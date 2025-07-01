import logging
from typing import List
import requests
import os
from plexapi.server import PlexServer
from .helperClasses import Playlist, Track, UserInputs
from .plex import update_or_create_plex_playlist

DEEZER_API_URL = "https://api.deezer.com"


def _get_all_tracks_from_playlist(tracklist_url: str) -> List[Track]:
    """
    Retrieve ALL tracks from a Deezer playlist URL, handling pagination.
    """
    all_tracks: List[Track] = []
    url = tracklist_url

    while url:
        try:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()

            for track_data in data.get('data', []):
                track = Track(
                    title=track_data.get('title', ''),
                    artist=track_data.get('artist', {}).get('name', ''),
                    album=track_data.get('album', {}).get('title', ''),
                    url=track_data.get('link', '')
                )
                all_tracks.append(track)

            # Move to next page if available
            url = data.get('next')
            if url:
                logging.debug(f"Deezer pagination: moving to {url}")

        except requests.exceptions.RequestException as e:
            logging.error(f"Network error fetching Deezer playlist at {url}: {e}")
            break
        except Exception as e:
            logging.error(f"Unexpected error parsing Deezer tracks: {e}")
            break

    return all_tracks


def deezer_playlist_sync(plex: PlexServer, user_inputs: UserInputs) -> None:
    """
    Create or update Plex playlists based on Deezer playlists using the public API.
    """
    playlist_ids_str = user_inputs.deezer_playlist_ids
    if not playlist_ids_str:
        logging.info("No Deezer playlist IDs configured; skipping Deezer sync.")
        return

    playlist_ids = [pid.strip() for pid in playlist_ids_str.split(',') if pid.strip()]
    suffix = " - Deezer" if user_inputs.append_service_suffix else ""
    limit = int(os.getenv("TEST_MODE_PLAYLIST_LIMIT", "0"))

    for idx, playlist_id in enumerate(playlist_ids):
        if limit > 0 and idx >= limit:
            logging.warning(f"TEST MODE: reached limit of {limit} Deezer playlists; stopping.")
            break

        logging.info(f"Syncing Deezer playlist ID: {playlist_id}")
        playlist_url = f"{DEEZER_API_URL}/playlist/{playlist_id}"
        try:
            response = requests.get(playlist_url)
            response.raise_for_status()
            playlist_data = response.json()

            if 'error' in playlist_data:
                message = playlist_data['error'].get('message', 'Unknown error')
                logging.error(f"Deezer API error for playlist {playlist_id}: {message}")
                continue

            playlist_obj = Playlist(
                id=playlist_data['id'],
                name=playlist_data['title'] + suffix,
                description=playlist_data.get('description', ''),
                poster=playlist_data.get('picture_big', '')
            )

            tracks = _get_all_tracks_from_playlist(playlist_data.get('tracklist', ''))
            if tracks:
                logging.info(f"Found {len(tracks)} tracks in playlist '{playlist_obj.name}'")
                update_or_create_plex_playlist(plex, playlist_obj, tracks, user_inputs)
            else:
                logging.warning(f"No tracks found for Deezer playlist '{playlist_obj.name}'")

        except requests.exceptions.RequestException as e:
            logging.error(f"Network error retrieving Deezer playlist {playlist_id}: {e}")
        except Exception as e:
            logging.error(f"Unexpected error during Deezer sync for playlist {playlist_id}: {e}")
