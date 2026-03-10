#!/usr/bin/env python

from setuptools import setup, find_packages
import os

version = {}
version_file = os.path.join(os.path.dirname(__file__), "direct_cli", "_version.py")
if os.path.exists(version_file):
    with open(version_file) as f:
        exec(f.read(), version)
else:
    version["__version__"] = "0.0.0"

with open("README.md", "r", encoding="utf-8") as fh:
    readme = fh.read()

setup(
    name="direct-cli",
    version=version["__version__"],
    description="Command-line interface for Yandex Direct API",
    long_description=readme,
    long_description_content_type="text/markdown",
    author="Pavel Maksimov",
    author_email="vur21@ya.ru",
    url="https://github.com/pavelmaksimov/direct-cli",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "tapi-yandex-direct>=2021.5.29",
        "click>=8.0.0",
        "python-dotenv>=0.19.0",
        "tabulate>=0.8.0",
        "colorama>=0.4.0",
        "tqdm>=4.60.0",
    ],
    extras_require={
        "dev": [
            "pytest>=6.0",
            "pytest-cov>=2.0",
            "black>=22.0",
            "flake8>=4.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "direct-cli=direct_cli.cli:cli",
        ],
    },
    python_requires=">=3.6",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    keywords="yandex direct cli api advertising",
    license="MIT",
    zip_safe=False,
)
