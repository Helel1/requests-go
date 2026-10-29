"""Loader selection and get_build_info() regressions.

These run against whatever library is loaded (the tracked legacy binaries in a
plain checkout, or the freshly built one in a build stage), so they assert the
selection logic and metadata reporting rather than binary identity.
"""
import hashlib
import importlib
import os
import unittest
from unittest import mock

from requests_go import get_build_info
from requests_go.__version__ import __version__
from requests_go.tls_client import client
import requests_go._build_info as build_info_module


class SelectLibraryNameTest(unittest.TestCase):
    def test_linux_x86_64_uses_amd64_library(self):
        self.assertEqual(client.select_library_name("linux", "x86_64", 8), "requests-go-amd64.so")

    def test_linux_amd64_alias_uses_amd64_library(self):
        self.assertEqual(client.select_library_name("linux", "AMD64", 8), "requests-go-amd64.so")

    def test_linux_aarch64_uses_arm64_library(self):
        self.assertEqual(client.select_library_name("linux", "aarch64", 8), "requests-go-arm64.so")
        self.assertEqual(client.select_library_name("linux", "arm64", 8), "requests-go-arm64.so")

    def test_linux_32_bit_is_not_mapped_to_a_library(self):
        # The previous loader matched "x86" as a substring, so x86_64 loaded
        # the 32-bit library name. i686 has no bundled library at all.
        with self.assertRaises(OSError):
            client.select_library_name("linux", "i686", 4)

    def test_darwin_selection(self):
        self.assertEqual(client.select_library_name("darwin", "arm64", 8), "requests-go-arm64.dylib")
        self.assertEqual(client.select_library_name("darwin", "x86_64", 8), "requests-go-x86.dylib")

    def test_windows_amd64_uses_win64_library(self):
        self.assertEqual(client.select_library_name("win32", "AMD64", 8), "requests-go-win64.dll")
        self.assertEqual(client.select_library_name("cygwin", "x86_64", 8), "requests-go-win64.dll")

    def test_windows_arm64_is_not_given_the_amd64_library(self):
        with self.assertRaises(OSError) as caught:
            client.select_library_name("win32", "ARM64", 8)
        self.assertIn("win32", str(caught.exception))

    def test_windows_32_bit_is_rejected(self):
        # The 32-bit DLL is not shipped; selecting it by pointer size alone
        # would fail at load time with a confusing error.
        with self.assertRaises(OSError):
            client.select_library_name("win32", "AMD64", 4)

    def test_other_unix_platforms_are_rejected(self):
        # Only Linux gets the ELF shared objects; other Unixes must not be
        # mapped to the Linux library name.
        for platform_name in ("freebsd13", "sunos5", "aix7"):
            with self.assertRaises(OSError):
                client.select_library_name(platform_name, "x86_64", 8)

    def test_unknown_platform_raises_instead_of_guessing(self):
        with self.assertRaises(OSError):
            client.select_library_name("sunos5", "sparc", 8)


class BuildInfoTest(unittest.TestCase):
    def test_reports_python_version_and_loaded_library(self):
        info = get_build_info()
        self.assertEqual(info["python_version"], __version__)
        self.assertEqual(info["library_path"], client.LIBRARY_PATH)
        self.assertTrue(os.path.isabs(info["library_path"]))
        self.assertIn(info["library_source"], ("bundled", "override"))

    def test_kernel_metadata_is_either_absent_or_matches_library(self):
        info = get_build_info()
        if info["kernel_metadata"] == "bundled":
            self.assertIn("upstream_commit", info["kernel"])
            self.assertEqual(len(info["kernel"]["upstream_commit"]), 40)
            self.assertEqual(info["kernel"]["library_sha256"], _sha256(info["library_path"]))
        else:
            self.assertIn(info["kernel_metadata"], ("missing-unknown", "override-unknown"))
            self.assertIsNone(info["kernel"])

    def test_missing_metadata_is_reported_as_unknown(self):
        # Force the bundled branch so the check also holds when the test run
        # itself uses REQUESTGO_DEPPATH.
        with mock.patch.object(build_info_module, "BUILD_INFO_FILENAME", "no-such-build-info.json"),                 mock.patch.object(client, "LIBRARY_SOURCE", "bundled"):
            info = get_build_info()
        self.assertEqual(info["kernel_metadata"], "missing-unknown")
        self.assertIsNone(info["kernel"])

    def test_override_does_not_claim_bundled_identity(self):
        bundled_path = client.LIBRARY_PATH
        with mock.patch.dict(os.environ, {"REQUESTGO_DEPPATH": bundled_path}):
            importlib.reload(client)
            try:
                info = get_build_info()
            finally:
                pass
        self.addCleanup(importlib.reload, client)
        self.assertEqual(info["library_source"], "override")
        self.assertEqual(info["library_path"], os.path.abspath(bundled_path))
        self.assertEqual(info["kernel_metadata"], "override-unknown")
        self.assertIsNone(info["kernel"])


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    unittest.main()
