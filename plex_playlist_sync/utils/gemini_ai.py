import os
import logging
import json
from typing import List, Dict, Optional

import google.generativeai as genai
from plexapi.server import PlexServer
from plexapi.exceptions import NotFound

from .helperClasses import Playlist as PlexPlaylist, Track as PlexTrack, UserInputs
from .plex import update_or_create_plex_playlist
from .database import add_managed_ai_playlist, get_managed_ai_playlists_for_user
from .music_charts import music_charts_searcher

# Otteniamo il logger che è già stato configurato in app.py
logger = logging.getLogger(__name__)

def configure_gemini() -> Optional[genai.GenerativeModel]:
    """Configura e restituisce il modello Gemini se la chiave API è presente."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.warning("GEMINI_API_KEY non trovata nel file .env. La creazione della playlist AI verrà saltata.")
        return None
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        return model
    except Exception as e:
        logger.error(f"Errore nella configurazione di Gemini: {e}")
        return None

def get_plex_favorites_by_id(plex: PlexServer, playlist_id: str) -> Optional[List[str]]:
    """Recupera le tracce da una playlist Plex usando il suo ID univoco (ratingKey)."""
    if not playlist_id:
        logger.warning("Nessun ID per la playlist dei preferiti fornito. Salto il recupero tracce.")
        return None
    logger.info(f"Tento di recuperare la playlist dei preferiti con ID: {playlist_id}")
    try:
        playlist = plex.fetchItem(int(playlist_id))
        tracks = [f"{track.artist().title} - {track.title}" for track in playlist.items()]
        logger.info(f"Trovate {len(tracks)} tracce nella playlist '{playlist.title}'.")
        return tracks
    except NotFound:
        logger.error(f"ERRORE: Playlist con ID '{playlist_id}' non trovata sul server Plex. Controlla l'ID nel file .env.")
        return None
    except Exception as e:
        logger.error(f"Errore imprevisto durante il recupero della playlist con ID '{playlist_id}': {e}")
        return None

def generate_playlist_prompt(
    favorite_tracks: List[str],
    custom_prompt: Optional[str] = None,
    previous_week_tracks: Optional[List[Dict]] = None,
    include_charts_data: bool = True
) -> str:
    """Crea un prompt robusto per produrre una playlist in JSON valido con dati di classifiche aggiornati."""
    tracks_str = "\n".join(favorite_tracks)
    
    # Raccolta dati musicali aggiornati
    charts_section = ""
    if include_charts_data:
        try:
            logger.info("Raccogliendo dati musicali aggiornati per informare Gemini...")
            music_data = music_charts_searcher.get_comprehensive_music_data(
                context=custom_prompt if custom_prompt else "playlist generation"
            )
            
            charts_info = []
            
            # Billboard Hot 100
            if music_data.get("charts", {}).get("billboard_hot_100"):
                billboard_top_10 = music_data["charts"]["billboard_hot_100"][:10]
                billboard_str = "\n".join([f"{t['position']}. {t['artist']} - {t['title']}" for t in billboard_top_10])
                charts_info.append(f"BILLBOARD HOT 100 (Top 10 attuale):\n{billboard_str}")
            
            # Spotify Global
            if music_data.get("charts", {}).get("spotify_global"):
                spotify_top_10 = music_data["charts"]["spotify_global"][:10]
                spotify_str = "\n".join([f"{t['position']}. {t['artist']} - {t['title']}" for t in spotify_top_10])
                charts_info.append(f"SPOTIFY GLOBAL TOP 10:\n{spotify_str}")
            
            # Classifiche italiane
            if music_data.get("charts", {}).get("italian"):
                italian_top_10 = music_data["charts"]["italian"][:10]
                italian_str = "\n".join([f"{t['position']}. {t['artist']} - {t['title']}" for t in italian_top_10])
                charts_info.append(f"CLASSIFICA ITALIANA (Top 10):\n{italian_str}")
            
            # Tendenze stagionali
            if music_data.get("trends", {}).get("seasonal"):
                seasonal_data = music_data["trends"]["seasonal"]
                season = seasonal_data.get("season", "unknown")
                trends = seasonal_data.get("trends", [])[:5]
                if trends:
                    seasonal_str = "\n".join([f"- {t['artist']} - {t['title']}" for t in trends])
                    charts_info.append(f"TENDENZE STAGIONALI ({season.upper()}):\n{seasonal_str}")
            
            # Tendenze per genere (se il prompt contiene riferimenti a generi)
            genre_keywords = {
                "rock": ["rock", "metal", "alternative", "indie"],
                "pop": ["pop", "mainstream", "radio"],
                "electronic": ["electronic", "edm", "house", "techno", "dance"],
                "hip-hop": ["hip-hop", "rap", "trap", "urban"]
            }
            
            prompt_lower = (custom_prompt or "").lower()
            for genre, keywords in genre_keywords.items():
                if any(keyword in prompt_lower for keyword in keywords):
                    genre_trends = music_data.get("trends", {}).get(genre, [])[:5]
                    if genre_trends:
                        genre_str = "\n".join([f"- {t['artist']} - {t['title']} ({t['trend']})" for t in genre_trends])
                        charts_info.append(f"TENDENZE {genre.upper()}:\n{genre_str}")
            
            if charts_info:
                charts_section = f"""
