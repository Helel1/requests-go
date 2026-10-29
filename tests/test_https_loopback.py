"""Loopback HTTPS smoke test through the Go kernel library.

Verifies that an HTTPS request really goes through the TLS adapter (not a plain
``requests`` HTTPAdapter) and that the freshly built library can complete a TLS
handshake. The server only listens on 127.0.0.1 and the certificate is
generated locally.
"""
import http.server
import os
import shutil
import ssl
import subprocess
import tempfile
import threading
import unittest

import requests_go
from requests_go.adapters import TLSAdapter
from requests_go.tls_config.config import TLS_CHROME_LATEST


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"ok-loopback"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@unittest.skipUnless(shutil.which("openssl"), "openssl is required to create the test certificate")
class LoopbackHTTPSTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="rg-loopback-")
        cert = os.path.join(cls.tmp, "cert.pem")
        key = os.path.join(cls.tmp, "key.pem")
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
             "-subj", "/CN=127.0.0.1", "-keyout", key, "-out", cert],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        cls.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        cls.httpd.socket = context.wrap_socket(cls.httpd.socket, server_side=True)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = "https://127.0.0.1:%d/" % cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_https_request_uses_tls_adapter(self):
        session = requests_go.Session()
        try:
            response = session.get(
                self.url, tls_config=TLS_CHROME_LATEST, verify=False, timeout=10
            )
            self.assertIsInstance(session.get_adapter(self.url), TLSAdapter)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.text.strip(), "ok-loopback")
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
