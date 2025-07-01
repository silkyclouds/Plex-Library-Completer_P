import os
import logging
import subprocess
import time
import unicodedata
from typing import Dict, Optional, List

from deezer import DeezerLinkFinder
from tidal import TidalLinkFinder
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

# Configuration from environment variables
TEMP_DIR = os.environ.get('TEMP_DOWNLOAD_DIR', '/app/state')
STREAMRIP_CONFIG = os.environ.get('STREAMRIP_CONFIG_PATH', '/root/.config/streamrip/config.toml')

# Service credentials
download_order = [s.strip().lower() for s in os.environ.get('DOWNLOAD_ORDER', 'tidal,deezer').split(',')]
TIDAL_USERNAME = os.environ.get('TIDAL_USERNAME', '')
TIDAL_PASSWORD = os.environ.get('TIDAL_PASSWORD', '')
SPOTIFY_CLIENT_ID = os.environ.get('SPOTIFY_CLIENT_ID', '')
SPOTIFY_CLIENT_SECRET = os.environ.get('SPOTIFY_CLIENT_SECRET', '')

# Initialize Spotify client if configured
spotify_client: Optional[spotipy.Spotify] = None
if 'spotify' in download_order and SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET:
    creds = SpotifyClientCredentials(client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET)
    spotify_client = spotipy.Spotify(auth_manager=creds)


def clean_url(url: str) -> str:
    """
    Remove invisible Unicode characters (category Cf) and trim whitespace.
    Prevents corrupted URLs causing download errors.
    """
    if not url:
        return ''
    cleaned = ''.join(ch for ch in url if unicodedata.category(ch) != 'Cf').strip()
    if cleaned != url:
        logging.info(f"Cleaned URL: '{url}' -> '{cleaned}'")
    return cleaned


def download_with_streamrip(link: str) -> None:
    """
    Invoke streamrip to download a single URL with timeout and cleanup.
    """
    if not link:
        logging.info('No link provided for download.')
        return
    cleaned_link = clean_url(link)
    if not cleaned_link:
        logging.error('Cleaned URL is empty, aborting download.')
        return

    # Ensure temporary directory exists
    try:
        os.makedirs(TEMP_DIR, exist_ok=True)
    except Exception as e:
        logging.error(f'Failed to create temp directory {TEMP_DIR}: {e}')
        temp_dir_local = '.'
    else:
        temp_dir_local = TEMP_DIR

    links_file = os.path.join(temp_dir_local, f'temp_links_{int(time.time())}.txt')
    try:
        with open(links_file, 'w', encoding='utf-8') as f:
            f.write(cleaned_link + '\n')

        logging.info(f'Starting streamrip download for: {cleaned_link}')
        command = ['rip', '--config-path', STREAMRIP_CONFIG, 'file', links_file]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            timeout=1800
        )
        logging.info(f'Download completed: {cleaned_link}')
        if result.stdout:
            logging.debug(f'Streamrip stdout:\n{result.stdout}')
        if result.stderr:
            logging.warning(f'Streamrip stderr:\n{result.stderr}')
    except subprocess.CalledProcessError as e:
        logging.error(f'Streamrip failed for {cleaned_link}: {e}')
        if e.stdout:
            logging.error(f'Stdout:\n{e.stdout}')
        if e.stderr:
            logging.error(f'Stderr:\n{e.stderr}')
    except Exception as e:
        logging.error(f'Unexpected error during streamrip download: {e}')
    finally:
        if os.path.exists(links_file):
            try:
                os.remove(links_file)
            except Exception as e:
                logging.warning(f'Failed to remove temp file {links_file}: {e}')


def find_and_download_track(track_info: Dict) -> None:
    """
    Find and download a track by querying services in the configured order.
    Supports 'spotify', 'tidal', 'deezer'.
    """
    title = track_info.get('title', '')
    artist = track_info.get('artist', '')
    if not title or not artist:
        logging.error('Track info missing title or artist.')
        return

    link: Optional[str] = None
    for service in download_order:
        service = service.lower()
        if service == 'spotify' and spotify_client:
            try:
                results = spotify_client.search(q=f'track:{title} artist:{artist}', type='track', limit=1)
                items = results.get('tracks', {}).get('items', [])
                if items:
                    link = items[0]['external_urls']['spotify']
                    logging.info(f'Found Spotify link for {title} - {artist}')
                    break
            except Exception as e:
                logging.warning(f'Spotify lookup failed for {title} - {artist}: {e}')

        elif service == 'tidal' and TIDAL_USERNAME and TIDAL_PASSWORD:
            try:
                tidal_finder = TidalLinkFinder(TIDAL_USERNAME, TIDAL_PASSWORD)
                link = tidal_finder.find_track_link({'title': title, 'artist': artist})
                if link:
                    logging.info(f'Found Tidal link for {title} - {artist}')
                    break
            except Exception as e:
                logging.warning(f'Tidal lookup failed for {title} - {artist}: {e}')

        elif service == 'deezer':
            deezer_link = DeezerLinkFinder.find_track_link({'title': title, 'artist': artist})
            if deezer_link:
                link = deezer_link
                logging.info(f'Found Deezer link for {title} - {artist}')
                break

        else:
            logging.debug(f'Service {service} is not configured or unsupported.')

    if not link:
        logging.error(f'No streaming link found for {title} - {artist}')
        return

    download_with_streamrip(link)


if __name__ == '__main__':
    # Batch processing: read tracks from CSV file and download each
    import csv
    input_csv = os.environ.get('TRACKS_CSV', 'tracks_to_download.csv')
    try:
        with open(input_csv, newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                find_and_download_track(row)
    except FileNotFoundError:
        logging.error(f'Tracks CSV file not found: {input_csv}')
    except Exception as e:
        logging.error(f'Error reading CSV file {input_csv}: {e}')
