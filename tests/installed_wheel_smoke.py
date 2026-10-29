"""Assert that an *installed* requests_go loads its own bundled library.

Run from a directory outside the source tree, with the wheel installed:

    cd /tmp && python /path/to/repo/tests/installed_wheel_smoke.py

Exits non-zero when the loaded library is not the one shipped inside the
installed package or when its build metadata does not describe the pinned
Linux amd64 kernel.
"""
import json
import os
import sys

import requests_go

EXPECTED_COMMIT = "8ddcf6496005c5cb9acaf3f18d38159b7ef43269"


def main():
    info = requests_go.get_build_info()
    print(json.dumps(info, indent=2, sort_keys=True))

    package_dir = os.path.realpath(os.path.dirname(os.path.abspath(requests_go.__file__)))
    library_path = os.path.realpath(info["library_path"])
    checks = [
        (os.path.dirname(library_path) == os.path.join(
            package_dir, "tls_client", "dependencies"), "library is not bundled in the installed package"),
        (info["library_source"] == "bundled", "library source is not 'bundled'"),
        (info["kernel_metadata"] == "bundled", "kernel metadata is not 'bundled'"),
        (info["kernel"] is not None, "kernel metadata is missing"),
    ]
    if info["kernel"]:
        checks.extend([
            (info["kernel"]["upstream_commit"] == EXPECTED_COMMIT, "unexpected upstream commit"),
            (info["kernel"]["goos"] == "linux", "unexpected GOOS"),
            (info["kernel"]["goarch"] == "amd64", "unexpected GOARCH"),
        ])

    failed = [message for ok, message in checks if not ok]
    for message in failed:
        sys.stderr.write("FAILED: %s\n" % message)
    if failed:
        return 1
    print("installed wheel smoke test OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
