"""Synthetic regression checks for climate cache. Temporary fixtures do not require the private research datasets."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import climate_access
from climate_block_cache import BlockCache
from climate_access import RangeReader, SourceIntegrityError


class FakeHeaders(dict):
    pass


def ok(data, size, etag='v1', start=0):
    """Build a minimal successful byte-range response fixture."""
    return 206, FakeHeaders({'Content-Range': f'bytes {start}-{start+len(data)-1}/{size}', 'ETag': etag}), data


class CacheTests(unittest.TestCase):
    """Original intents preserved; the transport is faked at `_get_range` so the
    tests never depend on proxy settings or the network."""

    def test_connection_reset_retries_without_partial_data(self):
        """Verify that connection reset retries without partial data."""
        with patch('climate_access._get_range', side_effect=[ConnectionResetError('reset'), ok(b'abcd', 4)]) as request, \
                patch('climate_access.time.sleep'):
            reader = RangeReader('https://example.test/a', 4, 'v1')
            self.assertEqual(reader.read(), b'abcd')
            self.assertEqual(request.call_count, 2)
            self.assertEqual(reader.transferred, 4)

    def test_retries_are_bounded(self):
        """Verify that retries are bounded."""
        before = climate_access.STATS.network_giveups
        with patch('climate_access._get_range', side_effect=ConnectionResetError('reset')) as request, \
                patch('climate_access.time.sleep') as sleep:
            with self.assertRaises(ConnectionResetError):
                RangeReader('https://example.test/a', 4).read()
            self.assertEqual(request.call_count, RangeReader.max_attempts)
            self.assertLessEqual(max(call.args[0] for call in sleep.call_args_list), RangeReader.max_backoff * 1.2)
        self.assertEqual(climate_access.STATS.network_giveups, before + 1)

    def test_dns_failure_is_retried(self):
        """Verify that dns failure is retried."""
        import socket
        with patch('climate_access._get_range', side_effect=[socket.gaierror(11001, 'getaddrinfo failed')] * 3 + [ok(b'abcd', 4)]), \
                patch('climate_access.time.sleep'):
            self.assertEqual(RangeReader('https://example.test/a', 4, 'v1').read(), b'abcd')

    def test_changed_source_is_not_retried(self):
        """Verify that changed source is not retried."""
        with patch('climate_access._get_range', return_value=ok(b'abcd', 4, etag='changed')) as request:
            with self.assertRaises(RuntimeError):
                RangeReader('https://example.test/a', 4, 'v1').read()
            self.assertEqual(request.call_count, 1)

    def test_wrong_content_range_is_not_retried(self):
        """Verify that wrong content range is not retried."""
        with patch('climate_access._get_range', return_value=(200, FakeHeaders({'ETag': 'v1'}), b'abcd')) as request:
            with self.assertRaises(SourceIntegrityError):
                RangeReader('https://example.test/a', 4, 'v1').read()
            self.assertEqual(request.call_count, 1)

    def test_non_transient_http_error_is_not_retried(self):
        """Verify that non transient http error is not retried."""
        import urllib.error
        error = urllib.error.HTTPError('https://example.test/a', 404, 'missing', {}, None)
        with patch('climate_access._get_range', side_effect=error) as request:
            with self.assertRaises(urllib.error.HTTPError):
                RangeReader('https://example.test/a', 4, 'v1').read()
            self.assertEqual(request.call_count, 1)

    def test_second_reader_uses_cache_and_changed_source_does_not(self):
        """Verify that second reader uses cache and changed source does not."""
        with tempfile.TemporaryDirectory() as directory:
            cache = BlockCache(Path(directory)/'blocks.sqlite')
            try:
                with patch('climate_access._get_range', return_value=ok(b'abcd', 4)) as request:
                    self.assertEqual(RangeReader('https://example.test/a', 4, 'v1', cache).read(), b'abcd')
                    again = RangeReader('https://example.test/a', 4, 'v1', cache)
                    self.assertEqual(again.read(), b'abcd')
                    self.assertEqual(again.transferred, 0)
                    self.assertEqual(request.call_count, 1)
                self.assertIsNone(cache.get(cache.key('https://example.test/a', 4, 'v2', 0)))
            finally:
                cache.close()

    def test_eviction_and_corruption(self):
        """Verify that eviction and corruption."""
        with tempfile.TemporaryDirectory() as directory:
            cache = BlockCache(Path(directory)/'blocks.sqlite', limit=8)
            try:
                cache.put('a', b'1234')
                cache.put('b', b'5678')
                cache.get('a')
                cache.put('c', b'abcd')
                self.assertIsNone(cache.get('b'))
                with cache.connect() as db:
                    db.execute("UPDATE blocks SET data=? WHERE key='a'", (b'xxxx',))
                self.assertIsNone(cache.get('a'))
                self.assertEqual(cache.get('c'), b'abcd')
            finally:
                cache.close()

    def test_existing_cache_file_is_reused(self):
        """Verify that existing cache file is reused."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'blocks.sqlite'
            first = BlockCache(path)
            first.put('k', b'data')
            first.close()
            second = BlockCache(path)
            try:
                self.assertEqual(second.get('k'), b'data')
            finally:
                second.close()
