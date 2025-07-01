import os
import logging
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from plexapi.server import PlexServer
import time
import random
from collections import Counter
import re
from datetime import datetime
from .utils.i18n import get_i18n

# Sample size for very large libraries
SAMPLE_SIZE = 5000
CACHE_DIR = "./state_data"
CACHE_DURATION = 86400  # seconds

# Modern color palette (inspired by Spotify)
SPOTIFY_COLORS = [
    '#1DB954', '#1ed760', '#1fdf64', '#FF6B6B', '#4ECDC4',
    '#FFE66D', '#A8E6CF', '#FF8E53', '#6C5CE7', '#FD79A8',
    '#00B894', '#FDCB6E', '#E17055', '#74B9FF', '#A29BFE'
]

# Genre normalization mapping
GENRE_MAPPING = {
    'rock': 'Rock',
    'classic rock': 'Classic Rock',
    'alternative rock': 'Alternative Rock',
    'hard rock': 'Hard Rock',
    'indie rock': 'Indie Rock',
    'punk rock': 'Punk Rock',
    'progressive rock': 'Progressive Rock',
    'folk rock': 'Folk Rock',
    'pop rock': 'Pop Rock',
    'pop': 'Pop',
    'synth-pop': 'Synth-Pop',
    'electronic': 'Electronic',
    'dance': 'Dance',
    'house': 'House',
    'techno': 'Techno',
    'ambient': 'Ambient',
    'edm': 'EDM',
    'trance': 'Trance',
    'dubstep': 'Dubstep',
    'hip hop': 'Hip-Hop',
    'rap': 'Rap',
    'jazz': 'Jazz',
    'blues': 'Blues',
    'metal': 'Metal',
    'classical': 'Classical',
    'country': 'Country',
    'folk': 'Folk',
    'latin': 'Latin',
    'reggae': 'Reggae',
    'ska': 'Ska',
    'r&b': 'R&B',
    'soul': 'Soul',
    'disco': 'Disco',
    'funk': 'Funk'
}


def normalize_genre(genre_str: str, language: str = 'en') -> str:
    """
    Normalize genre strings with optional language support.
    """
    unknown = "Unknown"
    if not genre_str:
        return unknown
    key = genre_str.lower().strip()
    if key in GENRE_MAPPING:
        return GENRE_MAPPING[key]
    for k, v in GENRE_MAPPING.items():
        if k in key or key in k:
            return v
    return genre_str.title()


def _extract_year(track) -> int | None:
    """
    Extract a reliable release year from a Plex track.
    """
    if getattr(track, 'originallyAvailableAt', None):
        return track.originallyAvailableAt.year
    if getattr(track, 'parentYear', None):
        return track.parentYear
    if getattr(track, 'year', None):
        return track.year
    try:
        album = track.album()
        if getattr(album, 'year', None):
            return album.year
        if getattr(album, 'originallyAvailableAt', None):
            return album.originallyAvailableAt.year
    except Exception:
        pass
    if getattr(track, 'addedAt', None):
        return track.addedAt.year
    return None


def _extract_genre(track, language: str = 'en') -> str:
    """
    Extract the first available genre or mood tag.
    """
    try:
        album = track.album()
        if getattr(album, 'genres', None):
            return normalize_genre(album.genres[0].tag, language)
    except Exception:
        pass
    if getattr(track, 'genres', None):
        return normalize_genre(track.genres[0].tag, language)
    if getattr(track, 'moods', None):
        return normalize_genre(track.moods[0].tag, language)
    return "Unknown"


