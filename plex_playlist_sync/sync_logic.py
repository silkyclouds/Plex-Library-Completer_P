import os
import time
import sys
import logging
import concurrent.futures
from typing import List, Dict
from datetime import datetime, timedelta

from plexapi.server import PlexServer
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

from .utils.cleanup import delete_old_playlists, delete_previous_week_playlist
from .utils.deezer import deezer_playlist_sync
from .utils.helperClasses import UserInputs, Playlist as PlexPlaylist, Track as PlexTrack
from .utils.spotify import spotify_playlist_sync
from .utils.downloader import download_single_track_with_streamrip, DeezerLinkFinder
from .utils.gemini_ai import configure_gemini, get_plex_favorites_by_id, generate_playlist_prompt, get_gemini_playlist_data
from .utils.weekly_ai_manager import manage_weekly_ai_playlist
from .utils.plex import update_or_create_plex_playlist, search_plex_track
from .utils.state_manager import load_playlist_state, save_playlist_state
from .utils.database import (
    initialize_db, clear_library_index, add_track_to_index, bulk_add_tracks_to_index, get_missing_tracks,
    check_track_in_index, check_track_in_index_smart, update_track_status
)

load_dotenv()

def build_library_index(app_state: Dict):
    """
    Esegue una scansione completa della libreria Plex e popola l'indice locale.
    Versione PARALLELA con controlli robusti e debug esteso.
    """
    import os  # Import necessario per os.getenv
    logger.info("=== AVVIO INDICIZZAZIONE PARALLELA LIBRERIA PLEX ===")
    plex_url, plex_token = os.getenv("PLEX_URL"), os.getenv("PLEX_TOKEN")
    library_name = os.getenv("LIBRARY_NAME", "Musica")

    if not (plex_url and plex_token):
        logger.error("❌ URL o Token di Plex non configurati. Impossibile indicizzare.")
        app_state['status'] = "Errore: URL o Token Plex mancanti."
        return

    try:
        # FASE 1: Inizializzazione e controlli
        from .utils.database import initialize_db, clear_library_index, add_track_to_index, get_library_index_stats
        
        logger.info("🔧 Inizializzazione database...")
        initialize_db()
        
        # Verifica stato database
        initial_stats = get_library_index_stats()
        logger.info(f"📊 Stato iniziale indice: {initial_stats['total_tracks_indexed']} tracce")
        
        # Connessione con timeout esteso
        app_state['status'] = "Connessione a Plex Server..."
        plex = PlexServer(plex_url, plex_token, timeout=120)
        
        try:
            music_library = plex.library.section(library_name)
            logger.info(f"✅ Connesso alla libreria '{library_name}'")
        except Exception as lib_error:
            logger.error(f"❌ Errore accesso libreria '{library_name}': {lib_error}")
            app_state['status'] = f"Errore: Libreria '{library_name}' non trovata"
            return
        
        # FASE 2: Stima totale tracce
        app_state['status'] = "Stimando dimensione libreria..."
        try:
            # Prova a ottenere il totale con un metodo veloce
            total_estimate = len(music_library.search(libtype='track', limit=50000))
            logger.info(f"📊 Stima tracce nella libreria: ~{total_estimate}")
        except Exception:
            logger.warning("⚠️ Impossibile stimare dimensione libreria, procedo comunque")
            total_estimate = 0
        
        # FASE 3: Svuotamento indice esistente
        app_state['status'] = "Svuotamento indice esistente..."
        logger.info("🗺️ Svuotamento indice esistente...")
        clear_library_index()
        
        # FASE 4: Scarica TUTTE le tracce una volta sola (evita ripetuti fetch)
        logger.info("📥 Scaricamento completo tracce da Plex (una volta sola)...")
        all_tracks = music_library.search(libtype='track')
        total_tracks = len(all_tracks)
        logger.info(f"✅ Scaricate {total_tracks} tracce totali da Plex")
        
        # FASE 5: Indicizzazione a batch delle tracce già scaricate
        batch_size = 2500  # Batch ridotti per evitare timeout
        total_processed = 0
        total_indexed = 0
        
        logger.info(f"🚀 Avvio indicizzazione a batch (size: {batch_size})")
        
        container_start = 0
        batch_num = 0
        
        while container_start < total_tracks:
            try:
                batch_num += 1
                batch_end = min(container_start + batch_size, total_tracks)
                app_state['status'] = f"Batch {batch_num}: {container_start}-{batch_end} | Indicizzate: {total_indexed}"
                
                # Slice delle tracce già scaricate (nessun fetch aggiuntivo)
                batch_tracks = all_tracks[container_start:batch_end]
                
                if not batch_tracks:
                    logger.info(f"🏁 Fine indicizzazione - batch vuoto")
                    break
                
                logger.info(f"🔄 Processando batch {batch_num}: {len(batch_tracks)} tracce (slice {container_start}:{batch_end})")
                
                # Processa il batch con inserimento BULK (PERFORMANCE OTTIMIZZATA)
                try:
                    batch_indexed = bulk_add_tracks_to_index(batch_tracks)
                    total_indexed += batch_indexed
                    total_processed += len(batch_tracks)
                    batch_errors = len(batch_tracks) - batch_indexed
                    
                    # Update status ogni batch
                    app_state['status'] = f"Batch {batch_num}: {len(batch_tracks)} processate | Tot indicizzate: {total_indexed}"
                    
                except Exception as batch_error:
                    logger.error(f"Errore nel batch {batch_num}: {batch_error}")
                    batch_errors = len(batch_tracks)
                    batch_indexed = 0
                
                logger.info(f"✅ Batch {batch_num} completato: {batch_indexed}/{len(batch_tracks)} indicizzate, {batch_errors} errori")
                
                # Progress update ogni 5 batch
                if batch_num % 5 == 0:
                    current_stats = get_library_index_stats()
                    logger.info(f"📊 Progresso generale: {total_processed} processate, {current_stats['total_tracks_indexed']} nel DB")
                
                container_start += batch_size
                
                # Se il batch è più piccolo del batch_size, abbiamo finito
                if len(batch_tracks) < batch_size:
                    logger.info(f"🏁 Ultimo batch completato - dimensione: {len(batch_tracks)}")
                    break
                    
            except Exception as batch_error:
                logger.error(f"❌ Errore nel batch {batch_num}: {batch_error}")
                container_start += batch_size
                continue

        # FASE 5: Verifica finale
        final_stats = get_library_index_stats()
        final_status = f"INDICIZZAZIONE COMPLETATA! {total_processed} processate, {final_stats['total_tracks_indexed']} indicizzate con successo in {batch_num} batch"
        app_state['status'] = final_status
        logger.info(f"=== {final_status} ===")
        
        # Debug informazioni database
        from .utils.database import DB_PATH
        db_size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
        logger.info(f"📋 Database finale: {DB_PATH} ({db_size} bytes)")
        
    except Exception as e:
        logger.error(f"❌ Errore critico durante l'indicizzazione della libreria: {e}", exc_info=True)
        app_state['status'] = "Errore critico durante l'indicizzazione."


