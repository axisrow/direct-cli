"""
Direct CLI - Command-line interface for Yandex Direct API
"""

__author__ = "Pavel Maksimov"
__email__ = "vur21@ya.ru"

# Version will be set by setuptools_scm
try:
    from ._version import version as __version__
except ImportError:
    __version__ = "unknown"

__all__ = ["__version__", "__author__", "__email__"]
