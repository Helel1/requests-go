import ctypes
import os
import sys
from platform import machine

# Architecture suffix of the bundled c-shared library per machine() value.
_SO_SUFFIX = {
    "x86_64": "-amd64.so",
    "amd64": "-amd64.so",
    "aarch64": "-arm64.so",
    "arm64": "-arm64.so",
}
_DYLIB_SUFFIX = {
    "x86_64": "-x86.dylib",
    "amd64": "-x86.dylib",
    "arm64": "-arm64.dylib",
    "aarch64": "-arm64.dylib",
}

DEPENDENCIES_DIR = os.path.join(os.path.abspath(os.path.dirname(__file__)), "dependencies")


def select_library_name(platform_name, machine_name, pointer_size):
    """Return the bundled library file name for a platform/machine pair.

    Only the platforms and architectures upstream actually ships are accepted;
    any other OS, machine or pointer size raises instead of guessing a library
    name (for example, Windows arm64 must not receive the x86_64 DLL).
    """
    machine_name = (machine_name or "").lower()
    if platform_name == "darwin":
        if machine_name in _DYLIB_SUFFIX:
            return "requests-go" + _DYLIB_SUFFIX[machine_name]
    elif platform_name in ("win32", "cygwin"):
        if pointer_size == 8 and machine_name in ("amd64", "x86_64"):
            return "requests-go-win64.dll"
    elif platform_name.startswith("linux"):
        if machine_name in _SO_SUFFIX:
            return "requests-go" + _SO_SUFFIX[machine_name]
    raise OSError(
        "requests_go: no bundled Go library for platform=%r machine=%r "
        "(supported: Linux x86_64/aarch64, macOS x86_64/arm64, 64-bit Windows amd64); "
        "set REQUESTGO_DEPPATH to a c-shared library built for this platform"
        % (platform_name, machine_name)
    )


_override = os.environ.get("REQUESTGO_DEPPATH")
if _override:
    LIBRARY_SOURCE = "override"
    LIBRARY_PATH = os.path.abspath(_override)
else:
    LIBRARY_SOURCE = "bundled"
    LIBRARY_PATH = os.path.join(
        DEPENDENCIES_DIR,
        select_library_name(sys.platform, machine(), ctypes.sizeof(ctypes.c_voidp)),
    )

library = ctypes.cdll.LoadLibrary(LIBRARY_PATH)

request = library.request
request.argtypes = [ctypes.c_char_p]
request.restype = ctypes.c_char_p

freeMemory = library.freeMemory
freeMemory.argtypes = [ctypes.c_char_p]

freeSession = library.freeSession
freeSession.argtypes = [ctypes.c_char_p]

# Stream API
stream_request = library.stream_request
stream_request.argtypes = [ctypes.c_char_p]
stream_request.restype = ctypes.c_char_p

stream_read = library.stream_read
stream_read.argtypes = [ctypes.c_char_p, ctypes.c_int]
stream_read.restype = ctypes.c_char_p

stream_close = library.stream_close
stream_close.argtypes = [ctypes.c_char_p]