def sync_playlists_for_user(plex: PlexServer, user_inputs: UserInputs):
    """Esegue la sincronizzazione Spotify e Deezer per un singolo utente."""
    if not (os.getenv("SKIP_SPOTIFY_SYNC", "0") == "1"):
        logger.info(f"--- Avvio sync Spotify per utente {user_inputs.plex_token[:4]}... ---")
        spotify_playlist_sync(plex, user_inputs)
    
    if not (os.getenv("SKIP_DEEZER_SYNC", "0") == "1"):
        logger.info(f"--- Avvio sync Deezer per utente {user_inputs.plex_token[:4]}... ---")
        deezer_playlist_sync(plex, user_inputs)

def force_playlist_scan_and_missing_detection():
    """
    Forza una scansione delle playlist esistenti su Plex per rilevare tracce mancanti.
    ATTENZIONE: Richiede che l'indice libreria sia popolato per funzionare correttamente.
    """
    # Controllo preventivo indice libreria
    from .utils.database import get_library_index_stats
    index_stats = get_library_index_stats()
    
    if index_stats['total_tracks_indexed'] == 0:
        logger.error("❌ BLOCCO SCANSIONE FORZATA: Indice libreria VUOTO!")
        logger.error("⚠️ La scansione produrrebbe solo falsi positivi. Indicizza prima la libreria.")
        return
    
    logger.info(f"--- Avvio scansione forzata playlist (indice: {index_stats['total_tracks_indexed']} tracce) ---")
    
    plex_url = os.getenv("PLEX_URL")
    plex_token = os.getenv("PLEX_TOKEN")
    
    if not (plex_url and plex_token):
        logger.error("Credenziali Plex non configurate")
        return
    
    try:
        plex = PlexServer(plex_url, plex_token, timeout=60)
        
        # Ottieni tutte le playlist dell'utente e filtra quelle musicali
        all_playlists = plex.playlists()
        logger.info(f"Trovate {len(all_playlists)} playlist totali")
        
        # Filtra playlist che non dovrebbero essere scansionate
        tv_keywords = ['simpsons', 'simpson', 'family guy', 'american dad', 'king of the hill', 
                      'episode', 'tv', 'show', 'serie', 'film', 'movie', 'cinema']
        
        music_playlists = []
        for playlist in all_playlists:
            playlist_name_lower = playlist.title.lower()
            
            # Skippa playlist TV/Film
            is_tv_playlist = any(keyword in playlist_name_lower for keyword in tv_keywords)
            
            # Skippa playlist NO_DELETE (create da Plex, non possono avere tracce mancanti)
            is_no_delete = 'no_delete' in playlist_name_lower
            
            if is_tv_playlist:
                logger.info(f"🎭 Saltata playlist TV/Film: '{playlist.title}'")
            elif is_no_delete:
                logger.info(f"🚫 Saltata playlist NO_DELETE: '{playlist.title}' (creata da Plex)")
            else:
                music_playlists.append(playlist)
        
        logger.info(f"🎵 Scansione di {len(music_playlists)} playlist musicali (saltate {len(all_playlists) - len(music_playlists)} TV/Film)")
        
        total_missing_found = 0
        
        for playlist in music_playlists:
            try:
                logger.info(f"Scansione playlist: {playlist.title}")
                
                # Ottieni tracce della playlist
                playlist_tracks = playlist.items()
                missing_count = 0
                
                for track in playlist_tracks:
                    try:
                        # Usa il nuovo sistema di matching intelligente
                        if not check_track_in_index_smart(track.title, track.grandparentTitle):
                            # Traccia potenzialmente mancante, aggiungila al DB
                            track_data = {
                                'title': track.title,
                                'artist': track.grandparentTitle,
                                'album': track.parentTitle if hasattr(track, 'parentTitle') else '',
                                'source_playlist_title': playlist.title,
                                'source_playlist_id': playlist.ratingKey
                            }
                            
                            from .utils.database import add_missing_track
                            add_missing_track(track_data)
                            missing_count += 1
                            total_missing_found += 1
                            
                    except Exception as track_error:
                        logger.warning(f"Errore nel processare traccia {track.title}: {track_error}")
                        continue
                
                if missing_count > 0:
                    logger.info(f"Playlist '{playlist.title}': {missing_count} tracce mancanti rilevate")
                    
            except Exception as playlist_error:
                logger.warning(f"Errore nel processare playlist {playlist.title}: {playlist_error}")
                continue
        
        logger.info(f"--- Scansione completata: {total_missing_found} tracce mancanti totali rilevate ---")
        
    except Exception as e:
        logger.error(f"Errore durante la scansione forzata playlist: {e}", exc_info=True)


