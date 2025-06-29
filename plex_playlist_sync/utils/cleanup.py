import logging
from datetime import datetime, timedelta
from plexapi.server import PlexServer
import os
from plexapi.exceptions import NotFound

def delete_old_playlists(plex: PlexServer, library_name: str, weeks_limit: int, preserve_tag: str = "NO_DELETE") -> None:
    """
    Elimina le playlist della libreria specificata che sono più vecchie del limite indicato (in settimane),
    a meno che il titolo della playlist contenga il tag di esclusione.
    La cancellazione avviene solo se la variabile d'ambiente FORCE_DELETE_OLD_PLAYLISTS è impostata a "1".
    """
    # --- MODIFICA: Legge la variabile d'ambiente per forzare la cancellazione ---
    force_delete = os.getenv("FORCE_DELETE_OLD_PLAYLISTS", "0") == "1"

    try:
        library = plex.library.section(library_name)
        logging.info(f"Libreria '{library_name}' trovata per la pulizia.")
    except Exception as e:
        logging.error(f"Errore: Libreria '{library_name}' non trovata durante la pulizia. Errore: {e}")
        return

    playlists_to_delete = []
    oggi = datetime.now()
    cutoff_date = oggi - timedelta(weeks=weeks_limit)

    for playlist in library.playlists():
        # Skip playlist if title contains the preserve tag (case-insensitive)
        if preserve_tag.lower() in playlist.title.lower():
            logging.info(f"Playlist '{playlist.title}' contrassegnata per NON cancellare.")
            continue

        if hasattr(playlist, 'addedAt'):
            creation_date = playlist.addedAt
            if creation_date < cutoff_date:
                playlists_to_delete.append(playlist)
                logging.info(f"Playlist da eliminare: '{playlist.title}' (Creato il {creation_date.strftime('%Y-%m-%d')})")
        else:
            logging.warning(f"Playlist '{playlist.title}' manca dell'attributo 'addedAt', ignorata durante la pulizia.")

    if playlists_to_delete:
        # --- MODIFICA: Rimosso input(), la conferma è automatica se il flag è attivo ---
        if force_delete:
            logging.warning(f"FORCE_DELETE_OLD_PLAYLISTS è attivo. Eliminazione di {len(playlists_to_delete)} playlist in corso...")
            for pl in playlists_to_delete:
                try:
                    pl.delete()
                    logging.info(f"Playlist '{pl.title}' eliminata.")
                except Exception as e:
                    logging.error(f"Impossibile eliminare la playlist '{pl.title}': {e}")
        else:
            logging.info(f"Trovate {len(playlists_to_delete)} playlist da eliminare, ma la cancellazione automatica non è attiva. Imposta FORCE_DELETE_OLD_PLAYLISTS=1 nel file .env per procedere.")
    else:
        logging.info("Nessuna playlist vecchia trovata da eliminare.")
        
        
# In utils/cleanup.py

def delete_previous_week_playlist(plex: PlexServer, base_playlist_name: str, current_week: int):
    """
    Cerca e cancella la versione della settimana precedente di una specifica playlist.
    Esempio: se current_week è 25, cerca e cancella "Nome Playlist - Settimana 24".
    """
    # Calcola la settimana e l'anno precedenti
    previous_week_date = datetime.now() - timedelta(weeks=1)
    previous_week_year, previous_week_num, _ = previous_week_date.isocalendar()

    # Costruisce il nome esatto della playlist da cercare e cancellare
    playlist_to_delete_name = f"{base_playlist_name} - Settimana {previous_week_num}"

    logging.info(f"Cerco la playlist della settimana precedente da eliminare: '{playlist_to_delete_name}'")

    try:
        # Cerca la playlist per titolo esatto
        old_playlist = plex.playlist(playlist_to_delete_name)
        logging.warning(f"Trovata vecchia playlist AI: '{old_playlist.title}'. Eliminazione in corso...")
        old_playlist.delete()
        logging.info(f"Vecchia playlist AI '{old_playlist.title}' eliminata con successo.")
    except NotFound:
        # È normale non trovarla, specialmente la prima volta che lo script gira
        logging.info(f"Nessuna playlist della settimana precedente ('{playlist_to_delete_name}') trovata. Nessuna azione richiesta.")
    except Exception as e:
        logging.error(f"Errore durante l'eliminazione della vecchia playlist AI '{playlist_to_delete_name}': {e}")