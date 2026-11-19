"""Test helper (not a test module): local HTTP range server.

Serves files from one directory with HTTP/1.1 keep-alive, counts connections,
requests and bytes, can simulate connection/request latency and bandwidth, and
can drop the next N requests abruptly (simulated network loss).
"""
import os
import re
import socket
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Stats:
    def __init__(self):
        """Initialize Stats from its supplied inputs without starting the application server."""
        self.lock = threading.Lock()
        self.connections = self.requests = self.bytes = self.fail_next = 0
        self.mode = 'normal'      # 'ignore_range' (200 + whole file) or 'oversize' (206 + extra bytes)

    def bump(self, **values):
        """Update the synthetic HTTP server counters while holding the test statistics lock."""
        with self.lock:
            for name, value in values.items():
                setattr(self, name, getattr(self, name) + value)


def serve(directory, *, connect_delay=0.0, rtt=0.0, bandwidth=None, etag='"v1"'):
    """Return (server, base_url, stats). Call server.shutdown() when done."""
    stats = Stats()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def setup(self):
            """Initialize the local HTTP request handler and its test connection bookkeeping."""
            super().setup()
            stats.bump(connections=1)
            if connect_delay:
                time.sleep(connect_delay)

        def log_message(self, *args):
            """Suppress routine HTTP access logs during synthetic transport tests."""
            pass

        def do_GET(self):
            """Serve a synthetic byte-range response with the configured delay, failure and protocol test modes."""
            stats.bump(requests=1)
            with stats.lock:
                fail = stats.fail_next > 0
                if fail:
                    stats.fail_next -= 1
            if fail:
                try:   # abortive close (RST); layout of struct linger differs on Windows
                    self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                                               struct.pack('HH' if os.name == 'nt' else 'ii', 1, 0))
                except OSError:
                    pass
                self.close_connection = True
                self.connection.close()
                return
            if rtt:
                time.sleep(rtt)
            path = os.path.join(directory, os.path.basename(self.path))
            size = os.path.getsize(path)
            match = re.fullmatch(r'bytes=(\d+)-(\d+)', self.headers.get('Range', ''))
            start, stop = int(match[1]), min(int(match[2]), size - 1)
            with open(path, 'rb') as handle:
                handle.seek(start)
                body = handle.read(stop - start + 1)
            if stats.mode == 'ignore_range':
                with open(path, 'rb') as handle:
                    body = handle.read()
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('ETag', etag)
                self.end_headers()
                try:
                    self.wfile.write(body)
                except OSError:
                    pass
                stats.bump(bytes=len(body))
                return
            if stats.mode == 'oversize':
                body = body + b'X' * 4096
            if bandwidth:
                time.sleep(len(body) / bandwidth)
            stats.bump(bytes=len(body))
            self.send_response(206)
            self.send_header('Content-Range', f'bytes {start}-{stop}/{size}')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('ETag', etag)
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f'http://127.0.0.1:{server.server_port}/', stats


def loopback_available(server, timeout=5):
    """True if this process can open a TCP connection to the local test server."""
    try:
        with socket.create_connection(('127.0.0.1', server.server_port), timeout=timeout):
            return True
    except OSError:
        return False
