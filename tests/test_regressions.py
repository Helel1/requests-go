"""Regression tests for the pool / session-lifecycle / cookie / stream fixes.

Unit-level only: no network, no loopback server, no Go session is created
(``freeSession`` is replaced with a recorder, ``TLSAdapter.send`` with a stub).
They import the package, so they need a platform where
``requests_go.tls_client.dependencies`` can be loaded:

    python -m unittest discover -s tests -v
    # or: python tests/test_regressions.py
"""
import base64
import json
import threading
import unittest
from unittest import mock
from urllib.parse import urlparse

import requests
from requests.cookies import RequestsCookieJar

import requests_go.adapters as adapters_module
import requests_go.sessions as sessions_module
import requests_go.tls_client.stream as stream_module
from requests_go.pool import ClosedPool, TLSHandlerPool
from requests_go.tls_client.exceptions import TLSClientExeption
from requests_go.tls_client.response import _parse_cookies
from requests_go.tls_config.config import TLS_CHROME_LATEST


class FakeHandler(object):
    """Stands in for TLSRequest: counts construction and close calls."""

    created = 0

    def __init__(self, tls_config=None):
        FakeHandler.created += 1
        self.serial = FakeHandler.created
        self.tls_config = tls_config
        self.closed = False

    def send(self, options):
        return self.serial

    def close(self):
        self.closed = True


def make_pool(maxsize=1, block=False):
    return TLSHandlerPool(tls_factory=FakeHandler, maxsize=maxsize, block=block,
                          tls_config=None)


class PoolTests(unittest.TestCase):
    def setUp(self):
        FakeHandler.created = 0

    def test_non_blocking_pool_creates_handler_on_demand(self):
        # A urllib3 pool is a cache, not a limiter: exceeding maxsize must not
        # fail the request.
        pool = make_pool(maxsize=1, block=False)
        first = pool.get_handler_from_pool()
        second = pool.get_handler_from_pool()
        self.assertIsNot(first, second)

    def test_blocking_pool_waits_for_a_returned_handler(self):
        # block=True keeps the urllib3 "wait" contract: it must neither create
        # extra handlers nor raise EmptyPool while the pool is empty.
        pool = make_pool(maxsize=1, block=True)
        pooled = pool.get_handler_from_pool()
        result = []

        def take():
            result.append(pool.get_handler_from_pool())

        thread = threading.Thread(target=take, daemon=True)
        thread.start()
        thread.join(0.3)
        self.assertTrue(thread.is_alive(), "block=True must wait for a free handler")
        pool.put_handler_back(pooled)
        thread.join(2)
        self.assertEqual(result, [pooled])

    def test_put_handler_back_drops_real_overflow(self):
        # Take *two* handlers from a maxsize=1 pool first: the pool is then
        # empty and only the second put can overflow it.
        pool = make_pool(maxsize=1, block=False)
        first = pool.get_handler_from_pool()
        second = pool.get_handler_from_pool()
        self.assertIsNot(first, second)
        pool.put_handler_back(first)    # fills the pool
        self.assertEqual(pool._pool.qsize(), 1)
        pool.put_handler_back(second)   # queue.Full -> must be dropped, not raised
        self.assertEqual(pool._pool.qsize(), 1)

    def test_closed_pool_rejects_handlers(self):
        pool = make_pool(maxsize=1, block=False)
        pool.close()
        with self.assertRaises(ClosedPool):
            pool.get_handler_from_pool()


class SessionLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.freed = []
        self._original_free = sessions_module.freeSession
        sessions_module.freeSession = lambda session_id: self.freed.append(session_id)

    def tearDown(self):
        sessions_module.freeSession = self._original_free

    def test_close_is_idempotent_and_releases_once(self):
        session = sessions_module.Session()
        session.close()
        session.close()
        self.assertEqual(len(self.freed), 1)

    def test_request_after_close_rebuilds_adapters(self):
        session = sessions_module.Session()
        before = session.adapters["https://"]
        session.close()
        session._reopen()  # what Session.request() does when called after close()
        after = session.adapters["https://"]
        self.assertIsNot(before, after)
        self.assertFalse(session._Session__closed)
        self.assertFalse(session._Session__freed)

        # The rebuilt session owns a fresh Go session id, so a second close
        # releases again (close -> reuse -> close must not be a no-op).
        session.close()
        self.assertEqual(len(self.freed), 2)


class SessionIdBindingTests(unittest.TestCase):
    """The id used by the Go session must be the id that freeSession releases.

    ``TLSConfig.fromJSON`` drops ``id``, so a cloned config gets a brand new
    uuid; Session.request() has to bind the clone back to its own id.
    """

    def setUp(self):
        self.freed = []
        self.adapter_ids = []
        self._original_free = sessions_module.freeSession
        sessions_module.freeSession = lambda session_id: self.freed.append(session_id)
        self._original_send = adapters_module.TLSAdapter.send

        def fake_send(adapter, request, **kwargs):
            self.adapter_ids.append(adapter._tls_config.id)
            response = requests.Response()
            response.status_code = 200
            response.url = request.url
            response._content = b""
            return response

        adapters_module.TLSAdapter.send = fake_send

    def tearDown(self):
        adapters_module.TLSAdapter.send = self._original_send
        sessions_module.freeSession = self._original_free

    def _assert_ids_match_session(self, session):
        self.assertEqual(len(self.freed), 1)
        self.assertTrue(self.adapter_ids)
        for adapter_id in self.adapter_ids:
            self.assertEqual(adapter_id, session._Session__id)
        self.assertEqual(self.freed[0].value.decode(), session._Session__id)

    def test_per_request_tls_config_is_bound_to_session_id(self):
        session = sessions_module.Session()
        # A different tls_config forces _ensure_https_adapter to remount, i.e.
        # the clone branch that used to lose the id.
        session.request("GET", "https://127.0.0.1:1/", tls_config=TLS_CHROME_LATEST,
                        allow_redirects=False)
        session.close()
        self._assert_ids_match_session(session)

    def test_session_tls_config_is_bound_to_session_id(self):
        session = sessions_module.Session()
        # Session.request() only mounts a TLSAdapter when the session config has
        # a ja3; the default TLSConfig() has none (HTTPAdapter path).
        session.tls_config = TLS_CHROME_LATEST
        session.request("GET", "https://127.0.0.1:1/", allow_redirects=False)
        session.close()
        self._assert_ids_match_session(session)