def run_downloader_only():
    """Legge i brani mancanti dal DB, cerca i link in parallelo e avvia il download."""
    logger.info("--- Avvio ricerca e download automatico per brani mancanti dal DB ---")
    missing_tracks_from_db = get_missing_tracks()
    
    if not missing_tracks_from_db:
        logger.info("Nessun brano mancante nel database da processare.")
        return False

    logger.info(f"Trovati {len(missing_tracks_from_db)} brani mancanti. Avvio ricerca link in parallelo...")
    tracks_with_links = []  # Lista di (track_id, link) per mantenere associazione
    
    # Usiamo un ThreadPoolExecutor per parallelizzare le richieste di rete
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        # Creiamo un future per ogni chiamata all'API
        future_to_track = {executor.submit(DeezerLinkFinder.find_track_link, {'title': track[1], 'artist': track[2]}): track for track in missing_tracks_from_db}
        
        for future in concurrent.futures.as_completed(future_to_track):
            track = future_to_track[future]
            link = future.result()
            if link:
                track_id = track[0]  # ID della traccia dal database
                tracks_with_links.append((track_id, link))
                logger.info(f"Link trovato per '{track[1]}' di '{track[2]}': {link}")

    if tracks_with_links:
        logger.info(f"Trovati {len(tracks_with_links)} link da scaricare.")
        
        # Raggruppa per link unici per evitare download doppi
        unique_links = {}
        for track_id, link in tracks_with_links:
            if link not in unique_links:
                unique_links[link] = []
            unique_links[link].append(track_id)
        
        # Scarica ogni link unico e aggiorna tutte le tracce associate
        for link, track_ids in unique_links.items():
            try:
                logger.info(f"Avvio download: {link} (per {len(track_ids)} tracce)")
                download_single_track_with_streamrip(link)
                
                # Aggiorna lo status di tutte le tracce associate a questo link
                for track_id in track_ids:
                    update_track_status(track_id, 'downloaded')
                    logger.info(f"Status aggiornato a 'downloaded' per traccia ID {track_id}")
                    
            except Exception as e:
                logger.error(f"Errore durante il download di {link}: {e}")
                # Marca le tracce come errore invece che downloaded
                for track_id in track_ids:
                    logger.warning(f"Download fallito per traccia ID {track_id}")
        
        return True
    else:
        logger.info("Nessun link di download trovato per i brani mancanti.")
        return False