def _extract_additional_metadata(track) -> dict:
    """
    Extract extra metadata: duration, rating, bitrate, artist, album, title, play count, added year.
    """
    data = {}
    data['duration_minutes'] = round(track.duration / 60000, 2) if getattr(track, 'duration', None) else None
    data['rating'] = getattr(track, 'userRating', None) or getattr(track, 'rating', None)
    data['bitrate'] = getattr(track, 'bitrate', None)
    data['artist'] = getattr(track, 'grandparentTitle', 'Unknown')
    data['album'] = getattr(track, 'parentTitle', 'Unknown')
    data['title'] = getattr(track, 'title', 'Unknown')
    data['play_count'] = getattr(track, 'viewCount', 0) or 0
    data['added_year'] = track.addedAt.year if getattr(track, 'addedAt', None) else None
    return data


def _get_cache_path(suffix: str) -> str:
    return os.path.join(CACHE_DIR, f"stats_cache_{suffix}.pkl")


def get_plex_tracks_as_df(
    plex: PlexServer,
    playlist_id: str | None,
    force_refresh: bool = False,
    language: str = 'en'
) -> pd.DataFrame:
    """
    Fetch tracks and return a DataFrame with extended metadata.
    """
    if playlist_id:
        playlist = plex.fetchItem(int(playlist_id))
        target = playlist
    else:
        target = plex.library.section('Music')  # section name configurable

    cache_key = playlist_id or 'library'
    cache_path = _get_cache_path(cache_key)

    if not force_refresh and os.path.exists(cache_path):
        age = time.time() - os.path.getmtime(cache_path)
        if age < CACHE_DURATION:
            logging.info(f"Loading cached stats: {cache_path}")
            return pd.read_pickle(cache_path)

    # Retrieve tracks
    if hasattr(target, 'items'):
        tracks = target.items()
    else:
        tracks = target.search(libtype='track')
    total = len(tracks)
    if not playlist_id and total > SAMPLE_SIZE:
        tracks = random.sample(list(tracks), SAMPLE_SIZE)

    data = []
    for tr in tracks:
        try:
            year = _extract_year(tr)
            genre = _extract_genre(tr, language)
            meta = _extract_additional_metadata(tr)
            row = {'year': year, 'genre': genre, **meta}
            data.append(row)
        except Exception as e:
            logging.warning(f"Error processing track: {e}")

    df = pd.DataFrame(data)
    df = df.dropna(subset=['genre'])
    df['year'] = df['year'].fillna(0).astype(int)
    df = df[(df['year'] == 0) | ((df['year'] >= 1900) & (df['year'] <= datetime.now().year + 1))]

    os.makedirs(CACHE_DIR, exist_ok=True)
    df.to_pickle(cache_path)
    logging.info(f"Cached stats saved to {cache_path}")
    return df


def generate_genre_pie_chart(df: pd.DataFrame, language: str = 'en') -> str:
    logging.info("Generating genre pie chart...")
    if df.empty or 'genre' not in df.columns:
        return "<div>No genre data available.</div>"
    counts = df['genre'].value_counts().nlargest(12).reset_index()
    counts.columns = ['genre', 'count']
    total = counts['count'].sum()
    other = len(df) - total
    if other > 0:
        counts = counts.append({'genre': 'Other', 'count': other}, ignore_index=True)

    fig = px.pie(
        counts,
        values='count',
        names='genre',
        title=get_chart_title('genre_distribution', len(df), language),
        color_discrete_sequence=SPOTIFY_COLORS
    )
    fig.update_traces(textinfo='percent+label')
    return fig.to_html(full_html=False, include_plotlyjs='cdn')


def generate_decade_bar_chart(df: pd.DataFrame, language: str = 'en') -> str:
    logging.info("Generating decade bar chart...")
    if df.empty or 'year' not in df.columns:
        return "<div>No year data available.</div>"
    df2 = df[df['year'] > 0].copy()
    df2['decade'] = df2['year'] // 10 * 10
    counts = df2['decade'].value_counts().sort_index().reset_index()
    counts.columns = ['decade', 'count']
    counts['decade'] = counts['decade'].astype(int).astype(str) + 's'
    fig = px.bar(
        counts,
        x='decade',
        y='count',
        title=get_chart_title('decade_distribution', len(df2), language)
    )
    return fig.to_html(full_html=False, include_plotlyjs='cdn')


