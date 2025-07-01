#!/usr/bin/env python3
"""Debug script for inspecting the sync_database.db and verifying environment settings including Tidal credentials and star threshold."""

import os
import sqlite3

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Retrieve Tidal credentials and star threshold for auto-snatch feature
TIDAL_USERNAME = os.getenv('TIDAL_USERNAME', '')
TIDAL_PASSWORD = os.getenv('TIDAL_PASSWORD', '')
STAR_THRESHOLD = os.getenv('STAR_THRESHOLD', None)

# Possible database paths to check
possible_paths = [
    './state_data/sync_database.db',
    '/app/state_data/sync_database.db',
    '/mnt/e/Docker image/Plex-Library-Completer/state_data/sync_database.db'
]

print("=== DEBUG DATABASE SYNC ===")

for db_path in possible_paths:
    print(f"\n🔍 Checking path: {db_path}")
    if os.path.exists(db_path):
        print(f"✅ Database found: {db_path}")
        size = os.path.getsize(db_path)
        print(f"📊 Size: {size} bytes")
        try:
            with sqlite3.connect(db_path) as con:
                cur = con.cursor()
                # List tables
                cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [row[0] for row in cur.fetchall()]
                print(f"📋 Tables found: {tables}")

                # Count indexed tracks
                if 'plex_library_index' in tables:
                    cur.execute("SELECT COUNT(*) FROM plex_library_index")
                    count = cur.fetchone()[0]
                    print(f"🎵 Indexed tracks: {count}")
                    if count > 0:
                        cur.execute("SELECT title_clean, artist_clean FROM plex_library_index LIMIT 5")
                        samples = cur.fetchall()
                        print("🎶 Sample tracks:")
                        for title, artist in samples:
                            print(f"   - '{title}' by '{artist}'")

                # Count missing tracks
                if 'missing_tracks' in tables:
                    cur.execute("SELECT COUNT(*) FROM missing_tracks")
                    missing_count = cur.fetchone()[0]
                    print(f"❌ Missing tracks: {missing_count}")

        except Exception as e:
            print(f"❌ Database error: {e}")
    else:
        print(f"❌ Database not found: {db_path}")

# Print environment variable debug info
print("\n=== ENVIRONMENT SETTINGS ===")
print(f"TIDAL_USERNAME set: {'yes' if TIDAL_USERNAME else 'no'}")
print(f"TIDAL_PASSWORD set: {'yes' if TIDAL_PASSWORD else 'no'}")
print(f"STAR_THRESHOLD: {STAR_THRESHOLD}")

# Verify working directory
print("\n=== PATH VERIFICATION ===")
print(f"Current working directory: {os.getcwd()}")
script_dir = os.path.dirname(__file__)
calculated_path = os.path.join(script_dir, 'state_data', 'sync_database.db')
print(f"Calculated path (as in code): {calculated_path}")
print(f"Exists calculated path? {os.path.exists(calculated_path)}")
