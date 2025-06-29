"""
Gestione delle playlist AI settimanali con persistenza JSON.
Legge le playlist NO_DELETE per analizzare i gusti dell'utente e genera playlist settimanali.
"""

import os
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional
from plexapi.server import PlexServer
from plexapi.exceptions import NotFound

from .gemini_ai import configure_gemini, generate_playlist_prompt, get_gemini_playlist_data
from .helperClasses import Playlist as PlexPlaylist, Track as PlexTrack, UserInputs
from .plex import update_or_create_plex_playlist
from .database import get_library_index_stats

logger = logging.getLogger(__name__)

# Path per la persistenza JSON
WEEKLY_AI_STATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "state_data")
WEEKLY_AI_STATE_FILE = os.path.join(WEEKLY_AI_STATE_DIR, "weekly_ai_playlists.json")

def ensure_state_directory():
    """Assicura che la directory state_data esista."""
    os.makedirs(WEEKLY_AI_STATE_DIR, exist_ok=True)

def load_weekly_ai_state() -> Dict:
    """Carica lo stato delle playlist AI settimanali dal JSON."""
    ensure_state_directory()
    try:
        if os.path.exists(WEEKLY_AI_STATE_FILE):
            with open(WEEKLY_AI_STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Errore nel caricamento stato AI settimanale: {e}")
    
    return {"playlists": {}, "last_update": None}

def save_weekly_ai_state(state: Dict):
    """Salva lo stato delle playlist AI settimanali nel JSON."""
    ensure_state_directory()
    try:
        with open(WEEKLY_AI_STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        logger.info("Stato AI settimanale salvato con successo")
    except Exception as e:
        logger.error(f"Errore nel salvataggio stato AI settimanale: {e}")

def get_current_week_info() -> Dict[str, int]:
    """Restituisce informazioni sulla settimana corrente."""
    now = datetime.now()
    year, week_num, _ = now.isocalendar()
    return {"year": year, "week": week_num}

def read_no_delete_playlist_for_taste_analysis(plex: PlexServer, favorites_playlist_id: str) -> Optional[List[str]]:
    """
    Legge una playlist NO_DELETE per analizzare i gusti dell'utente.
    IMPORTANTE: Questa funzione è SOLO LETTURA, non modifica la playlist.
    """
    if not favorites_playlist_id:
        logger.warning("Nessun ID per la playlist dei preferiti fornito per analisi gusti.")
        return None
    
    try:
        playlist = plex.fetchItem(int(favorites_playlist_id))
        
        # Verifica che sia una playlist protetta
        preserve_tag = os.getenv("PRESERVE_TAG", "NO_DELETE")
        if preserve_tag.lower() not in playlist.title.lower():
            logger.warning(f"⚠️ Playlist '{playlist.title}' non contiene tag '{preserve_tag}' - potrebbe non essere protetta")
        
        logger.info(f"📖 Lettura playlist protetta '{playlist.title}' per analisi gusti (SOLO LETTURA)")
        
        # Estrae le tracce per l'analisi dei gusti
        tracks = []
        for track in playlist.items():
            try:
                artist = track.grandparentTitle if hasattr(track, 'grandparentTitle') else track.artist().title
                title = track.title
                tracks.append(f"{artist} - {title}")
            except Exception as track_error:
                logger.debug(f"Errore lettura traccia: {track_error}")
                continue
        
        logger.info(f"✅ Analizzate {len(tracks)} tracce da playlist protetta '{playlist.title}'")
        return tracks
        
    except NotFound:
        logger.error(f"❌ Playlist con ID '{favorites_playlist_id}' non trovata sul server Plex")
        return None
    except Exception as e:
        logger.error(f"❌ Errore lettura playlist protetta con ID '{favorites_playlist_id}': {e}")
        return None

def should_update_weekly_playlist(current_week_info: Dict, state: Dict, user_key: str) -> bool:
    """Determina se la playlist settimanale deve essere aggiornata."""
    user_playlist_key = f"{user_key}_weekly"
    
    # Se non esiste ancora una playlist per questo utente
    if user_playlist_key not in state["playlists"]:
        logger.info(f"🆕 Prima creazione playlist settimanale per utente '{user_key}'")
        return True
    
    # Controlla se siamo in una nuova settimana
    last_playlist = state["playlists"][user_playlist_key]
    last_week = last_playlist.get("week_info", {})
    
    if (current_week_info["year"] != last_week.get("year") or 
        current_week_info["week"] != last_week.get("week")):
        logger.info(f"🗓️ Nuova settimana rilevata per '{user_key}': Settimana {current_week_info['week']}, Anno {current_week_info['year']}")
        return True
    
    logger.info(f"⏭️ Stessa settimana per '{user_key}': Settimana {current_week_info['week']}, Anno {current_week_info['year']}")
    return False

def recreate_playlist_from_state(
    plex: PlexServer,
    user_inputs: UserInputs, 
    playlist_data: Dict,
    user_key: str
) -> Optional[object]:
    """Ricrea una playlist identica utilizzando i dati salvati nello stato JSON."""
    logger.info(f"🔄 Ricreazione playlist identica da stato JSON per '{user_key}'")
    
    try:
        # Crea oggetto playlist
        playlist_obj = PlexPlaylist(
            id=None,
            name=playlist_data["name"],
            description=playlist_data.get("description", ""),
            poster=None,
        )
        
        # Converte le tracce salvate in oggetti Track
        tracks = []
        for track_data in playlist_data["tracks"]:
            track = PlexTrack(
                title=track_data.get("title", ""),
                artist=track_data.get("artist", ""),
                album=track_data.get("album", ""),
                url=""
            )
            tracks.append(track)
        
        logger.info(f"🎵 Ricreazione playlist '{playlist_data['name']}' con {len(tracks)} tracce salvate")
        
        # Crea/aggiorna la playlist su Plex
        created_playlist = update_or_create_plex_playlist(plex, playlist_obj, tracks, user_inputs)
        
        if created_playlist:
            logger.info(f"✅ Playlist '{playlist_data['name']}' ricreata con successo da stato JSON")
            return created_playlist
        else:
            logger.error(f"❌ Fallimento ricreazione playlist '{playlist_data['name']}' da stato JSON")
            return None
            
    except Exception as e:
        logger.error(f"❌ Errore ricreazione playlist da stato JSON: {e}")
        return None

def create_new_weekly_playlist(
    plex: PlexServer,
    user_inputs: UserInputs,
    favorites_playlist_id: str,
    user_key: str,
    current_week_info: Dict,
    previous_week_tracks: Optional[List[Dict]] = None
) -> Optional[Dict]:
    """Crea una nuova playlist settimanale usando Gemini AI."""
    logger.info(f"🎨 Creazione nuova playlist settimanale AI per '{user_key}' - Settimana {current_week_info['week']}")
    
    # Configura Gemini
    model = configure_gemini()
    if not model:
        logger.error("❌ Gemini non configurato, impossibile creare playlist AI")
        return None
    
    # Legge i gusti dell'utente dalla playlist NO_DELETE (SOLO LETTURA)
    favorite_tracks = read_no_delete_playlist_for_taste_analysis(plex, favorites_playlist_id)
    if not favorite_tracks:
        logger.error("❌ Impossibile leggere playlist preferiti per analisi gusti")
        return None
    
    # Genera prompt per nuova playlist settimanale con dati aggiornati
    prompt = generate_playlist_prompt(
        favorite_tracks,
        custom_prompt=f"Crea una playlist settimanale di 25 brani per la settimana {current_week_info['week']} dell'anno {current_week_info['year']}. "
                     f"Basati sui gusti dell'utente ma aggiungi varietà e novità per rendere interessante questa settimana specifica. "
                     f"Includi alcuni brani dalle classifiche attuali per mantenere la playlist aggiornata.",
        previous_week_tracks=previous_week_tracks,
        include_charts_data=True
    )
    
    # Richiesta a Gemini
    playlist_data = get_gemini_playlist_data(model, prompt)
    if not playlist_data:
        logger.error("❌ Gemini non ha restituito dati validi per la playlist")
        return None
    
    # Aggiunge suffisso settimanale al nome
    original_name = playlist_data["playlist_name"]
    weekly_name = f"{original_name} - Settimana {current_week_info['week']}"
    playlist_data["playlist_name"] = weekly_name
    
    # Crea oggetti Plex
    playlist_obj = PlexPlaylist(
        id=None,
        name=weekly_name,
        description=playlist_data.get("description", ""),
        poster=None,
    )
    
    tracks = []
    for track_data in playlist_data["tracks"]:
        track = PlexTrack(
            title=track_data.get("title", ""),
            artist=track_data.get("artist", ""),
            album=track_data.get("album", ""),
            url=""
        )
        tracks.append(track)
    
    # Crea la playlist su Plex
    created_playlist = update_or_create_plex_playlist(plex, playlist_obj, tracks, user_inputs)
    
    if created_playlist:
        # Prepara dati per il salvataggio nello stato
        state_data = {
            "name": weekly_name,
            "description": playlist_data.get("description", ""),
            "tracks": playlist_data["tracks"],
            "week_info": current_week_info,
            "created_at": datetime.now().isoformat(),
            "plex_rating_key": created_playlist.ratingKey
        }
        
        logger.info(f"✅ Playlist settimanale '{weekly_name}' creata con successo")
        return state_data
    else:
        logger.error(f"❌ Fallimento creazione playlist settimanale '{weekly_name}'")
        return None

def manage_weekly_ai_playlist(
    plex: PlexServer,
    user_inputs: UserInputs,
    favorites_playlist_id: str,
    user_key: str
) -> bool:
    """
    Gestisce la playlist AI settimanale per un utente:
    - Crea nuova playlist se è una nuova settimana
    - Ricrea playlist esistente se siamo nella stessa settimana
    """
    logger.info(f"🤖 Gestione playlist AI settimanale per utente '{user_key}'")
    
    # Controllo stato indice libreria
    index_stats = get_library_index_stats()
    if index_stats['total_tracks_indexed'] == 0:
        logger.error(f"❌ Indice libreria Plex VUOTO! ({index_stats['total_tracks_indexed']} tracce indicizzate)")
        logger.error(f"⚠️ Playlist AI falliranno - esegui prima 'Indicizza Libreria' dalla homepage")
        return False
    else:
        logger.info(f"✅ Indice libreria: {index_stats['total_tracks_indexed']} tracce indicizzate")
    
    current_week_info = get_current_week_info()
    state = load_weekly_ai_state()
    user_playlist_key = f"{user_key}_weekly"
    
    try:
        if should_update_weekly_playlist(current_week_info, state, user_key):
            # NUOVA SETTIMANA: Crea playlist completamente nuova
            
            # Recupera tracce della settimana precedente per continuità
            previous_week_tracks = None
            if user_playlist_key in state["playlists"]:
                previous_week_tracks = state["playlists"][user_playlist_key].get("tracks", [])
            
            # Crea nuova playlist
            new_playlist_data = create_new_weekly_playlist(
                plex, user_inputs, favorites_playlist_id, user_key, 
                current_week_info, previous_week_tracks
            )
            
            if new_playlist_data:
                # Salva nel stato
                state["playlists"][user_playlist_key] = new_playlist_data
                state["last_update"] = datetime.now().isoformat()
                save_weekly_ai_state(state)
                return True
            else:
                return False
                
        else:
            # STESSA SETTIMANA: Ricrea playlist identica da JSON
            if user_playlist_key in state["playlists"]:
                playlist_data = state["playlists"][user_playlist_key]
                recreated_playlist = recreate_playlist_from_state(
                    plex, user_inputs, playlist_data, user_key
                )
                return recreated_playlist is not None
            else:
                logger.warning(f"⚠️ Nessun dato salvato per playlist settimanale di '{user_key}'")
                return False
                
    except Exception as e:
        logger.error(f"❌ Errore gestione playlist AI settimanale per '{user_key}': {e}")
        return False