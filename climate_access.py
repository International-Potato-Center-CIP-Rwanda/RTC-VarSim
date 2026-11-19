"""Inspect a remote TIFF using verified, bounded HTTPS range requests.

Proposed revision (review before deploying; do not swap into a running worker):
- persistent keep-alive connections per thread (one DNS lookup/TLS handshake per
  connection instead of per 64 KiB block) when no proxy is configured;
- contiguous missing blocks are fetched in one verified range request, with a
  bounded read-ahead only for sequential access;
- the first block is fetched in Python before GDAL opens the file (see prime());
- network-class failures are retried for longer (bounded, jittered) and counted
  so the job runner can tell a network outage from a genuine data error.
Integrity checks are unchanged: HTTP 206, exact Content-Range, ETag and length.
"""
import functools
import http.client
import io
import os
import random
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict

BLOCK = 65536
MEMORY_BLOCKS = 128
TRANSIENT_HTTP = (408, 429, 500, 502, 503, 504)


def _env_int(name, default):
    """Read a bounded integer transport setting from the environment, using the supplied default when absent."""
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


HTTP_TIMEOUT = _env_int('AFSA_HTTP_TIMEOUT', 30)


class SourceIntegrityError(RuntimeError):
    """Range/identity mismatch. Never retried."""


class TransientHTTPStatus(Exception):
    def __init__(self, code):
        """Initialize TransientHTTPStatus from its supplied inputs without starting the application server."""
        super().__init__(f'Transient HTTP status {code}')
        self.code = code


class _Stats:
    """Process-wide counters for logging and for classifying job failures."""
    FIELDS = ('requests', 'bytes', 'connections', 'retries', 'network_giveups', 'integrity_errors', 'disk_hits')

    def __init__(self):
        """Initialize _Stats from its supplied inputs without starting the application server."""
        self.lock = threading.Lock()
        for name in self.FIELDS:
            setattr(self, name, 0)
        self.last_failed_source = None

    def record_giveup(self, url, size, etag):
        """Record a source whose network retries were exhausted without counting duplicate give-ups twice."""
        with self.lock:
            self.network_giveups += 1
            self.last_failed_source = dict(url=url, bytes=size, etag=etag)

    def add(self, **values):
        """Update transport counters while holding the statistics lock."""
        with self.lock:
            for name, value in values.items():
                setattr(self, name, getattr(self, name) + value)

    def snapshot(self):
        """Return a thread-safe copy of the current transport counters."""
        with self.lock:
            return {name: getattr(self, name) for name in self.FIELDS}


STATS = _Stats()
_local = threading.local()


def _proxied(url):
    """Determine whether the source URL must use the configured proxy settings."""
    parsed = urllib.parse.urlsplit(url)
    return _proxied_host(parsed.scheme, parsed.hostname or '')


@functools.lru_cache(maxsize=64)
def _proxied_host(scheme, host):
    # Cached: on Windows getproxies() reads the registry and proxy_bypass() may resolve DNS.
    """Look up the proxy decision for a scheme and host without changing the requested source URL."""
    return scheme in urllib.request.getproxies() and not urllib.request.proxy_bypass(host)


def _connection(parsed):
    """Get or create the thread-local HTTP connection used for a source request."""
    connections = getattr(_local, 'connections', None)
    if connections is None:
        connections = _local.connections = {}
    key = (parsed.scheme, parsed.hostname, parsed.port)
    conn = connections.get(key)
    if conn is None:
        if parsed.scheme == 'https':
            conn = http.client.HTTPSConnection(parsed.hostname, parsed.port, timeout=HTTP_TIMEOUT,
                                               context=ssl.create_default_context())
        else:
            conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=HTTP_TIMEOUT)
        connections[key] = conn
        STATS.add(connections=1)
    return key, conn


def _drop_connection(key):
    """Discard a cached connection after an error so later requests reconnect safely."""
    conn = getattr(_local, 'connections', {}).pop(key, None)
    if conn is not None:
        conn.close()