DATI MUSICALI AGGIORNATI (utilizza questi per ispirazione e per includere brani attuali):
---
{chr(10).join(charts_info)}
---
ISTRUZIONE: Usa questi dati per includere brani attuali e di tendenza nella playlist, bilanciandoli con i gusti dell'utente.
"""
            logger.info("Dati musicali aggiornati integrati nel prompt con successo")
        except Exception as e:
            logger.warning(f"Impossibile recuperare dati musicali aggiornati: {e}")
            charts_section = ""
    
    if custom_prompt:
        core_prompt = custom_prompt.strip()
        previous_week_section = ""
    else:
        core_prompt = "Genera una playlist completamente nuova di 50 canzoni basata sui gusti dimostrati nella lista sottostante. Includi un mix di classici e novità."
        if previous_week_tracks:
            previous_tracks_str = "\n".join([f"- {track['artist']} - {track['title']}" for track in previous_week_tracks])
            previous_week_section = f"""
LISTA TRACCE SETTIMANA PRECEDENTE (per continuità):
---
{previous_tracks_str}
---
ISTRUZIONE SPECIALE: Per creare una "storia musicale", includi nella nuova playlist tra i 5 e i 10 brani dalla lista della settimana precedente che si legano meglio con le nuove canzoni che sceglierai.
"""
        else:
            previous_week_section = ""

    prompt = f"""
Sei un DJ esperto con accesso a dati musicali aggiornati. Il tuo compito è creare una playlist basata su un prompt e una lista di tracce preferite.
PROMPT:
{core_prompt}

LISTA TRACCE PREFERITE (per riferimento sui gusti generali):
---
{tracks_str}
---
{charts_section}
{previous_week_section}
REGOLE DI RISPOSTA OBBLIGATORIE:
La tua risposta deve essere **esclusivamente un blocco di codice JSON valido**, senza testo introduttivo o commenti.
Il JSON deve avere questa struttura esatta:
{{
  "playlist_name": "Un Nome Creativo in Italiano (max 4 parole)",
  "description": "Una breve descrizione in italiano (max 1 frase).",
  "tracks": [
    {{ "artist": "Artista Traccia 1", "title": "Titolo Traccia 1" }},
    {{ "artist": "Artista Traccia 2", "title": "Titolo Traccia 2" }}
  ]
}}

