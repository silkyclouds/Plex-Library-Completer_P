#!/usr/bin/env python3
"""Forza la creazione del database sync nel path corretto"""

import os
import sys
import sqlite3

# Aggiungi il path del progetto
sys.path.append('.')

from plex_playlist_sync.utils.database import initialize_db, DB_PATH, get_library_index_stats

def force_create_database():
    print("=== FORZATURA CREAZIONE DATABASE ===")
    print(f"🎯 Target path: {DB_PATH}")
    
    # Verifica directory
    db_dir = os.path.dirname(DB_PATH)
    print(f"📁 Directory: {db_dir}")
    
    if not os.path.exists(db_dir):
        print(f"❌ Directory non esiste, creo: {db_dir}")
        os.makedirs(db_dir, exist_ok=True)
    else:
        print(f"✅ Directory esiste: {db_dir}")
    
    # Forza inizializzazione
    print("🔧 Inizializzo database...")
    try:
        initialize_db()
        print("✅ Inizializzazione completata")
        
        # Verifica esistenza
        if os.path.exists(DB_PATH):
            size = os.path.getsize(DB_PATH)
            print(f"✅ Database creato: {DB_PATH} ({size} bytes)")
            
            # Test connessione
            with sqlite3.connect(DB_PATH) as con:
                cur = con.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [row[0] for row in cur.fetchall()]
                print(f"📋 Tabelle create: {tables}")
                
                # Test inserimento traccia fake
                print("🧪 Test inserimento traccia...")
                cur.execute("""
                    INSERT OR IGNORE INTO plex_library_index (title_clean, artist_clean, album_clean)
                    VALUES (?, ?, ?)
                """, ("test_track", "test_artist", "test_album"))
                con.commit()
                
                # Verifica inserimento
                cur.execute("SELECT COUNT(*) FROM plex_library_index")
                count = cur.fetchone()[0]
                print(f"🎵 Tracce dopo test: {count}")
                
        else:
            print(f"❌ Database non creato: {DB_PATH}")
            
    except Exception as e:
        print(f"❌ Errore: {e}")
        import traceback
        traceback.print_exc()
    
    # Verifica con la funzione originale
    print("\n=== TEST FUNZIONE ORIGINALE ===")
    try:
        stats = get_library_index_stats()
        print(f"📊 Stats originali: {stats}")
    except Exception as e:
        print(f"❌ Errore stats: {e}")

if __name__ == "__main__":
    force_create_database()