def _get_range(url, start, stop):
    """One HTTP range GET. Returns (status, headers-like, body).

    The body is read only for a 206 whose Content-Range names exactly the requested
    span, and never more than the requested length + 1 bytes, so a server that
    ignores Range (200 + whole file) or sends an oversized body cannot make us
    download or buffer the file. Any connection left with unread bytes is discarded.
    """
    STATS.add(requests=1)
    expected = stop - start + 1
    if _proxied(url):
        # Same path as the original reader, so proxy settings keep working.
        req = urllib.request.Request(url, headers={'Range': f'bytes={start}-{stop}'})
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as response:
                if response.status != 206 or not str(response.headers.get('Content-Range', '')).startswith(f'bytes {start}-{stop}/'):
                    return response.status, response.headers, b''
                return response.status, response.headers, response.read(expected + 1)
        except urllib.error.HTTPError as error:
            if error.code in TRANSIENT_HTTP:
                raise TransientHTTPStatus(error.code) from error
            raise
    parsed = urllib.parse.urlsplit(url)
    target = parsed.path + (f'?{parsed.query}' if parsed.query else '')
    key, conn = _connection(parsed)
    try:
        conn.request('GET', target, headers={'Range': f'bytes={start}-{stop}'})
        response = conn.getresponse()
        headers = response.headers
        valid = response.status == 206 and str(headers.get('Content-Range', '')).startswith(f'bytes {start}-{stop}/')
        body = response.read(expected + 1) if valid else b''
        clean = valid and len(body) == expected and response.length == 0 and not response.will_close
        if not clean:
            _drop_connection(key)       # unread or unexpected bytes: never reuse this socket
    except BaseException:
        _drop_connection(key)
        raise
    if response.status in TRANSIENT_HTTP:
        raise TransientHTTPStatus(response.status)
    return response.status, headers, body