IMPORTANTE: Bilancia sapientemente i gusti personali dell'utente con le tendenze attuali per creare una playlist moderna e personalizzata.
"""
    return prompt.strip()

def get_gemini_playlist_data(model: genai.GenerativeModel, prompt: str) -> Optional[Dict]:
    """Invia il prompt a Gemini e restituisce il JSON parsificato."""
    logger.info("Invio richiesta a Gemini per la creazione della playlist...")
    try:
        response = model.generate_content(prompt)
        cleaned_text = response.text.strip()
        start_index = cleaned_text.find('{')
        end_index = cleaned_text.rfind('}') + 1
        if start_index == -1 or end_index == 0:
            raise ValueError("Nessun oggetto JSON valido trovato nella risposta.")
        
        json_str = cleaned_text[start_index:end_index]
        playlist_data = json.loads(json_str)
        logger.info(f"Playlist generata da Gemini: '{playlist_data.get('playlist_name')}'.")
        return playlist_data
    except Exception as e:
        logger.error(f"Errore nel parsing della risposta di Gemini: {e}")
        logger.error(f"Risposta ricevuta che ha causato l'errore:\n{response.text if 'response' in locals() else 'Nessuna risposta ricevuta'}")
        return None

def list_ai_playlists(plex: PlexServer) -> List[Dict]:
    """Recupera la lista delle playlist AI gestite dal database locale."""
    logger.info("Recupero delle playlist AI gestite dal database...")
    # La logica ora è centralizzata nel DB per coerenza
    return get_managed_ai_playlists_for_user(plex.myPlexAccount().username)


def generate_on_demand_playlist(
    plex: PlexServer,
    user_inputs: UserInputs,
    favorites_playlist_id: str,
    custom_prompt: Optional[str],
    selected_user_key: str,
    include_charts_data: bool = True
):
    """Genera una playlist on-demand, la crea su Plex e la salva nel DB locale."""
    logger.info(f"Generazione playlist on-demand avviata per utente {selected_user_key}…")

    model = configure_gemini()
    if not model: return False

    favorite_tracks = get_plex_favorites_by_id(plex, favorites_playlist_id)
    if not favorite_tracks: return False

    prompt = generate_playlist_prompt(favorite_tracks, custom_prompt, include_charts_data=include_charts_data)
    playlist_data = get_gemini_playlist_data(model, prompt)

    if not (playlist_data and playlist_data.get("tracks") and playlist_data.get("playlist_name")):
        logger.error("Dati playlist Gemini mancanti o non validi.")
        return False

    new_playlist_obj = PlexPlaylist(
        id=None,
        name=playlist_data["playlist_name"],
        description=playlist_data.get("description", ""),
        poster=None,
    )
    new_tracks = [PlexTrack(title=t.get("title", ""), artist=t.get("artist", ""), album="", url="") for t in playlist_data["tracks"]]
    
    created_plex_playlist = update_or_create_plex_playlist(plex, new_playlist_obj, new_tracks, user_inputs)

    if created_plex_playlist:
        db_playlist_info = {
            'plex_rating_key': created_plex_playlist.ratingKey,
            'title': created_plex_playlist.title,
            'description': created_plex_playlist.summary,
            'user': selected_user_key,
            'tracklist': playlist_data.get("tracks", [])
        }
        add_managed_ai_playlist(db_playlist_info)
        return True
    else:
        logger.error("La creazione della playlist su Plex è fallita, non la aggiungo al DB.")
        return False

def get_music_charts_preview() -> Dict:
    """Restituisce un'anteprima dei dati delle classifiche musicali disponibili."""
    logger.info("Generando anteprima dati classifiche musicali...")
    try:
        data = music_charts_searcher.get_comprehensive_music_data("preview")
        
        preview = {
            "timestamp": data.get("timestamp"),
            "charts_available": [],
            "trends_available": [],
            "news_count": len(data.get("news", []))
        }
        
        # Riassunto classifiche
        charts = data.get("charts", {})
        for chart_name, chart_data in charts.items():
            if chart_data:
                preview["charts_available"].append({
                    "name": chart_name,
                    "count": len(chart_data),
                    "top_3": chart_data[:3] if len(chart_data) >= 3 else chart_data
                })
        
        # Riassunto tendenze
        trends = data.get("trends", {})
        for trend_name, trend_data in trends.items():
            if trend_data:
                if trend_name == "seasonal":
                    preview["trends_available"].append({
                        "name": f"seasonal_{trend_data.get('season', 'unknown')}",
                        "count": len(trend_data.get("trends", [])),
                        "season": trend_data.get("season")
                    })
                else:
                    preview["trends_available"].append({
                        "name": trend_name,
                        "count": len(trend_data),
                        "sample": trend_data[:2] if len(trend_data) >= 2 else trend_data
                    })
        
        logger.info(f"Anteprima generata: {len(preview['charts_available'])} classifiche, {len(preview['trends_available'])} tendenze")
        return preview
        
    except Exception as e:
        logger.error(f"Errore nella generazione anteprima classifiche: {e}")
        return {"error": str(e)}

def test_music_charts_integration() -> bool:
    """Testa l'integrazione delle classifiche musicali."""
    logger.info("Test integrazione classifiche musicali...")
    try:
        # Test ricerca classifiche
        billboard = music_charts_searcher.get_billboard_hot_100()
        spotify = music_charts_searcher.get_spotify_global_top_50()
        italian = music_charts_searcher.get_italian_charts()
        seasonal = music_charts_searcher.get_seasonal_trends()
        
        # Test ricerca per genere
        rock_trends = music_charts_searcher.get_genre_trending("rock")
        pop_trends = music_charts_searcher.get_genre_trending("pop")
        
        # Test ricerca notizie
        rock_news = music_charts_searcher.search_music_news("rock")
        
        # Test dati completi
        full_data = music_charts_searcher.get_comprehensive_music_data("test")
        
        results = {
            "billboard_count": len(billboard) if billboard else 0,
            "spotify_count": len(spotify) if spotify else 0,
            "italian_count": len(italian) if italian else 0,
            "seasonal_available": seasonal is not None,
            "rock_trends_count": len(rock_trends) if rock_trends else 0,
            "pop_trends_count": len(pop_trends) if pop_trends else 0,
            "rock_news_count": len(rock_news) if rock_news else 0,
            "full_data_sections": len(full_data.keys()) if full_data else 0
        }
        
        success = all([
            results["billboard_count"] > 0,
            results["spotify_count"] > 0,
            results["italian_count"] > 0,
            results["seasonal_available"],
            results["full_data_sections"] > 0
        ])
        
        logger.info(f"Test completato. Successo: {success}, Risultati: {results}")
        return success
        
    except Exception as e:
        logger.error(f"Errore nel test integrazione classifiche: {e}")
        return False