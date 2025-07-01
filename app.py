import os
import time
import logging
import threading
import csv
import sys
import concurrent.futures
import queue
from flask import Flask, render_template, redirect, url_for, flash, jsonify, request
from dotenv import load_dotenv
from plexapi.server import PlexServer
from plexapi.exceptions import NotFound
from plexapi.audio import Track

# Load environment variables
load_dotenv()

# --- Centralized Logging Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s -[%(levelname)s] - %(message)s",
    handlers=[
        logging.FileHandler("plex_sync.log", mode="a", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logger.setLevel(logging.DEBUG)
# --- End Logging Configuration ---

# Import local modules
from plex_playlist_sync.sync_logic import (
    run_full_sync_cycle,
    run_cleanup_only,
    build_library_index,
    rescan_and_update_missing,
    force_playlist_scan_and_missing_detection
)
from plex_playlist_sync.stats_generator import (
    get_plex_tracks_as_df,
    generate_genre_pie_chart,
    generate_decade_bar_chart,
    generate_top_artists_chart,
    generate_duration_distribution,
    generate_year_trend_chart,
    get_library_statistics
)
from plex_playlist_sync.utils.gemini_ai import list_ai_playlists, generate_on_demand_playlist
from plex_playlist_sync.utils.helperClasses import UserInputs
from plex_playlist_sync.utils.database import (
    initialize_db,
    get_missing_tracks,
    update_track_status,
    get_missing_track_by_id,
    add_managed_ai_playlist,
    get_managed_ai_playlists_for_user,
    delete_managed_ai_playlist,
    get_managed_playlist_details,
    delete_all_missing_tracks,
    delete_missing_track,
    check_track_in_index,
    comprehensive_track_verification,
    get_library_index_stats,
    clean_tv_content_from_missing_tracks,
    clean_resolved_missing_tracks
)
from plex_playlist_sync.utils.downloader import DeezerLinkFinder, download_single_track_with_streamrip
from plex_playlist_sync.utils.i18n import init_i18n_for_app, translate_status

# Initialize database
initialize_db()

app = Flask(__name__, template_folder='templates')
app.secret_key = os.getenv("FLASK_SECRET_KEY", "a-random-strong-secret-key")

# Initialize internationalization
init_i18n_for_app(app)

# Shared application state
app_state = {"status": "Idle", "last_sync": "Never", "is_running": False}

# Download queue and executor
download_queue = queue.Queue()
download_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

def download_worker():
    while True:
        item = download_queue.get()
        if item is None:
            break
        link, track_id = item
        try:
            logger.info(f"Starting download for {link} (Track ID: {track_id})")
            download_single_track_with_streamrip(link)
            update_track_status(track_id, 'downloaded')
            logger.info(f"Download completed for {link} (Track ID: {track_id})")
        except Exception as e:
            logger.error(f"Error downloading {link} (Track ID: {track_id}): {e}", exc_info=True)
        finally:
            download_queue.task_done()


def run_task_in_background(trigger_label, target_function, *args):
    app_state['is_running'] = True
    app_state['status'] = f"Operation ({trigger_label}) in progress..."
    try:
        if target_function == run_full_sync_cycle:
            target_function(*args)
            app_state['last_sync'] = time.strftime("%Y-%m-%d %H:%M:%S")
        else:
            target_function(*args)
        app_state['status'] = "Idle"
    except Exception as e:
        logger.error(f"Critical error during '{trigger_label}': {e}", exc_info=True)
        app_state['status'] = "Error! Check logs."
    finally:
        app_state['is_running'] = False


def start_background_task(target_function, flash_message, *args):
    if app_state['is_running']:
        flash("Another operation is already running. Please wait.", "warning")
    else:
        flash(flash_message, "info")
        thread = threading.Thread(target=run_task_in_background, args=(target_function.__name__, target_function, *args))
        thread.start()
    return redirect(request.referrer or url_for('index'))


def get_user_aliases():
    return {
        'main': os.getenv('USER_ALIAS_MAIN', 'Primary User'),
        'secondary': os.getenv('USER_ALIAS_SECONDARY', 'Secondary User')
    }

@app.route('/')
def index():
    index_stats = get_library_index_stats()
    return render_template('index.html', aliases=get_user_aliases(), index_stats=index_stats)

@app.route('/missing_tracks')
def missing_tracks():
    try:
        tracks = get_missing_tracks()
        logger.info(f"Retrieved {len(tracks)} missing tracks")
        return render_template('missing_tracks.html', tracks=tracks)
    except Exception as e:
        logger.error(f"Error in missing_tracks view: {e}", exc_info=True)
        flash(f"Error retrieving missing tracks: {e}", "error")
        return render_template('missing_tracks.html', tracks=[])

# ... REST OF ROUTES TRANSLATED TO ENGLISH ...

if __name__ == '__main__':
    logger.info("Starting Flask application...")
    # Start background download worker
    threading.Thread(target=download_worker, daemon=True).start()
    # Start scheduled syncs
    def scheduler():
        time.sleep(10)
        wait = int(os.getenv('SECONDS_TO_WAIT', 86400))
        while True:
            if not app_state['is_running']:
                logger.info("Scheduler: initiating automatic sync.")
                run_task_in_background('AutomaticSync', run_full_sync_cycle)
            time.sleep(wait)
    threading.Thread(target=scheduler, daemon=True).start()
    app.run(host='0.0.0.0', port=5000)