class RangeReader(io.RawIOBase):
    max_attempts = _env_int('AFSA_RANGE_ATTEMPTS', 10)      # 1+2+4+...+60 s ≈ 4.5 min of waiting
    max_backoff = 60
    max_coalesce_blocks = _env_int('AFSA_MAX_COALESCE_BLOCKS', 32)  # ≤ 2 MiB per request

    def __init__(self, url, size, etag=None, disk_cache=None):
        """Initialize RangeReader from its supplied inputs without starting the application server."""
        self.url, self.size, self.pos = url, size, 0
        self.cache = OrderedDict()
        self.etag = etag
        self.transferred = 0
        self.disk_cache = disk_cache
        self.cache_hits = 0
        self._last_fetched = None
        self._ahead = 0

    def fetch_range(self, start, stop):
        """Fetch a validated byte range with bounded transient-error retries; reject changed identity or invalid range responses."""
        last_error = None
        for attempt in range(self.max_attempts):
            if attempt:
                delay = min(self.max_backoff, 2 ** (attempt - 1)) * random.uniform(0.8, 1.2)
                STATS.add(retries=1)
                time.sleep(delay)
            try:
                status, headers, data = _get_range(self.url, start, stop)
                if status != 206 or headers.get('Content-Range') != f'bytes {start}-{stop}/{self.size}':
                    raise SourceIntegrityError('Server did not honor range')
                if self.etag and headers.get('ETag') != self.etag:
                    raise SourceIntegrityError('Source changed since inventory')
                if len(data) > stop - start + 1:
                    raise SourceIntegrityError('Oversized range response')
                if len(data) != stop - start + 1:
                    raise http.client.IncompleteRead(data, stop - start + 1 - len(data))
                return data
            except SourceIntegrityError:
                STATS.add(integrity_errors=1)
                raise
            except TransientHTTPStatus as error:
                last_error = error
            except urllib.error.HTTPError:
                raise
            except (OSError, http.client.HTTPException) as error:
                # DNS (getaddrinfo), resets, timeouts, truncated bodies.
                last_error = error
        STATS.record_giveup(self.url, self.size, self.etag)
        if isinstance(last_error, TransientHTTPStatus) and isinstance(last_error.__cause__, urllib.error.HTTPError):
            raise last_error.__cause__
        raise last_error

    def prime(self):
        """Fetch the first block in Python before GDAL reads anything.

        Measured with rasterio 1.5.2 / GDAL 3.12: if the very first read GDAL makes
        through a Python opener raises, the process aborts (C++ std::length_error,
        exit 134) instead of raising RasterioIOError, so no failure marker is written
        and no retry is possible. Priming moves that first network read into Python.
        """
        if 0 not in self.cache and not self._from_disk(0):
            self._load(0, min(self.size, BLOCK))
        return self

    def readable(self):
        """Advertise read support to the file-like Rasterio adapter."""
        return True
    def seekable(self):
        """Advertise random access to the file-like Rasterio adapter."""
        return True
    def tell(self):
        """Return the current byte offset in the remote file."""
        return self.pos

    def seek(self, offset, whence=0):
        """Update the byte offset using the requested absolute, relative or end-relative origin."""
        self.pos = offset + (self.pos if whence == 1 else self.size if whence == 2 else 0)
        if self.pos < 0: raise ValueError('Negative offset')
        return self.pos

    def _disk_key(self, start):
        """Identify a cached block using source URL, size, ETag and block position."""
        return self.disk_cache.key(self.url, self.size, self.etag, start) if self.disk_cache and self.etag else None

    def _from_disk(self, start):
        """Read and validate a persistent cache block when one exists."""
        key = self._disk_key(start)
        if key is None:
            return False
        cached = self.disk_cache.get(key)
        if cached is not None and len(cached) == min(start + BLOCK, self.size) - start:
            self._remember(start, cached)
            self.cache_hits += 1
            STATS.add(disk_hits=1)
            return True
        return False

    def _remember(self, start, data):
        """Store a fetched block in memory and the optional persistent cache."""
        self.cache[start] = data
        self.cache.move_to_end(start)
        while len(self.cache) > MEMORY_BLOCKS:
            self.cache.popitem(last=False)

    def _load(self, first, end):
        """Fetch block `first` plus following missing blocks in one request."""
        sequential = self._last_fetched is not None and first == self._last_fetched + BLOCK
        self._ahead = min(max(1, self._ahead * 2), self.max_coalesce_blocks) if sequential else 0
        needed_last = (end - 1) // BLOCK * BLOCK
        file_last = (self.size - 1) // BLOCK * BLOCK
        target_last = min(needed_last + self._ahead * BLOCK, file_last)
        blocks = [first]
        while len(blocks) < self.max_coalesce_blocks:
            candidate = blocks[-1] + BLOCK
            if candidate > target_last or candidate in self.cache or self._from_disk(candidate):
                break
            blocks.append(candidate)
        stop = min(blocks[-1] + BLOCK, self.size) - 1
        data = self.fetch_range(first, stop)
        self.transferred += len(data)
        STATS.add(bytes=len(data))
        for start in blocks:
            chunk = data[start - first:min(start + BLOCK, self.size) - first]
            key = self._disk_key(start)
            if key: self.disk_cache.put(key, chunk)
            self._remember(start, chunk)
        self._last_fetched = blocks[-1]

    def read(self, size=-1):
        """Read bytes at the current position, preserving the file-like contract and configured response-size bounds."""
        end = self.size if size < 0 else min(self.size, self.pos + size)
        parts = []
        while self.pos < end:
            start = self.pos // BLOCK * BLOCK
            if start not in self.cache and not self._from_disk(start):
                self._load(start, end)
            block = self.cache[start]
            count = min(end - self.pos, start + len(block) - self.pos)
            parts.append(block[self.pos - start:self.pos - start + count])
            self.pos += count
        return b''.join(parts)


REACHABLE, UNREACHABLE, INTEGRITY = 'reachable', 'unreachable', 'integrity'


def source_state(url, size, etag=None):
    """Single-attempt one-byte probe through the same transport (proxy-aware).

    REACHABLE: valid 206 with matching size/ETag. UNREACHABLE: network-class failure
    or transient HTTP status (worth waiting). INTEGRITY: the server answered but the
    answer is wrong (non-206, wrong Content-Range/ETag, non-transient HTTP error);
    waiting will not fix it.
    """
    try:
        status, headers, data = _get_range(url, 0, 0)
    except TransientHTTPStatus:
        return UNREACHABLE
    except urllib.error.HTTPError:
        return INTEGRITY
    except (OSError, http.client.HTTPException):
        return UNREACHABLE
    if status != 206 or headers.get('Content-Range') != f'bytes 0-0/{size}' or len(data) != 1:
        return INTEGRITY
    if etag and headers.get('ETag') != etag:
        return INTEGRITY
    return REACHABLE


def source_reachable(url, size, etag=None):
    """Probe source availability with a bounded byte-range request and validate the expected identity."""
    return source_state(url, size, etag) == REACHABLE
