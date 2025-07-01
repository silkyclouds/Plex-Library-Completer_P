import sqlite3
import logging
import os
import re
import json
import queue
import threading
import time
from contextlib import contextmanager
from typing import List, Dict, Any, Optional
from plexapi.server import PlexServer
from plexapi.exceptions import NotFound
from plexapi.audio import Track

# Use the 'state_data' folder for persistent storage
db_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
DB_PATH = os.path.join(db_root, "state_data", "sync_database.db")

class DatabasePool:
    """
    Thread-safe SQLite connection pool with performance optimizations.
    """
    def __init__(self, db_path: str, pool_size: int = 10, timeout: int = 30):
        self.db_path = db_path
        self.pool = queue.Queue(maxsize=pool_size)
        self.timeout = timeout
        self.lock = threading.Lock()
        self.connections_created = 0
        logging.info(f"Initializing DB pool: path={db_path}, size={pool_size}")

    def _create_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.db_path,
            timeout=self.timeout,
            check_same_thread=False
        )
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=50000")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA mmap_size=268435456")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.row_factory = sqlite3.Row
        with self.lock:
            self.connections_created += 1
        logging.debug(f"Created DB connection #{self.connections_created}")
        return conn

    def get_connection(self) -> sqlite3.Connection:
        try:
            conn = self.pool.get_nowait()
            logging.debug("Reusing DB connection from pool")
            return conn
        except queue.Empty:
            logging.debug("DB pool empty; creating new connection")
            return self._create_connection()

    def return_connection(self, conn: sqlite3.Connection):
        try:
            conn.execute("SELECT 1").fetchone()
            self.pool.put_nowait(conn)
            logging.debug("Returned DB connection to pool")
        except Exception:
            conn.close()
            logging.debug("Closed invalid DB connection")

    @contextmanager
    def connection(self):
        conn = self.get_connection()
        try:
            yield conn
            conn.commit()
        except:
            conn.rollback()
            raise
        finally:
            self.return_connection(conn)

_db_pool: Optional[DatabasePool] = None

def get_db_pool() -> DatabasePool:
    global _db_pool
    if _db_pool is None:
        _db_pool = DatabasePool(DB_PATH)
    return _db_pool

@contextmanager
def get_db():
    pool = get_db_pool()
    with pool.connection() as conn:
        yield conn

# CRUD and utility functions