class CookieParseTests(unittest.TestCase):
    def _parse(self, cookie):
        jar = RequestsCookieJar()
        _parse_cookies([cookie], urlparse("https://127.0.0.1:8443/"), jar)
        return jar

    def _cookie(self, expires, **extra):
        payload = {"Name": "py", "Value": "1", "Path": "/", "Domain": "127.0.0.1",
                   "Expires": expires, "Secure": False, "HttpOnly": False}
        payload.update(extra)
        return next(iter(self._parse(payload)))

    def test_go_zero_expiry_is_a_session_cookie(self):
        # http.Cookie without Expires serialises as the zero time; treating that
        # as an expiry makes requests drop the cookie and never send it.
        # (MaxAge=-1 / delete semantics are NOT mapped by this function; that is
        # a separate, pre-existing gap.)
        cookie = self._cookie("0001-01-01T00:00:00Z", MaxAge=-1)
        self.assertIsNone(cookie.expires)

    def test_epoch_expiry_stays_expired(self):
        cookie = self._cookie("1970-01-01T00:00:00Z")
        self.assertEqual(cookie.expires, 0)

    def test_pre_epoch_expiry_stays_expired(self):
        cookie = self._cookie("1969-12-31T23:59:59Z")
        self.assertEqual(cookie.expires, -1)

    def test_real_expiry_is_kept(self):
        cookie = self._cookie("2030-01-01T00:00:00Z")
        self.assertIsNotNone(cookie.expires)
        self.assertGreater(cookie.expires, 0)


def _b64(data):
    return base64.b64encode(data).decode("utf-8")


class StreamBodyTests(unittest.TestCase):
    """StreamBody error paths: close the Go entry once, free error ids once,
    never lose the last data chunk, never return silently truncated data."""

    def setUp(self):
        self.reads = []
        self.close_calls = []
        self.free_calls = []
        self._patches = [
            mock.patch.object(stream_module, "_stream_read",
                              side_effect=lambda stream_id, size: self._next_read()),
            mock.patch.object(stream_module, "_stream_close",
                              side_effect=lambda stream_id: self.close_calls.append(stream_id)),
            mock.patch.object(stream_module, "_free_memory",
                              side_effect=lambda response_id: self.free_calls.append(response_id)),
        ]
        for patch in self._patches:
            patch.start()

    def tearDown(self):
        for patch in self._patches:
            patch.stop()

    def _next_read(self):
        item = self.reads.pop(0)
        if isinstance(item, Exception):
            raise item
        return json.dumps(item).encode("utf-8")

    def test_error_response_frees_id_and_closes_once(self):
        self.reads = [{"err": "boom", "id": "err-1"}]
        body = stream_module.StreamBody("sid")
        with self.assertRaises(TLSClientExeption):
            body.read(16)
        self.assertEqual(self.free_calls, [b"err-1"])
        self.assertEqual(self.close_calls, [b"sid"])
        body.close()  # caller close after the error must stay a no-op
        self.assertEqual(self.close_calls, [b"sid"])

    def test_dll_failure_closes_stream(self):
        self.reads = [RuntimeError("dll exploded")]
        body = stream_module.StreamBody("sid")
        with self.assertRaises(TLSClientExeption):
            body.read(16)
        self.assertEqual(self.close_calls, [b"sid"])
        self.assertEqual(self.free_calls, [])

    def test_tail_chunk_error_is_visible_on_next_read(self):
        self.reads = [{"data": _b64(b"tail"), "eof": True, "err": "boom"}]
        body = stream_module.StreamBody("sid")
        self.assertEqual(body.read(16), b"tail")   # data delivered first
        self.assertEqual(self.close_calls, [])     # not closed yet
        with self.assertRaises(TLSClientExeption):
            body.read(16)
        self.assertEqual(self.close_calls, [b"sid"])

    def test_read_all_raises_instead_of_returning_truncated_data(self):
        self.reads = [
            {"data": _b64(b"part"), "eof": False},
            {"data": _b64(b"tail"), "eof": True, "err": "boom"},
        ]
        body = stream_module.StreamBody("sid")
        with self.assertRaises(TLSClientExeption):
            body.read(-1)
        self.assertEqual(self.close_calls, [b"sid"])

    def test_close_does_not_swallow_pending_error(self):
        self.reads = [{"data": _b64(b"x"), "eof": True, "err": "boom"}]
        body = stream_module.StreamBody("sid")
        self.assertEqual(body.read(16), b"x")
        body.close()
        with self.assertRaises(TLSClientExeption):
            body.read(16)
        self.assertEqual(self.close_calls, [b"sid"])

    def test_eof_keeps_tail_data(self):
        self.reads = [{"data": _b64(b"abc"), "eof": True}]
        body = stream_module.StreamBody("sid")
        self.assertEqual(body.read(-1), b"abc")
        body.close()
        self.assertEqual(self.close_calls, [b"sid"])
        self.assertEqual(self.free_calls, [])


if __name__ == "__main__":
    unittest.main()
