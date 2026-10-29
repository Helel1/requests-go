"""Build tooling regressions: staging rules, target guard and packaging guard.

No Go build is performed here; the compile step is exercised by CI and by
``python -m tools.build_go_lib``.
"""
import os
import subprocess
import sys
import tempfile
import unittest

from tools import build_go_lib

REPO_ROOT = build_go_lib.REPO_ROOT


def _write(path, content="x"):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)


class StagePythonPackageTest(unittest.TestCase):
    def test_stage_keeps_only_the_new_library_and_build_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = os.path.join(tmp, "requests-go-amd64.so")
            with open(library, "wb") as handle:
                handle.write(b"freshly built kernel")
            stage = os.path.join(tmp, "stage")

            build_go_lib._stage_python_package(
                stage, library, {"python_version": "x", "kernel": {"upstream_commit": "0" * 40}}
            )

            dependencies = os.path.join(stage, "requests_go", "tls_client", "dependencies")
            self.assertEqual(
                sorted(os.listdir(dependencies)),
                ["__init__.py", "requests-go-amd64.so"],
            )
            with open(os.path.join(dependencies, "requests-go-amd64.so"), "rb") as handle:
                self.assertEqual(handle.read(), b"freshly built kernel")
            self.assertTrue(os.path.exists(os.path.join(stage, "requests_go", "_build_info.json")))
            # The stage must still carry what an sdist needs.
            self.assertTrue(os.path.exists(os.path.join(stage, "setup.py")))
            self.assertTrue(os.path.exists(os.path.join(stage, "patches", "go-fix-46ef52b.diff")))
            self.assertTrue(os.path.exists(os.path.join(stage, "tools", "build_go_lib.py")))
            self.assertTrue(os.path.exists(os.path.join(stage, "LICENSE-GPL-3.0")))
            # Local scratch artifacts must not leak into the package.
            self.assertFalse(os.path.exists(os.path.join(stage, "requests-go-patched.zip")))

    def test_stage_inside_the_repository_copies_only_the_allowlist(self):
        """An output directory inside the repo must not be copied into itself."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "repo")
            for name in build_go_lib._STAGE_TOP_FILES:
                _write(os.path.join(repo, name), "top-level %s\n" % name)
            _write(os.path.join(repo, "requests_go", "__init__.py"))
            _write(os.path.join(repo, "requests_go", "_build_info.json"), '{"stale": true}\n')
            _write(os.path.join(repo, "requests_go", "tls_client", "dependencies", "__init__.py"))
            for old_binary in ("requests-go-arm64.so", "requests-go-win64.dll",
                               "requests-go-x86.dylib"):
                _write(os.path.join(repo, "requests_go", "tls_client", "dependencies", old_binary))
            _write(os.path.join(repo, "tools", "build_go_lib.py"))
            _write(os.path.join(repo, "patches", "go-fix.diff"))
            _write(os.path.join(repo, "patches", "scratch.txt"))
            _write(os.path.join(repo, "tests", "test_something.py"))
            _write(os.path.join(repo, "docs", "maintenance.md"))
            # Local output and scratch material that must never be staged.
            _write(os.path.join(repo, "out", "stage", "requests_go", "__init__.py"))
            _write(os.path.join(repo, "out", "dist", "requests_go-0.whl"))
            _write(os.path.join(repo, "out", "build_info.json"))
            _write(os.path.join(repo, "requests-go-fix-report.md"))
            _write(os.path.join(repo, "credentials.env"), "TOKEN=secret\n")

            library = os.path.join(tmp, "requests-go-amd64.so")
            with open(library, "wb") as handle:
                handle.write(b"freshly built kernel")
            stage = os.path.join(repo, "out", "stage-2")
            build_go_lib._stage_python_package(
                stage, library, {"kernel": {"upstream_commit": "0" * 40}}, source_root=repo
            )

            self.assertFalse(os.path.exists(os.path.join(stage, "out")))
            self.assertFalse(os.path.exists(os.path.join(stage, "requests-go-fix-report.md")))
            self.assertFalse(os.path.exists(os.path.join(stage, "credentials.env")))
            self.assertEqual(
                sorted(os.listdir(os.path.join(stage, "patches"))), ["go-fix.diff"]
            )
            dependencies = os.path.join(stage, "requests_go", "tls_client", "dependencies")
            self.assertEqual(
                sorted(os.listdir(dependencies)), ["__init__.py", "requests-go-amd64.so"]
            )
            with open(os.path.join(stage, "requests_go", "_build_info.json"), encoding="utf-8") as handle:
                self.assertNotIn("stale", handle.read())


class TargetGuardTest(unittest.TestCase):
    def test_other_targets_are_rejected_before_any_build(self):
        for env in ({"GOARCH": "arm64"}, {"GOOS": "darwin"}, {"GOOS": "linux", "GOARCH": "386"},
                    {"CGO_ENABLED": "0"}):
            with self.assertRaises(ValueError) as caught:
                build_go_lib.build_go_library("unused-go-dir", os.path.join("unused", "out"), env=env)
            self.assertIn("only supports", str(caught.exception))

    def test_supported_target_in_env_is_accepted(self):
        build_env = build_go_lib._build_env({"GOOS": "linux", "GOARCH": "amd64", "GOPROXY": "off"})
        self.assertEqual(build_env["GOOS"], "linux")
        self.assertEqual(build_env["GOARCH"], "amd64")
        self.assertEqual(build_env["CGO_ENABLED"], "1")
        self.assertEqual(build_env["GOPROXY"], "off")

    @unittest.skipUnless(os.name == "posix", "needs an executable shell stub")
    def test_effective_toolchain_target_is_read_and_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub = os.path.join(tmp, "go")
            _write(stub, '#!/bin/sh\nprintf "linux\\namd64\\n"\n')
            os.chmod(stub, 0o755)
            self.assertEqual(build_go_lib._go_target(stub, {}, tmp), ("linux", "amd64"))

            _write(stub, '#!/bin/sh\nprintf "linux\\narm64\\n"\n')
            os.chmod(stub, 0o755)
            with self.assertRaises(RuntimeError) as caught:
                build_go_lib._go_target(stub, {}, tmp)
            self.assertIn("only supports", str(caught.exception))


class SourceTreePackagingGuardTest(unittest.TestCase):
    def test_setup_refuses_to_package_the_source_tree(self):
        if os.path.exists(os.path.join(REPO_ROOT, "requests_go", "_build_info.json")):
            self.skipTest("a build stage left _build_info.json in the source tree")
        completed = subprocess.run(
            [sys.executable, "setup.py", "--version"],
            cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        output = completed.stdout.decode("utf-8", "replace")
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("refusing to package the source tree", output)
        self.assertIn("tools.build_go_lib", output)


class ExistingOutputTest(unittest.TestCase):
    def test_existing_output_is_not_cleared_silently(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "go-src"))
            with self.assertRaises(FileExistsError):
                build_go_lib.build_go_library("unused-go-dir", tmp)


if __name__ == "__main__":
    unittest.main()
