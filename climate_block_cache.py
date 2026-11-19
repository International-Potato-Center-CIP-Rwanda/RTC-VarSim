"""Bounded persistent cache of verified HTTP ranges, shared by readers.

Proposed revision: one long-lived connection per cache object (instead of a new
connection + commit per lookup), WAL journaling and an index on `used`, so LRU
lookups do not scan the table. Keys, SHA-256 verification, LRU eviction and the
byte limit are unchanged; the existing database file is reused as-is.
"""
import hashlib
import sqlite3
import threading
import time
from pathlib import Path
from contextlib import contextmanager

class BlockCache:
    def __init__(self, path, limit=256*1024*1024):
        """Initialize BlockCache from its supplied inputs without starting the application server."""
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.limit=limit
        self.lock=threading.Lock()
        self.db=sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        with self.lock, self.db:
            self.db.execute('PRAGMA journal_mode=WAL')
            self.db.execute('CREATE TABLE IF NOT EXISTS blocks (key TEXT PRIMARY KEY, data BLOB, sha TEXT, used INTEGER)')
            self.db.execute('CREATE INDEX IF NOT EXISTS blocks_used ON blocks(used)')
    @contextmanager
    def connect(self):
        """Kept for callers/tests that inspect the database directly."""
        with self.lock, self.db:
            yield self.db
    def close(self):
        """Close the cache database connection when processing is finished."""
        with self.lock:
            self.db.close()
    def __del__(self):
        """Release cache resources during object cleanup without propagating destructor errors."""
        try: self.db.close()
        except Exception: pass
    @staticmethod
    def key(url, size, etag, start):
        """Build a cache identity from source metadata and block offset."""
        return hashlib.sha256(repr((url,size,etag,start)).encode()).hexdigest()
    @staticmethod
    def tick(db):
        """Advance the cache access counter used for eviction ordering."""
        previous=db.execute('SELECT COALESCE(MAX(used),0) FROM blocks').fetchone()[0]
        return max(time.time_ns(),previous+1)
    def get(self, key):
        """Return a valid cached block and update its access order; discard corrupt entries."""
        with self.lock, self.db as db:
            row=db.execute('SELECT data,sha FROM blocks WHERE key=?',(key,)).fetchone()
            if row is None: return None
            if hashlib.sha256(row[0]).hexdigest()!=row[1]:
                db.execute('DELETE FROM blocks WHERE key=?',(key,))
                return None
            db.execute('UPDATE blocks SET used=? WHERE key=?',(self.tick(db),key))
            return row[0]
    def put(self, key, data):
        """Store a checksummed byte block and evict old entries to respect the cache size limit."""
        if len(data)>self.limit: return
        with self.lock, self.db as db:
            db.execute('INSERT OR REPLACE INTO blocks VALUES (?,?,?,?)',(key,data,hashlib.sha256(data).hexdigest(),self.tick(db)))
            total=db.execute('SELECT COALESCE(SUM(LENGTH(data)),0) FROM blocks').fetchone()[0]
            while total>self.limit:
                oldest,length=db.execute('SELECT key,LENGTH(data) FROM blocks ORDER BY used LIMIT 1').fetchone()
                db.execute('DELETE FROM blocks WHERE key=?',(oldest,))
                total-=length
