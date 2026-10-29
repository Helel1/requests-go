#!/usr/bin/env python
"""Packaging entry point.

This package ships a compiled Go kernel library, so it must be built from a
build stage produced by ``tools/build_go_lib.py`` (which writes
``requests_go/_build_info.json`` and the matching library). Packaging the
source tree directly would pick up the stale prebuilt binaries that are
tracked in git for legacy releases, which is refused on purpose.
"""
import os
import sys

from setuptools import Distribution, setup, find_packages

here = os.path.abspath(os.path.dirname(__file__))

BUILD_INFO = os.path.join(here, "requests_go", "_build_info.json")
if not os.path.exists(BUILD_INFO):
    sys.exit(
        "requests_go: refusing to package the source tree directly.\n"
        "The maintenance build must come from a build stage that carries the\n"
        "freshly built Go kernel library and its metadata. Run:\n"
        "    python -m tools.build_go_lib <go_source_dir> <output_dir>\n"
        "and build the wheel/sdist from <output_dir>/stage."
    )

about = {}
with open(os.path.join(here, "requests_go", "__version__.py"), encoding="utf-8") as f:
    exec(f.read(), about)

with open(os.path.join(here, "README.md"), encoding="utf-8") as f:
    readme = f.read()

try:
    from setuptools.command.bdist_wheel import bdist_wheel as _bdist_wheel
except ImportError:  # setuptools < 70.1 with the separate wheel package
    from wheel.bdist_wheel import bdist_wheel as _bdist_wheel


class BinaryDistribution(Distribution):
    """The code is pure Python but the package is not platform independent.

    It carries a Linux amd64 c-shared library, so its files belong in platlib
    (``Root-Is-Purelib: false``) instead of ``.data/purelib``.
    """

    def has_ext_modules(self):
        return True


class bdist_wheel_linux_x86_64(_bdist_wheel):
    """Tag the wheel for the platform whose library it carries."""

    def get_tag(self):
        return "py3", "none", "linux_x86_64"


setup(
    name=about["__title__"],
    version=about["__version__"],
    author=about["__author__"],
    description=about["__description__"],
    license="MIT (Python wrapper) + GPL-3.0-only (bundled Go kernel)",
    license_files=["LICENSE", "LICENSE-GPL-3.0", "THIRD_PARTY_NOTICES.md"],
    author_email=about["__author_email__"],
    url=about["__url__"],
    python_requires=">=3.7",
    long_description=readme,
    long_description_content_type="text/markdown",
    packages=find_packages(),
    package_data={
        "requests_go": ["_build_info.json"],
        "requests_go.tls_client.dependencies": ["*.so", "*.dll", "*.dylib"],
    },
    classifiers=[
        "Environment :: Web Environment",
        "Intended Audience :: Developers",
        "Natural Language :: English",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: Software Development :: Libraries",
    ],
    install_requires=[
        "requests>=2.28.1",
        "six>=1.16.0",
        "PySocks>=1.7.1"
    ],
    distclass=BinaryDistribution,
    cmdclass={"bdist_wheel": bdist_wheel_linux_x86_64},
)