def rescan_and_update_missing():
    """Scansiona le tracce aggiunte di recente a Plex e aggiorna la lista dei mancanti."""
    logger.info("--- Avvio scansione post-download per pulire la lista dei brani mancanti ---")
    plex_url, plex_token = os.getenv("PLEX_URL"), os.getenv("PLEX_TOKEN")
    if not (plex_url and plex_token):
        logger.error("URL o Token Plex principale non configurati.")
        return

    try:
        plex = PlexServer(plex_url, plex_token)
        music_library = plex.library.section(os.getenv("LIBRARY_NAME", "Musica"))
        
        logger.info("Ricerca di tracce aggiunte di recente a Plex per aggiornare l'indice...")
        recently_added = music_library.search(sort="addedAt:desc", limit=500)
        
        newly_indexed_count = 0
        thirty_minutes_ago = datetime.now() - timedelta(minutes=30)

        for track in recently_added:
            if track.addedAt >= thirty_minutes_ago:
                add_track_to_index(track)
                newly_indexed_count += 1
        
        if newly_indexed_count > 0:
            logger.info(f"Aggiunte {newly_indexed_count} nuove tracce all'indice locale.")
        else:
            logger.info("Nessuna traccia nuova trovata da aggiungere all'indice.")

        tracks_to_verify = get_missing_tracks()
        logger.info(f"Verifica di {len(tracks_to_verify)} brani dalla lista dei mancanti...")

        updated_tracks = []
        for track_info in tracks_to_verify:
            if check_track_in_index_smart(track_info[1], track_info[2]):
                logger.info(f"SUCCESSO: La traccia '{track_info[1]}' è ora presente. Aggiorno lo stato.")
                update_track_status(track_info[0], 'downloaded')
                updated_tracks.append(track_info)
        
        # Auto-aggiorna le playlist AI se ci sono nuove tracce disponibili
        if updated_tracks:
            auto_update_ai_playlists(plex, updated_tracks)
        
        logger.info("--- Scansione post-download completata ---")

    except Exception as e:
        logger.error(f"Errore critico durante la scansione post-download: {e}", exc_info=True)