def initialize_db():
    """Create or upgrade necessary tables."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    logging.info(f"Initializing database at {DB_PATH}")
    with get_db() as con:
        cur = con.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS missing_tracks (\
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, artist TEXT NOT NULL,\
            album TEXT, source_playlist_title TEXT NOT NULL, source_playlist_id INTEGER,\
            status TEXT NOT NULL DEFAULT 'missing', added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,\
            UNIQUE(title, artist, source_playlist_title))")
        cur.execute("CREATE TABLE IF NOT EXISTS plex_library_index (\
            id INTEGER PRIMARY KEY AUTOINCREMENT, title_clean TEXT NOT NULL, artist_clean TEXT NOT NULL,\
            album_clean TEXT, year INTEGER, added_at TIMESTAMP,\
            UNIQUE(artist_clean, album_clean, title_clean))")
        cur.execute("CREATE TABLE IF NOT EXISTS managed_ai_playlists (\
            id INTEGER PRIMARY KEY AUTOINCREMENT, plex_rating_key INTEGER, title TEXT NOT NULL UNIQUE,\
            description TEXT, user TEXT NOT NULL, tracklist_json TEXT NOT NULL,\
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        # indices
        cur.execute("CREATE INDEX IF NOT EXISTS idx_index_artist_title ON plex_library_index(artist_clean, title_clean)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_missing_status ON missing_tracks(status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ai_user ON managed_ai_playlists(user)")


def add_managed_ai_playlist(info: Dict[str, Any]):
    with get_db() as con:
        cur = con.cursor()
        cur.execute("INSERT INTO managed_ai_playlists (plex_rating_key, title, description, user, tracklist_json) VALUES (?,?,?,?,?)",
                    (info['plex_rating_key'], info['title'], info.get('description',''), info['user'], json.dumps(info['tracklist'])))


def get_managed_ai_playlists_for_user(user: str) -> List[Dict]:
    with get_db() as con:
        cur = con.cursor()
        res = cur.execute("SELECT id, title, description, tracklist_json, created_at FROM managed_ai_playlists WHERE user=? ORDER BY created_at DESC",(user,))
        rows = []
        for r in res.fetchall():
            d = dict(r)
            d['item_count'] = len(json.loads(d['tracklist_json'])) if d['tracklist_json'] else 0
            rows.append(d)
        return rows


def delete_managed_ai_playlist(pid: int):
    with get_db() as con:
        con.cursor().execute("DELETE FROM managed_ai_playlists WHERE id=?",(pid,))


def get_managed_playlist_details(pid: int) -> Optional[Dict]:
    with get_db() as con:
        cur = con.cursor()
        r = cur.execute("SELECT * FROM managed_ai_playlists WHERE id=?",(pid,)).fetchone()
        return dict(r) if r else None


def add_missing_track(info: Dict[str, Any]):
    with get_db() as con:
        con.cursor().execute("INSERT OR IGNORE INTO missing_tracks(title,artist,album,source_playlist_title,source_playlist_id) VALUES (?,?,?,?,?)",
                               (info['title'],info['artist'],info.get('album'),info['source_playlist_title'],info['source_playlist_id']))


def delete_missing_track(mid: int):
    with get_db() as con:
        con.cursor().execute("DELETE FROM missing_tracks WHERE id=?",(mid,))


def get_missing_tracks() -> List[tuple]:
    with get_db() as con:
        return con.cursor().execute("SELECT * FROM missing_tracks WHERE status='missing' OR status IS NULL").fetchall()


def delete_all_missing_tracks():
    with get_db() as con:
        con.cursor().execute("DELETE FROM missing_tracks")


def get_missing_track_by_id(mid: int) -> Optional[Dict]:
    with get_db() as con:
        r = con.cursor().execute("SELECT * FROM missing_tracks WHERE id=?",(mid,)).fetchone()
        return dict(r) if r else None


def update_track_status(mid: int, status: str):
    with get_db() as con:
        con.cursor().execute("UPDATE missing_tracks SET status=? WHERE id=?",(status,mid))


def _clean_string(text: str) -> str:
    s = text.lower()
    s = re.sub(r"\s*[\(\[].*?[\)\]]\s*",' ',s)
    s = re.sub(r"[^\w\s\-\'\&]",' ',s)
    return re.sub(r"\s+",' ',s).strip()


def get_library_index_stats() -> Dict[str,int]:
    with get_db() as con:
        cnt = con.cursor().execute("SELECT COUNT(*) FROM plex_library_index").fetchone()[0]
        return {'total_tracks_indexed':cnt}


def check_track_in_index(title:str,artist:str) -> bool:
    tc,ac = _clean_string(title),_clean_string(artist)
    with get_db() as con:
        r = con.cursor().execute("SELECT id FROM plex_library_index WHERE title_clean=? AND artist_clean=?",(tc,ac)).fetchone()
        return bool(r)


def check_track_in_index_smart(title:str,artist:str,debug:bool=False) -> bool:
    from thefuzz import fuzz
    tc,ac = _clean_string(title),_clean_string(artist)
    # exact
    if check_track_in_index(title,artist): return True
    # fuzzy retrieve candidates
    patterns=[]
    if len(tc)>3: patterns.append(f"%{tc[:4]}%")
    if len(ac)>3: patterns.append(f"%{ac[:4]}%")
    if patterns:
        q = " OR ".join(["title_clean LIKE ? OR artist_clean LIKE ?" for _ in patterns])
        params = []
        for p in patterns: params.extend([p,p])
        candidates = get_db().cursor().execute(f"SELECT title_clean,artist_clean FROM plex_library_index WHERE {q}",tuple(params)).fetchall()
        for dbt,dba in candidates:
            tscore = fuzz.token_set_ratio(tc,dbt)
            ascore = fuzz.token_set_ratio(ac,dba) if ac and dba else 100
            score = (tscore*0.7 + ascore*0.3) if ac and dba else tscore
            if score>=85: return True
    return False


def check_track_in_filesystem(title:str,artist:str,base_path:str="M:\\Organizzata") -> bool:
    import glob,platform
    start=time.time()
    if platform.system()!='Windows': base_path = base_path.replace('M:\\','/mnt/m/')
    tc= re.sub(r'[<>:"/\\|?*]','',title)[:30]
    ac= re.sub(r'[<>:"/\\|?*]','',artist)[:30]
    patterns=[f"{base_path}/**/*{tc[:15]}*{ac[:15]}*.mp3"]
    for p in patterns:
        if time.time()-start>5: break
        try:
            if glob.glob(p,recursive=True): return True
        except: pass
    return False


def comprehensive_track_verification(title:str,artist:str,debug:bool=False) -> Dict[str,bool]:
    res={'exact_match':False,'smart_match':False,'filesystem_match':False,'exists':False,'match_method':'none'}
    if check_track_in_index(title,artist): res.update({'exact_match':True,'exists':True,'match_method':'exact'}); return res
    if check_track_in_index_smart(title,artist,debug): res.update({'smart_match':True,'exists':True,'match_method':'smart'}); return res
    if check_track_in_filesystem(title,artist): res.update({'filesystem_match':True,'exists':True,'match_method':'filesystem'})
    return res


def add_track_to_index(track:Track) -> bool:
    if not hasattr(track,'title'): return False
    title,artist,album = track.title,track.grandparentTitle,track.parentTitle
    year,added = getattr(track,'year',None),getattr(track,'addedAt',None)
    tc,ac,alb = _clean_string(title),_clean_string(artist),_clean_string(album)
    for attempt in range(3):
        try:
            with sqlite3.connect(DB_PATH,timeout=10) as con:
                con.execute("INSERT OR IGNORE INTO plex_library_index (title_clean,artist_clean,album_clean,year,added_at) VALUES (?,?,?,?,?)",(tc,ac,alb,year,added))
            return True
        except sqlite3.OperationalError:
            time.sleep(0.1)
    return False


def bulk_add_tracks_to_index(tracks:List[Track],chunk_size:int=1000) -> int:
    data=[]
    for t in tracks:
        if not hasattr(t,'title'): continue
        data.append((_clean_string(t.title),_clean_string(t.grandparentTitle),_clean_string(t.parentTitle),getattr(t,'year',None),getattr(t,'addedAt',None)))
    inserted=0
    for i in range(0,len(data),chunk_size):
        chunk=data[i:i+chunk_size]
        with sqlite3.connect(DB_PATH) as con:
            con.execute("PRAGMA synchronous=OFF"); con.execute("PRAGMA journal_mode=MEMORY")
            cur=con.cursor()
            cur.executemany("INSERT OR IGNORE INTO plex_library_index (title_clean,artist_clean,album_clean,year,added_at) VALUES (?,?,?,?,?)",chunk)
            inserted+=cur.rowcount
    return inserted


def test_matching_improvements(sample_size:int=100) -> Optional[Dict]:
    import random
    missing=get_missing_tracks()
    if not missing: return None
    sample=random.sample(missing,min(sample_size,len(missing)))
    old,new,impr=0,0,[]
    for _,title,artist,*_ in sample:
        if check_track_in_index(title,artist): old+=1
        if check_track_in_index_smart(title,artist): new+=1
        if not check_track_in_index(title,artist) and check_track_in_index_smart(title,artist): impr.append((title,artist))
    return {'old_matches':old,'new_matches':new,'improvements':len(impr),'test_size':len(sample)}


def clean_invalid_missing_tracks():
    tvs=['simpsons','family guy','episode','movie']
    with get_db() as con:
        cur=con.cursor()
        cur.execute("DELETE FROM missing_tracks WHERE source_playlist_title LIKE '%no_delete%'")
        for k in tvs:
            cur.execute("DELETE FROM missing_tracks WHERE title LIKE ? OR artist LIKE ?","%{}%".format(k))


def clean_resolved_missing_tracks() -> (int,int):
    with get_db() as con:
        cur=con.cursor()
        cur.execute("SELECT COUNT(*) FROM missing_tracks WHERE status IN ('downloaded','resolved_manual')")
        cnt=cur.fetchone()[0]
        if cnt>0: cur.execute("DELETE FROM missing_tracks WHERE status IN ('downloaded','resolved_manual')")
        return cnt, con.cursor().execute("SELECT COUNT(*) FROM missing_tracks").fetchone()[0]


def clean_tv_content_from_missing_tracks():
    clean_invalid_missing_tracks()


def diagnose_indexing_issues():
    plex_url,plex_token,lib=os.getenv('PLEX_URL'),os.getenv('PLEX_TOKEN'),os.getenv('LIBRARY_NAME','Music')
    if not plex_url or not plex_token: return
    plex=PlexServer(plex_url,plex_token)
    items=plex.library.section(lib).search(libtype='track',limit=1000)
    counts={'tracks':0,'non':0,'empty':0}
    for it in items:
        if isinstance(it,Track): counts['tracks']+=1
        else: counts['non']+=1
    logging.info(f"Index diagnosis: {counts}")


def clear_library_index():
    with get_db() as con:
        con.cursor().execute("DELETE FROM plex_library_index")
    logging.info("Cleared plex_library_index")
