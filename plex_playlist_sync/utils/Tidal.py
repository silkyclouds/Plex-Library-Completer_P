import logging
from typing import List, Dict
import tidalapi
import unicodedata

class TidalLinkFinder:
    def __init__(self, username: str, password: str):
        """
        Initialize a Tidal session for track/album lookup.
        """
        self.session = tidalapi.Session()
        try:
            self.session.login(username, password)
            logging.info("Authenticated to Tidal successfully.")
        except Exception as e:
            logging.error(f"Failed to authenticate to Tidal: {e}")
            raise

    @staticmethod
    def _clean_string(s: str) -> str:
        """
        Remove invisible unicode characters (category Cf) and trim spaces.
        """
        if not s:
            return ""
        cleaned = ''.join(ch for ch in s if unicodedata.category(ch) != 'Cf').strip()
        return cleaned

    def find_album_by_track(self, title: str, artist: str) -> Dict | None:
        """
        Given a title and artist, search Tidal and return the first matching album.
        Returns dict with 'album_id' and 'album_name', or None if not found.
        """
        title_c = self._clean_string(title)
        artist_c = self._clean_string(artist)
        try:
            # Search tracks
            results = self.session.search('tracks', f"{title_c} {artist_c}")
            if not results or not results.tracks:
                return None
            track = results.tracks[0]
            album = track.album
            return {'album_id': album.id, 'album_name': album.name}
        except Exception as e:
            logging.warning(f"Tidal search failed for '{title} - {artist}': {e}")
            return None

    def get_artist_albums(self, artist_name: str) -> List[Dict]:
        """
        Retrieve all albums for a given artist name.
        Returns list of dicts {'id', 'name'}.
        """
        name_c = self._clean_string(artist_name)
        try:
            artists = self.session.search('artists', name_c).artists
            if not artists:
                return []
            artist = artists[0]
            albums = artist.albums()
            return [{'id': alb.id, 'name': alb.name} for alb in albums]
        except Exception as e:
            logging.error(f"Failed to fetch albums for artist '{artist_name}': {e}")
            return []

    def find_track_link(self, track_info: Dict) -> str | None:
        """
        Find streaming URL for a specific track in Tidal, if available.
        Returns track URL or None.
        """
        track = self.find_album_by_track(track_info.get('title', ''), track_info.get('artist', ''))
        if not track:
            return None
        try:
            # Construct streaming link
            return f"https://listen.tidal.com/album/{track['album_id']}"
        except Exception:
            return None

    def find_potential_tracks(self, title: str, artist: str) -> List[Dict]:
        """
        Search for potential track matches (up to 10) for manual review.
        Returns list of tracks with metadata.
        """
        title_c = self._clean_string(title)
        artist_c = self._clean_string(artist)
        try:
            results = self.session.search('tracks', f"{title_c} {artist_c}")
            potentials = []
            for t in results.tracks[:10]:
                potentials.append({
                    'title': t.name,
                    'artist': t.artist.name,
                    'album': t.album.name,
                    'url': f"https://listen.tidal.com/track/{t.id}"
                })
            logging.info(f"Found {len(potentials)} potential matches for '{title} - {artist}' on Tidal.")
            return potentials
        except Exception as e:
            logging.error(f"Error during manual search for '{title} - {artist}' on Tidal: {e}")
            return []
