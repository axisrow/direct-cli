import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
PATCH_SCRIPT = ROOT_DIR / "scripts/patch_vendor_imports.py"
VENDOR_DIR = ROOT_DIR / "direct_cli/_vendor/tapi_yandex_direct"


def test_patch_vendor_imports_rewrites_absolute_imports(tmp_path):
    vendor_dir = tmp_path / "tapi_yandex_direct"
    vendor_dir.mkdir()
    module = vendor_dir / "tapi_yandex_direct.py"
    init_file = vendor_dir / "__init__.py"

    module.write_text(
        "\n".join(
            [
                "from tapi_yandex_direct import exceptions",
                "from tapi_yandex_direct.resource_mapping import RESOURCE_MAPPING_V5",
                "",
            ]
        ),
        encoding="utf-8",
    )
    init_file.write_text(
        "from tapi_yandex_direct.tapi_yandex_direct import YandexDirect\n",
        encoding="utf-8",
    )

    subprocess.run(
        [sys.executable, str(PATCH_SCRIPT), str(vendor_dir)],
        check=True,
        cwd=ROOT_DIR,
    )
    first_module = module.read_text(encoding="utf-8")
    first_init = init_file.read_text(encoding="utf-8")

    subprocess.run(
        [sys.executable, str(PATCH_SCRIPT), str(vendor_dir)],
        check=True,
        cwd=ROOT_DIR,
    )

    assert first_module == module.read_text(encoding="utf-8")
    assert first_init == init_file.read_text(encoding="utf-8")
    assert first_module == "\n".join(
        [
            "from . import exceptions",
            "from .resource_mapping import RESOURCE_MAPPING_V5",
            "",
        ]
    )
    assert first_init == "from .tapi_yandex_direct import YandexDirect\n"


def test_patch_vendor_imports_rejects_plain_absolute_import(tmp_path):
    vendor_dir = tmp_path / "tapi_yandex_direct"
    vendor_dir.mkdir()
    module = vendor_dir / "tapi_yandex_direct.py"
    module.write_text("import tapi_yandex_direct\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(PATCH_SCRIPT), str(vendor_dir)],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "unsupported absolute import" in result.stderr


def test_patch_vendor_imports_rejects_multiline_import(tmp_path):
    vendor_dir = tmp_path / "tapi_yandex_direct"
    vendor_dir.mkdir()
    module = vendor_dir / "tapi_yandex_direct.py"
    module.write_text("from tapi_yandex_direct import (\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(PATCH_SCRIPT), str(vendor_dir)],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "multi-line import not supported" in result.stderr
    # File must not be written (atomic patching)
    assert module.read_text(encoding="utf-8") == "from tapi_yandex_direct import (\n"


def test_patch_vendor_imports_rejects_backslash_continuation(tmp_path):
    vendor_dir = tmp_path / "tapi_yandex_direct"
    vendor_dir.mkdir()
    module = vendor_dir / "tapi_yandex_direct.py"
    module.write_text("from tapi_yandex_direct import \\\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(PATCH_SCRIPT), str(vendor_dir)],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "multi-line import not supported" in result.stderr
    # File must not be written (atomic patching)
    assert module.read_text(encoding="utf-8") == "from tapi_yandex_direct import \\\n"


def test_patch_vendor_imports_atomic_on_unsupported_import(tmp_path):
    """Verify no files are written when a later file has an unsupported import."""
    vendor_dir = tmp_path / "tapi_yandex_direct"
    vendor_dir.mkdir()
    good_file = vendor_dir / "good.py"
    bad_file = vendor_dir / "zzz_bad.py"

    good_file.write_text(
        "from tapi_yandex_direct import exceptions\n", encoding="utf-8"
    )
    bad_file.write_text("import tapi_yandex_direct\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(PATCH_SCRIPT), str(vendor_dir)],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    # good.py must remain unpatched (atomic)
    assert good_file.read_text(encoding="utf-8") == (
        "from tapi_yandex_direct import exceptions\n"
    )


def test_vendored_tapi_yandex_direct_uses_relative_imports():
    offenders = []
    for path in VENDOR_DIR.rglob("*.py"):
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            stripped = line.strip()
            if stripped.startswith(
                ("from tapi_yandex_direct", "import tapi_yandex_direct")
            ):
                offenders.append(f"{path.relative_to(ROOT_DIR)}:{line_number}: {line}")

    assert offenders == []