def run_cleanup_only():
    """Esegue solo la pulizia delle vecchie playlist per tutti gli utenti."""
    if not (os.getenv("SKIP_CLEANUP", "0") == "1"):
        user_tokens = [os.getenv("PLEX_TOKEN"), os.getenv("PLEX_TOKEN_USERS")]
        for token in filter(None, user_tokens):
            try:
                plex = PlexServer(os.getenv("PLEX_URL"), token)
                logger.info(f"--- Avvio pulizia vecchie playlist per utente {token[:4]}... ---")
                delete_old_playlists(plex, os.getenv("LIBRARY_NAME"), int(os.getenv("WEEKS_LIMIT")), os.getenv("PRESERVE_TAG"))
            except Exception as e:
                logger.error(f"Errore durante la connessione a Plex per la pulizia (utente {token[:4]}...): {e}")


def run_full_sync_cycle():
    """Esegue un ciclo completo di sincronizzazione, AI, e poi tenta il download/rescan."""
    logger.info("Avvio di un nuovo ciclo di sincronizzazione completo...")
    
    RUN_GEMINI_PLAYLIST_CREATION = os.getenv("RUN_GEMINI_PLAYLIST_CREATION", "0") == "1"
    AUTO_DELETE_AI_PLAYLIST = os.getenv("AUTO_DELETE_AI_PLAYLIST", "0") == "1"
    RUN_DOWNLOADER = os.getenv("RUN_DOWNLOADER", "1") == "1"
    
    sync_start_time = datetime.now()
    current_year, current_week, _ = sync_start_time.isocalendar()

    user_configs = [
        {"name": "main user", "token": os.getenv("PLEX_TOKEN"), "favorites_id": os.getenv("PLEX_FAVORITES_PLAYLIST_ID_MAIN")},
        {"name": "secondary user", "token": os.getenv("PLEX_TOKEN_USERS"), "favorites_id": os.getenv("PLEX_FAVORITES_PLAYLIST_ID_SECONDARY")}
    ]
    
    gemini_model = configure_gemini() if RUN_GEMINI_PLAYLIST_CREATION else None
    
    for user_config in user_configs:
        token = user_config["token"]
        name = user_config["name"]
        favorites_playlist_id = user_config["favorites_id"]

        if not token: continue

        logger.info(f"--- Processing user: {name} ---")
        user_inputs = UserInputs(
            plex_url=os.getenv("PLEX_URL"), plex_token=token,
            plex_token_others=os.getenv("PLEX_TOKEN_USERS"),
            plex_min_songs=int(os.getenv("PLEX_MIN_SONGS", 0)),
            write_missing_as_csv=False,
            append_service_suffix=os.getenv("APPEND_SERVICE_SUFFIX", "1") == "1",
            add_playlist_poster=os.getenv("ADD_PLAYLIST_POSTER", "1") == "1",
            add_playlist_description=os.getenv("ADD_PLAYLIST_DESCRIPTION", "1") == "1",
            append_instead_of_sync=False, wait_seconds=0,
            spotipy_client_id=os.getenv("SPOTIFY_CLIENT_ID"), spotipy_client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
            spotify_user_id=os.getenv("SPOTIFY_USER_ID"), deezer_user_id=os.getenv("DEEZER_USER_ID"),
            deezer_playlist_ids=os.getenv("DEEZER_PLAYLIST_ID_SECONDARY") if name == "secondary user" else os.getenv("DEEZER_PLAYLIST_ID"),
            spotify_playlist_ids=os.getenv("SPOTIFY_PLAYLIST_IDS_SECONDARY") if name == "secondary user" else os.getenv("SPOTIFY_PLAYLIST_IDS"),
            spotify_categories=[], country=os.getenv("COUNTRY")
        )
        
        try:
            plex = PlexServer(user_inputs.plex_url, user_inputs.plex_token)
            sync_playlists_for_user(plex, user_inputs)
            
            if gemini_model and favorites_playlist_id:
                logger.info(f"--- Gestione Playlist AI Settimanale per {name} ---")
                try:
                    # Usa il nuovo sistema settimanale con persistenza JSON
                    weekly_success = manage_weekly_ai_playlist(
                        plex, user_inputs, favorites_playlist_id, 
                        "main" if name == "main user" else "secondary"
                    )
                    if weekly_success:
                        logger.info(f"✅ Playlist AI settimanale gestita con successo per {name}")
                    else:
                        logger.warning(f"⚠️ Problemi nella gestione playlist AI settimanale per {name}")
                except Exception as ai_error:
                    logger.error(f"❌ Errore gestione playlist AI settimanale per {name}: {ai_error}")
                    continue

        except Exception as e:
            logger.error(f"Errore critico durante l'elaborazione di {name}: {e}", exc_info=True)

    logger.info("Ciclo di sincronizzazione e AI completato.")
    
    # CONTROLLO CRITICO: Non eseguire scansione playlist se l'indice libreria è vuoto!
    from .utils.database import get_library_index_stats
    index_stats = get_library_index_stats()
    
    if index_stats['total_tracks_indexed'] == 0:
        logger.error("❌ BLOCCO SCANSIONE: Indice libreria VUOTO! Non posso rilevare tracce mancanti senza indice.")
        logger.error("⚠️ Esegui 'Indicizza Libreria' dalla homepage prima di continuare.")
        logger.error("🛑 Saltando scansione playlist e download per evitare falsi positivi massivi.")
        return  # Esce dal ciclo senza fare nulla
    
    logger.info(f"✅ Indice libreria OK: {index_stats['total_tracks_indexed']} tracce indicizzate")
    
    # Forza scansione playlist per rilevare missing tracks se il DB è vuoto
    current_missing_count = len(get_missing_tracks())
    if current_missing_count == 0:
        logger.info("Nessuna traccia mancante nel DB. Forzo scansione playlist...")
        force_playlist_scan_and_missing_detection()
    else:
        logger.info(f"Trovate {current_missing_count} tracce mancanti nel DB esistente.")
    
    if RUN_DOWNLOADER:
        download_attempted = run_downloader_only()
        if download_attempted:
            wait_time = int(os.getenv("PLEX_SCAN_WAIT_TIME", "300"))
            logger.info(f"Attendo {wait_time} secondi per dare a Plex il tempo di indicizzare...")
            time.sleep(wait_time)
            rescan_and_update_missing()
    else:
        logger.warning("Download automatico saltato come da configurazione.")
    
    logger.info("--- Ciclo completo terminato ---")