def generate_top_artists_chart(df: pd.DataFrame, top_n: int = 15, language: str = 'en') -> str:
    logging.info("Generating top artists chart...")
    if df.empty or 'artist' not in df.columns:
        return "<div>No artist data available.</div>"
    df2 = df[df['artist'].str.lower() != 'various artists']
    counts = df2['artist'].value_counts().nlargest(top_n).reset_index()
    counts.columns = ['artist', 'count']
    fig = px.bar(
        counts,
        x='count',
        y='artist',
        orientation='h',
        title=get_chart_title('top_artists', top_n, language)
    )
    return fig.to_html(full_html=False, include_plotlyjs='cdn')


def generate_duration_distribution(df: pd.DataFrame, language: str = 'en') -> str:
    logging.info("Generating duration distribution histogram...")
    if df.empty or 'duration_minutes' not in df.columns:
        return "<div>No duration data available.</div>"
    df2 = df.dropna(subset=['duration_minutes'])
    fig = px.histogram(
        df2,
        x='duration_minutes',
        nbins=30,
        title=get_chart_title('duration_distribution', None, language)
    )
    return fig.to_html(full_html=False, include_plotlyjs='cdn')


def generate_year_trend_chart(df: pd.DataFrame, language: str = 'en') -> str:
    logging.info("Generating year trend chart...")
    if df.empty or 'year' not in df.columns:
        return "<div>No year data available.</div>"
    df2 = df[df['year'] > 0].copy()
    counts = df2['year'].value_counts().sort_index().reset_index()
    counts.columns = ['year', 'count']
    fig = px.line(
        counts,
        x='year',
        y='count',
        title=get_chart_title('year_trend', None, language)
    )
    return fig.to_html(full_html=False, include_plotlyjs='cdn')


def get_library_statistics(df: pd.DataFrame) -> dict:
    stats = {}
    stats['total_tracks'] = len(df)
    stats['unique_artists'] = df['artist'].nunique() if 'artist' in df.columns else 0
    stats['unique_albums'] = df['album'].nunique() if 'album' in df.columns else 0
    stats['unique_genres'] = df['genre'].nunique() if 'genre' in df.columns else 0
    if 'year' in df.columns:
        years = df[df['year'] > 0]['year']
        stats['oldest_track'] = int(years.min()) if not years.empty else None
        stats['newest_track'] = int(years.max()) if not years.empty else None
    return stats


def get_chart_title(chart_type: str, count_or_value: int | None, language: str = 'en') -> str:
    titles = {
        'genre_distribution': f'Musical Genre Distribution ({count_or_value:,} tracks)' if count_or_value else 'Musical Genre Distribution',
        'decade_distribution': f'Track Distribution by Decade ({count_or_value:,} tracks)' if count_or_value else 'Track Distribution by Decade',
        'top_artists': f'Top {count_or_value} Artists by Track Count' if count_or_value else 'Top Artists by Track Count',
        'duration_distribution': 'Track Duration Distribution',
        'year_trend': 'Track Trend by Year'
    }
    return titles.get(chart_type, chart_type)


def get_axis_title(axis_type: str, language: str = 'en') -> str:
    axes = {
        'decade': 'Decade',
        'track_count': 'Number of Tracks',
        'duration_minutes': 'Duration (minutes)',
        'artist': 'Artist',
        'year': 'Year'
    }
    return axes.get(axis_type, axis_type)


def get_hover_template(chart_type: str, language: str = 'en') -> str:
    templates = {
        'genre': '<b>%{label}</b><br>Tracks: %{value:,}<br>Percentage: %{percent}<extra></extra>',
        'top_artists': '<b>%{y}</b><br>Tracks: %{x:,}<extra></extra>',
        'year_trend': '<b>Year %{x}</b><br>Tracks: %{y:,}<extra></extra>'
    }
    return templates.get(chart_type, '%{label}: %{value}<extra></extra>')
