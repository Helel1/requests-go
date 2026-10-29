"""Build metadata of the Go kernel library that is actually loaded."""

import json
import os

from .__version__ import __version__

BUILD_INFO_FILENAME = "_build_info.json"


def _read_kernel_metadata():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), BUILD_INFO_FILENAME)
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    kernel = data.get("kernel")
    return kernel if isinstance(kernel, dict) else None


def get_build_info():
    """Return the Python version, the loaded library path and kernel metadata.

    The kernel metadata describes the library that was bundled at build time.
    It is reported as unknown when the library is overridden through
    ``REQUESTGO_DEPPATH`` (the bundled metadata cannot identify that file) or
    when the package carries no ``_build_info.json``.
    """
    from .tls_client import client

    metadata = _read_kernel_metadata()
    if client.LIBRARY_SOURCE == "override":
        kernel, status = None, "override-unknown"
    elif metadata is None:
        kernel, status = None, "missing-unknown"
    else:
        kernel, status = metadata, "bundled"

    return {
        "python_version": __version__,
        "library_path": client.LIBRARY_PATH,
        "library_source": client.LIBRARY_SOURCE,
        "kernel": kernel,
        "kernel_metadata": status,
    }
