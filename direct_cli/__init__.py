"""
Direct CLI - Command-line interface for Yandex Direct API
"""

from importlib.metadata import PackageNotFoundError, version

__author__ = "Pavel Maksimov"
__email__ = "vur21@ya.ru"

try:
    __version__ = version("direct-cli")
except PackageNotFoundError:
    __version__ = "unknown"

__all__ = ["__version__", "__author__", "__email__"]
