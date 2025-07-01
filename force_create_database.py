#!/usr/bin/env python3
"""Force creation of the sync database at the correct path and verify functionality."""
import os
import sys
import sqlite3

# Ensure project path is included
target_dir = os.path.dirname(__file__)
sys.path.append(target_dir)

from plex_playlist_sync.utils.database import initialize_db, DB_PATH, get_library_index_stats


def force_create_database():
    print("=== FORCE DATABASE CREATION ===")
    print(f"🎯 Target path: {DB_PATH}")

    # Verify directory exists
    db_dir = os.path.dirname(DB_PATH)
    print(f"📁 Directory: {db_dir}")
    if not os.path.exists(db_dir):
        print(f"❌ Directory does not exist, creating: {db_dir}")
        os.makedirs(db_dir, exist_ok=True)
    else:
        print(f"✅ Directory exists: {db_dir}")

    # Initialize database
    print("🔧 Initializing database...")
    try:
        initialize_db()
        print("✅ Initialization complete")

        # Verify file creation
        if os.path.exists(DB_PATH):
            size = os.path.getsize(DB_PATH)
            print(f"✅ Database created: {DB_PATH} ({size} bytes)")

            # Test connection and table creation
            with sqlite3.connect(DB_PATH) as con:
                cur = con.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [row[0] for row in cur.fetchall()]
                print(f"📋 Tables created: {tables}")

                # Insert a test record
                print("🧪 Testing record insertion...")
                cur.execute(
                    """
                    INSERT OR IGNORE INTO plex_library_index (title_clean, artist_clean, album_clean)
                    VALUES (?, ?, ?)
                    """, ("test_track", "test_artist", "test_album")
                )
                con.commit()

                # Verify insertion
                cur.execute("SELECT COUNT(*) FROM plex_library_index")
                count = cur.fetchone()[0]
                print(f"🎵 Track count after test insert: {count}")
        else:
            print(f"❌ Database not created: {DB_PATH}")

    except Exception as e:
        print(f"❌ Error during initialization: {e}")
        import traceback
        traceback.print_exc()

    # Verify original stats function
    print("\n=== VERIFY ORIGINAL FUNCTION ===")
    try:
        stats = get_library_index_stats()
        print(f"📊 Original stats: {stats}")
    except Exception as e:
        print(f"❌ Error retrieving stats: {e}")


if __name__ == "__main__":
    force_create_database()
