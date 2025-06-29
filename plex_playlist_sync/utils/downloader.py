import os
import csv
import logging
import requests
import subprocess
from typing import List, Dict
import time
import unicodedata

def clean_url(url: str) -> str:
    """
    Rimuove caratteri invisibili come zero-width space dagli URL.
    Questo risolve problemi con URL corrotti che causano errori di download.
    """
    if not url:
        return ""
    
    # Rimuove caratteri di controllo Unicode (categoria Cf) come zero-width space
    cleaned = ''.join(char for char in url if unicodedata.category(char) != 'Cf')
    
    # Rimuove spazi extra all'inizio e alla fine
    cleaned = cleaned.strip()
    
    # Log solo se è stato effettivamente pulito qualcosa
    if cleaned != url:
        logging.info(f"URL pulito: '{url}' -> '{cleaned}'")
    
    return cleaned

class DeezerLinkFinder:
    @staticmethod
    def find_track_link(track_info: dict) -> str | None:
        """
        Cerca una singola traccia su Deezer e restituisce il link dell'album.
        Questa funzione è usata dal downloader automatico.
        """
        try:
            title = track_info.get("title", "").strip()
            artist = track_info.get("artist", "").strip()

            if not title or not artist:
                return None

            search_url = f'https://api.deezer.com/search?q=track:"{title}" artist:"{artist}"&limit=1'
            response = requests.get(search_url)
            response.raise_for_status()
            deezer_data = response.json()

            if deezer_data.get("data"):
                album_id = deezer_data["data"][0].get("album", {}).get("id")
                if album_id:
                    album_link = f'https://www.deezer.com/album/{album_id}'
                    # Non logghiamo qui per non intasare i log durante i cicli automatici
                    return album_link
            return None
        except Exception:
            # Silenziamo gli errori qui perché è un tentativo "best-effort"
            return None

    @staticmethod
    def find_potential_tracks(title: str, artist: str) -> List[Dict]:
        """
        Cerca su Deezer e restituisce una lista di potenziali tracce per la ricerca manuale.
        """
        try:
            search_url = f'https://api.deezer.com/search?q=track:"{title}" artist:"{artist}"&limit=10'
            response = requests.get(search_url)
            response.raise_for_status()
            deezer_data = response.json()
            logging.info(f"Ricerca manuale per '{title} - {artist}' ha restituito {len(deezer_data.get('data', []))} risultati.")
            return deezer_data.get("data", [])
        except Exception as e:
            logging.error(f"Errore durante la ricerca manuale su Deezer per '{title} - {artist}': {e}")
            return []

def download_single_track_with_streamrip(link: str):
    """
    Lancia streamrip per scaricare un singolo URL.
    """
    if not link:
        logging.info("Nessun link da scaricare fornito.")
        return

    # Pulisci l'URL da caratteri invisibili prima del download
    cleaned_link = clean_url(link)
    if not cleaned_link:
        logging.error("URL vuoto dopo la pulizia, download annullato.")
        return

    # Assicura che la directory temp esista
    temp_dir = "/app/state"
    if not os.path.exists(temp_dir):
        try:
            os.makedirs(temp_dir, exist_ok=True)
            logging.info(f"📁 Creata directory temporanea: {temp_dir}")
        except Exception as e:
            logging.error(f"❌ Impossibile creare directory {temp_dir}: {e}")
            # Fallback su directory corrente
            temp_dir = "."
    
    temp_links_file = f"{temp_dir}/temp_download_{int(time.time())}.txt"
    try:
        with open(temp_links_file, "w", encoding="utf-8") as f:
            f.write(f"{cleaned_link}\n")
        
        logging.info(f"Avvio del download con streamrip per il link: {cleaned_link}")
        config_path = "/root/.config/streamrip/config.toml"
        command = ["rip", "--config-path", config_path, "file", temp_links_file]
        
        # Aggiungiamo un timeout per evitare che il processo si blocchi all'infinito
        process = subprocess.run(command, capture_output=True, text=True, check=True, encoding='utf-8', timeout=1800)
        logging.info(f"Download di {cleaned_link} completato con successo.")
        if process.stdout:
             logging.debug(f"Output di streamrip per {cleaned_link}:\n{process.stdout}")
        if process.stderr:
             logging.warning(f"Output di warning da streamrip per {cleaned_link}:\n{process.stderr}")

    except subprocess.CalledProcessError as e:
        logging.error(f"Errore durante l'esecuzione di streamrip per {cleaned_link}.")
        if e.stdout: logging.error(f"Output Standard (stdout):\n{e.stdout}")
        if e.stderr: logging.error(f"Output di Errore (stderr):\n{e.stderr}")
    except Exception as e:
        logging.error(f"Un errore imprevisto è occorso durante l'avvio di streamrip per {cleaned_link}: {e}")
    finally:
        if os.path.exists(temp_links_file):
            os.remove(temp_links_file)
            logging.info(f"File temporaneo di download rimosso: {temp_links_file}")