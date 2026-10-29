"""Build the Linux amd64 Go kernel library that ships inside ``requests_go``.

Primary interface is the importable function ``build_go_library``::

    from tools.build_go_lib import build_go_library
    paths = build_go_library(
        go_source_dir="../requests-go-go-source/wangluozhe-requests",
        output_dir="dist/maintenance-linux-amd64",
    )
    print(paths["wheel"])

The Go repository is only read. ``git archive <commit>`` extracts the pinned
commit of the Go source fork into ``<output_dir>/go-src`` and only that
extraction is compiled. The fork already carries the kernel fixes as commits,
so no patch is applied on top. Nothing is written back to the Go repository and
no existing output directory is cleared: an existing ``go-src`` / ``stage``
makes the build fail unless the caller picks another output directory.

Also usable as ``python -m tools.build_go_lib <go_source_dir> <output_dir>``.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The kernel is built from this project's own Go source fork, which is a fork of
# wangluozhe/requests and keeps that module path. The ``upstream_*`` names and
# the matching build-metadata keys describe the Go source the kernel was built
# from, not the original author's repository; the value is a full commit SHA so
# a rebuild is reproducible.
UPSTREAM_REPO = "https://github.com/Helel1/requests"
UPSTREAM_MODULE = "github.com/wangluozhe/requests"
UPSTREAM_COMMIT = "8ddcf6496005c5cb9acaf3f18d38159b7ef43269"

# The fork carries the maintenance fixes as commits, so nothing is applied on
# top of the extracted source. ``patches/go-fix-46ef52b.diff`` is retired and
# kept only as the historical record of what UPSTREAM_COMMIT contains.
PATCH_PATHS = ()

# This maintenance release is only defined for one target: the bundled library
# name, the wheel tag and the metadata all describe Linux amd64. Anything else
# is rejected instead of producing a mislabelled artifact.
SUPPORTED_GOOS = "linux"
SUPPORTED_GOARCH = "amd64"
LIBRARY_NAME = "requests-go-amd64.so"
PROBE_SYMBOL_PREFIX = b"probe_"

# Allowlist of what the build stage receives. Everything else in the
# repository (VCS data, local output directories, scratch reports, archives,
# credentials, prebuilt libraries of other platforms) is never copied.
_STAGE_TOP_FILES = (
    "setup.py",
    "pyproject.toml",
    "MANIFEST.in",
    "LICENSE",
    "LICENSE-GPL-3.0",
    "THIRD_PARTY_NOTICES.md",
    "README.md",
    "CHANGELOG.md",
)
_STAGE_DOC_DIRS = ("tools", "patches", "tests", "docs")
_STAGE_DOC_SUFFIXES = (".py", ".diff", ".go", ".md")
_STAGE_SKIP_NAMES = {"__pycache__", "_build_info.json"}
_STAGE_SKIP_SUFFIXES = (".pyc", ".pyo", ".so", ".dll", ".dylib")


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(args, cwd=None, env=None):
    completed = subprocess.run(
        args, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    output = completed.stdout.decode("utf-8", "replace")
    if completed.returncode != 0:
        raise RuntimeError(
            "command failed (exit %d): %s\n%s"
            % (completed.returncode, " ".join(args), output)
        )
    return output


def _git_archive(go_source_dir, commit, destination, git_binary="git"):
    archive = os.path.join(tempfile.mkdtemp(prefix="rg-go-archive-"), "src.tar")
    try:
        with open(archive, "wb") as handle:
            subprocess.run(
                [git_binary, "-C", go_source_dir, "archive", commit],
                stdout=handle, check=True,
            )
        with tarfile.open(archive) as tar:
            tar.extractall(destination)
    finally:
        shutil.rmtree(os.path.dirname(archive), ignore_errors=True)


def _apply_patches(source_dir, patch_files, git_binary="git"):
    applied = []
    for patch in patch_files:
        _run([git_binary, "apply", "--whitespace=nowarn", patch], cwd=source_dir)
        applied.append({"path": patch, "sha256": _sha256(patch)})
    return applied


def _build_library(go_source, output_dir, go_binary, env):
    library = os.path.join(output_dir, LIBRARY_NAME)
    _run(
        [go_binary, "build", "-trimpath", "-buildmode=c-shared", "-o", library, "export.go"],
        cwd=os.path.join(go_source, "libs_dist"),
        env=env,
    )
    return library


def _assert_no_probe_symbols(library):
    nm = shutil.which("nm")
    if nm is None:
        return "nm not available; probe symbol check skipped"
    output = subprocess.run(
        [nm, "-D", "--defined-only", library],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True,
    ).stdout
    if PROBE_SYMBOL_PREFIX in output:
        raise RuntimeError(
            "production library exports probe_ symbols; it was built with -tags probe"
        )
    return "no probe_ symbols in production library"


def _go_version(go_binary, env):
    return _run([go_binary, "env", "GOVERSION"], env=env).strip()


def _build_env(env):
    """Return the Go build environment, rejecting any other target.

    The library name, the wheel tag and the metadata all describe Linux amd64,
    so a caller cannot redirect the build through ``env`` without producing a
    mislabelled artifact.
    """
    supported = {
        "GOOS": SUPPORTED_GOOS,
        "GOARCH": SUPPORTED_GOARCH,
        "CGO_ENABLED": "1",
    }
    for name, value in (env or {}).items():
        if name in supported and str(value) != supported[name]:
            raise ValueError(
                "this build only supports %s=%r, got %s=%r"
                % (name, supported[name], name, value)
            )
    build_env = dict(os.environ)
    build_env.update(supported)
    build_env.update(env or {})
    return build_env


def _go_target(go_binary, env, cwd):
    """Read the effective GOOS/GOARCH from the toolchain and verify them."""
    output = _run([go_binary, "env", "GOOS", "GOARCH"], cwd=cwd, env=env).split()
    if len(output) != 2:
        raise RuntimeError("unexpected `go env GOOS GOARCH` output: %r" % output)
    goos, goarch = output
    if (goos, goarch) != (SUPPORTED_GOOS, SUPPORTED_GOARCH):
        raise RuntimeError(
            "go build would target %s/%s, but this release only supports %s/%s"
            % (goos, goarch, SUPPORTED_GOOS, SUPPORTED_GOARCH)
        )
    return goos, goarch


def _snapshot_source(go_source, commit, patch_files, output_dir):
    short = commit[:7]
    snapshot = os.path.join(output_dir, "requests-go-src-%s.tar.gz" % short)
    with tarfile.open(snapshot, "w:gz") as tar:
        tar.add(go_source, arcname="requests-go-%s" % short)
        for patch in patch_files:
            tar.add(patch, arcname="requests-go-%s/maintenance-patches/%s"
                    % (short, os.path.basename(patch)))
    return snapshot


def _copy_stage_tree(source, destination, suffixes=None):
    if not os.path.isdir(source):
        raise FileNotFoundError("build stage requires directory %s" % source)
    for root, dirnames, filenames in os.walk(source):
        dirnames[:] = sorted(name for name in dirnames if name not in _STAGE_SKIP_NAMES)
        target = os.path.join(destination, os.path.relpath(root, source))
        os.makedirs(target, exist_ok=True)
        for name in sorted(filenames):
            if name in _STAGE_SKIP_NAMES or name.endswith(_STAGE_SKIP_SUFFIXES):
                continue
            if suffixes is not None and not name.endswith(suffixes):
                continue
            shutil.copy2(os.path.join(root, name), os.path.join(target, name))


def _stage_python_package(stage_dir, library, kernel_metadata, source_root=None):
    """Copy the Python package into ``stage_dir`` with only the new library.

    Only an allowlist is copied: the ``requests_go`` package, the build entry
    point, patches, tests, docs and packaging metadata. Local output
    directories, scratch reports, archives and prebuilt libraries of other
    platforms never reach the stage, so an ``output_dir`` inside the repository
    cannot copy a previous build into itself.
    """
    source_root = source_root or REPO_ROOT
    os.makedirs(stage_dir, exist_ok=True)

    for name in _STAGE_TOP_FILES:
        source = os.path.join(source_root, name)
        if not os.path.isfile(source):
            raise FileNotFoundError("build stage requires %s in %s" % (name, source_root))
        shutil.copy2(source, os.path.join(stage_dir, name))

    for name in _STAGE_DOC_DIRS:
        _copy_stage_tree(
            os.path.join(source_root, name), os.path.join(stage_dir, name), _STAGE_DOC_SUFFIXES
        )

    _copy_stage_tree(
        os.path.join(source_root, "requests_go"), os.path.join(stage_dir, "requests_go")
    )

    dependencies = os.path.join(stage_dir, "requests_go", "tls_client", "dependencies")
    os.makedirs(dependencies, exist_ok=True)
    shutil.copy2(library, os.path.join(dependencies, LIBRARY_NAME))
    with open(os.path.join(stage_dir, "requests_go", "_build_info.json"), "w", encoding="utf-8") as handle:
        json.dump(kernel_metadata, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return stage_dir


def _build_distributions(stage_dir, dist_dir, python):
    """Build the wheel and the sdist from the stage (never from the source tree)."""
    os.makedirs(dist_dir, exist_ok=True)
    has_build = subprocess.run(
        [python, "-c", "import build"], cwd=stage_dir,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode == 0
    if has_build:
        _run([python, "-m", "build", "--no-isolation", "--outdir", dist_dir], cwd=stage_dir)
    else:
        _run([python, "setup.py", "sdist", "--dist-dir", dist_dir,
              "bdist_wheel", "--dist-dir", dist_dir], cwd=stage_dir)
    artifacts = sorted(os.listdir(dist_dir))
    wheels = [os.path.join(dist_dir, name) for name in artifacts if name.endswith(".whl")]
    sdists = [os.path.join(dist_dir, name) for name in artifacts if name.endswith(".tar.gz")]
    if len(wheels) != 1 or len(sdists) != 1:
        raise RuntimeError(
            "expected one wheel and one sdist in %s, found %r" % (dist_dir, artifacts)
        )
    return wheels[0], sdists[0]


def build_go_library(
    go_source_dir,
    output_dir,
    go_binary="go",
    go_ref=UPSTREAM_COMMIT,
    patch_paths=PATCH_PATHS,
    env=None,
    python=None,
    build_dist=True,
):
    """Build the kernel library and the staged Python package.

    Returns a dict of absolute paths and build metadata. Raises instead of
    overwriting an existing build in ``output_dir``. The target is fixed to
    Linux amd64; ``env`` may carry Go tool settings (``GOPROXY``, ``GOPATH``,
    ``GOMODCACHE``, ``GOCACHE``, ``GOFLAGS``) but not a different GOOS/GOARCH.
    """
    python = python or sys.executable
    build_env = _build_env(env)
    go_source_dir = os.path.abspath(go_source_dir)
    output_dir = os.path.abspath(output_dir)
    patch_files = [
        path if os.path.isabs(path) else os.path.join(REPO_ROOT, path)
        for path in patch_paths
    ]

    go_source = os.path.join(output_dir, "go-src")
    stage_dir = os.path.join(output_dir, "stage")
    dist_dir = os.path.join(output_dir, "dist")
    for existing in (go_source, stage_dir):
        if os.path.exists(existing):
            raise FileExistsError(
                "%s already exists; pick a fresh output directory instead of "
                "reusing a previous build" % existing
            )
    os.makedirs(output_dir, exist_ok=True)

    commit = _run(["git", "-C", go_source_dir, "rev-parse", go_ref + "^{commit}"]).strip()
    if len(commit) != 40:
        raise RuntimeError("could not resolve %r to a commit in %s" % (go_ref, go_source_dir))

    _git_archive(go_source_dir, commit, go_source)
    applied_patches = _apply_patches(go_source, patch_files)

    goos, goarch = _go_target(
        go_binary, build_env, os.path.join(go_source, "libs_dist")
    )

    library = _build_library(go_source, output_dir, go_binary, build_env)
    probe_check = _assert_no_probe_symbols(library)
    go_version = _go_version(go_binary, build_env)

    kernel_metadata = {
        "python_version": _read_python_version(),
        "kernel": {
            "module": UPSTREAM_MODULE,
            "upstream_repo": UPSTREAM_REPO,
            "upstream_commit": commit,
            "patches": [
                {"path": os.path.relpath(patch["path"], REPO_ROOT), "sha256": patch["sha256"]}
                for patch in applied_patches
            ],
            "go_version": go_version,
            "goos": goos,
            "goarch": goarch,
            "trimpath": True,
            "library": LIBRARY_NAME,
            "library_sha256": _sha256(library),
            "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
    }

    build_info = os.path.join(output_dir, "build_info.json")
    with open(build_info, "w", encoding="utf-8") as handle:
        json.dump(kernel_metadata, handle, indent=2, sort_keys=True)
        handle.write("\n")

    snapshot = _snapshot_source(go_source, commit, patch_files, output_dir)
    _stage_python_package(stage_dir, library, kernel_metadata)

    wheel = sdist = None
    if build_dist:
        wheel, sdist = _build_distributions(stage_dir, dist_dir, python)

    return {
        "output_dir": output_dir,
        "go_source": go_source,
        "library": library,
        "source_tar": snapshot,
        "build_info": build_info,
        "stage_dir": stage_dir,
        "dist_dir": dist_dir if build_dist else None,
        "wheel": wheel,
        "sdist": sdist,
        "commit": commit,
        "patches": [patch["path"] for patch in applied_patches],
        "go_version": go_version,
        "probe_check": probe_check,
    }


def _read_python_version():
    namespace = {}
    with open(os.path.join(REPO_ROOT, "requests_go", "__version__.py"), encoding="utf-8") as handle:
        exec(handle.read(), namespace)
    return namespace["__version__"]


def main(argv):
    if len(argv) != 3:
        sys.stderr.write(
            "usage: python -m tools.build_go_lib <go_source_dir> <output_dir>\n"
            "environment: GO_BINARY, GOPROXY, GOPATH, GOMODCACHE, GOCACHE, GOFLAGS, GOPRIVATE\n"
        )
        return 2
    env = {}
    for name in ("GOPROXY", "GOPATH", "GOMODCACHE", "GOCACHE", "GOFLAGS", "GOPRIVATE"):
        if os.environ.get(name):
            env[name] = os.environ[name]
    result = build_go_library(
        argv[1],
        argv[2],
        go_binary=os.environ.get("GO_BINARY", "go"),
        env=env,
    )
    for key in ("library", "source_tar", "build_info", "wheel", "sdist", "probe_check"):
        print("%s: %s" % (key, result[key]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
