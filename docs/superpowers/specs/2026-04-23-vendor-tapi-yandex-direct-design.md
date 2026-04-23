# Vendor tapi-yandex-direct into direct_cli/_vendor/

## Context

PyPI rejects packages with direct git dependencies (`package @ git+https://...`).
`direct-cli` depends on a fork of `tapi-yandex-direct` hosted at
`github.com/axisrow/tapi-yandex-direct`, blocking publication to PyPI.

Solution: vendor the fork's source code directly into the package under
`direct_cli/_vendor/tapi_yandex_direct/`. An automated script checks for
upstream version changes before each release and updates the vendored copy.

## File structure

```
direct_cli/
  _vendor/
    __init__.py                    # empty package marker
    tapi_yandex_direct/
      __init__.py                  # contains __version__ — used by update script
      tapi_yandex_direct.py
      resource_mapping.py
      exceptions.py

scripts/
  update_vendor.sh                 # new: checks and updates vendored copy
  release_pypi.sh                  # modified: calls update_vendor.sh at start
```

## scripts/update_vendor.sh

Logic:
1. Read current vendored version from
   `direct_cli/_vendor/tapi_yandex_direct/__init__.py` (grep `__version__`)
2. `git clone --depth 1 https://github.com/axisrow/tapi-yandex-direct.git`
   into a temp dir, read `__version__` from cloned copy
3. If versions match → print "Vendor up to date (X.Y.Z)" → exit 0
4. If versions differ → copy 4 files into `direct_cli/_vendor/tapi_yandex_direct/`
5. `git add` + `git commit "chore(vendor): update tapi-yandex-direct to X.Y.Z"`
6. Clean up temp dir

## pyproject.toml changes

Remove:
```toml
"tapi-yandex-direct @ git+https://github.com/axisrow/tapi-yandex-direct.git",
```

Add (transitive deps of the fork, needed at runtime):
```toml
"orjson",
"requests",
"tapi-wrapper2",
```

`[tool.setuptools.packages.find]` — no change needed, `direct_cli*` already
captures `direct_cli._vendor`.

## Import changes (2 lines)

`direct_cli/api.py:7`:
```python
from direct_cli._vendor.tapi_yandex_direct import YandexDirect
```

`tests/test_transport_contract.py:4`:
```python
from direct_cli._vendor.tapi_yandex_direct import YandexDirect
```

## release_pypi.sh integration

After loading `.env`, before cleaning artifacts:
```bash
echo "Checking vendor dependencies..."
bash "${ROOT_DIR}/scripts/update_vendor.sh"
```

## Verification

1. `bash scripts/update_vendor.sh` — should print "up to date" or commit an update
2. `pytest tests/ -v --ignore=tests/test_integration.py` — all unit tests pass
3. `bash scripts/release_pypi.sh all` — builds and uploads successfully to both
   TestPyPI and PyPI without the "Can't have direct dependency" error
4. `pip install direct-cli==0.2.9` installs and `direct --help` works