def auto_update_ai_playlists(plex, updated_tracks):
    """
    Aggiorna automaticamente le playlist AI gestite quando nuove tracce sono disponibili.
    
    Args:
        plex: PlexServer instance (utente principale)
        updated_tracks: Lista di tracce appena diventate disponibili
    """
    logger.info("🔄 Auto-aggiornamento playlist AI con nuove tracce...")
    
    try:
        from .utils.database import get_managed_ai_playlists_for_user
        from .utils.plex import search_plex_track, update_or_create_plex_playlist
        
        # Prepara connessioni per entrambi gli utenti
        plex_url = os.getenv("PLEX_URL")
        main_token = os.getenv("PLEX_TOKEN") 
        secondary_token = os.getenv("PLEX_TOKEN_USERS")
        
        # Crea connessioni separate per ogni utente
        plex_connections = {}
        if main_token:
            plex_connections['main'] = PlexServer(plex_url, main_token)
        if secondary_token:
            plex_connections['secondary'] = PlexServer(plex_url, secondary_token)
        
        # Ottieni playlist per ogni utente
        updated_count = 0
        for user_type in ['main', 'secondary']:
            if user_type not in plex_connections:
                continue
                
            user_plex = plex_connections[user_type]
            user_playlists = get_managed_ai_playlists_for_user(user_type)
            
            if not user_playlists:
                logger.info(f"Nessuna playlist AI per utente {user_type}")
                continue
                
            logger.info(f"Trovate {len(user_playlists)} playlist AI per utente {user_type}")
            
            for playlist_data in user_playlists:
                playlist_title = playlist_data['title']  # title dalla tabella managed_ai_playlists
                source_playlist_titles = [track[4] for track in updated_tracks]  # source_playlist_title
                
                # Controlla se questa playlist AI ha tracce tra quelle appena scaricate
                if playlist_title in source_playlist_titles:
                    logger.info(f"🎵 Aggiornamento playlist AI '{playlist_title}' per utente {user_type}")
                    
                    try:
                        # Trova la playlist su Plex dell'utente corretto
                        existing_playlist = None
                        for playlist in user_plex.playlists():
                            if playlist.title == playlist_title:
                                existing_playlist = playlist
                                break
                        
                        if existing_playlist:
                            # Ottieni le tracce che ora sono disponibili per questa playlist
                            new_tracks_for_playlist = [
                                track for track in updated_tracks 
                                if track[4] == playlist_title  # source_playlist_title
                            ]
                            
                            # Cerca e aggiungi le nuove tracce trovate
                            tracks_to_add = []
                            for track_info in new_tracks_for_playlist:
                                track_title, track_artist = track_info[1], track_info[2]
                                
                                # Cerca la traccia su Plex usando la connessione dell'utente corretto
                                plex_track = search_plex_track(user_plex, track_title, track_artist)
                                if plex_track:
                                    tracks_to_add.append(plex_track)
                                    logger.info(f"✅ Trovata traccia per aggiunta: '{track_title}' di '{track_artist}'")
                            
                            # Aggiungi le nuove tracce alla playlist
                            if tracks_to_add:
                                current_tracks = existing_playlist.items()
                                all_tracks = list(current_tracks) + tracks_to_add
                                
                                # Aggiorna la playlist con tutte le tracce (vecchie + nuove)
                                existing_playlist.clear()
                                existing_playlist.addItems(all_tracks)
                                
                                logger.info(f"🎉 Playlist '{playlist_title}' aggiornata con {len(tracks_to_add)} nuove tracce")
                                updated_count += 1
                            else:
                                logger.info(f"⚠️ Nessuna nuova traccia trovata su Plex per '{playlist_title}'")
                        else:
                            logger.warning(f"❌ Playlist '{playlist_title}' non trovata su Plex per utente {user_type}")
                            
                    except Exception as playlist_error:
                        logger.error(f"Errore aggiornamento playlist '{playlist_title}' per utente {user_type}: {playlist_error}")
                        continue
        
        if updated_count > 0:
            logger.info(f"✅ Auto-aggiornamento completato: {updated_count} playlist AI aggiornate")
        else:
            logger.info("ℹ️ Nessuna playlist AI necessitava aggiornamenti")
            
    except Exception as e:
        logger.error(f"Errore durante auto-aggiornamento playlist AI: {e}", exc_info=True)