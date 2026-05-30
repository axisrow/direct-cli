import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
PATCH_SCRIPT = ROOT_DIR / "scripts/patch_vendor_imports.py"
VENDOR_DIR = ROOT_DIR / "direct_cli/_vendor/tapi_yandex_direct"


def _load_patch_module():
    """Import scripts/patch_vendor_imports.py by path (no import-time effects)."""
    spec = importlib.util.spec_from_file_location("patch_vendor_imports", PATCH_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def test_patch_vendor_imports_rewrites_parenthesized_multiline_imports(tmp_path):
    vendor_dir = tmp_path / "tapi_yandex_direct"
    subpackage = vendor_dir / "v4"
    subpackage.mkdir(parents=True)
    module = subpackage / "adapter.py"
    module.write_text(
        "\n".join(
            [
                "from tapi_yandex_direct import (",
                "    exceptions,",
                ")",
                "from tapi_yandex_direct.v4.resource_mapping import (",
                "    RESOURCE_MAPPING_V4_LIVE,",
                "    SUPPORTED_V4_METHODS,",
                ")",
                "",
            ]
        ),
        encoding="utf-8",
    )

    subprocess.run(
        [sys.executable, str(PATCH_SCRIPT), str(vendor_dir)],
        check=True,
        cwd=ROOT_DIR,
    )

    assert module.read_text(encoding="utf-8") == "\n".join(
        [
            "from .. import (",
            "    exceptions,",
            ")",
            "from .resource_mapping import (",
            "    RESOURCE_MAPPING_V4_LIVE,",
            "    SUPPORTED_V4_METHODS,",
            ")",
            "",
        ]
    )


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
    assert "backslash import continuation not supported" in result.stderr
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


def test_vendored_executor_stub_declares_timeout_kwarg():
    """The checked-in stub must keep ``timeout`` on the client executor's
    ``get``/``post``, or mypy rejects ``auth._resolve_client_login_via_api``
    (it passes ``timeout=`` on the credential-resolution hot path). The
    upstream fork drops this kwarg, so ``update_vendor.sh`` would wipe it on
    every bump if ``patch_vendor_imports.py`` did not re-apply it — see the
    #480 follow-up. An ``ast`` check (not a substring grep) stays robust to
    black reflowing the one-line signature back to multi-line.
    """
    stub = (VENDOR_DIR / "tapi_yandex_direct.pyi").read_text(encoding="utf-8")
    tree = ast.parse(stub)
    cls = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and node.name == "YandexDirectClientExecutor"
    )
    for method_name in ("get", "post"):
        func = next(
            node
            for node in cls.body
            if isinstance(node, ast.FunctionDef) and node.name == method_name
        )
        kwonly = {arg.arg for arg in func.args.kwonlyargs}
        assert "timeout" in kwonly, (
            f"{method_name} stub lost the timeout kwarg — vendor patch not "
            "re-applied (see scripts/patch_vendor_imports.py)"
        )


def test_patch_stub_text_adds_timeout_idempotently():
    """``_patch_stub_text`` adds ``timeout`` to the client executor exactly
    once, leaves the report executor alone, and is a no-op on a second pass.
    """
    pvi = _load_patch_module()
    upstream = (
        "class YandexDirectClientExecutor:\n"
        "    def get(\n"
        "        self, *, params: dict = None, data: dict = None, "
        "headers: dict = None\n"
        "    ) -> X:\n"
        '        """\n'
        "        Send HTTP 'GET' request.\n"
        "\n"
        "        :param params: q\n"
        "        :param data: d\n"
        '        """\n'
        "    def post(\n"
        "        self, *, params: dict = None, data: dict = None, "
        "headers: dict = None\n"
        "    ) -> X:\n"
        '        """\n'
        "        Send HTTP 'POST' request.\n"
        "\n"
        "        :param params: q\n"
        "        :param data: d\n"
        '        """\n'
        "\n"
        "class YandexDirectClientReportExecutor:\n"
        "    def post(\n"
        "        self, *, params: dict = None, data: dict = None, "
        "headers: dict = None\n"
        "    ) -> Y:\n"
        '        """\n'
        "        Send HTTP 'POST' request.\n"
        "\n"
        "        :param params: q\n"
        "        :param data: d\n"
        '        """\n'
    )

    first = pvi._patch_stub_text(upstream)

    # Both client-executor methods gain the kwarg and exactly one doc line each.
    assert first.count("timeout: float = None") == 2
    assert first.count(":param timeout:") == 2

    # The report executor is out of scope and must stay untouched.
    report_block = first.split("class YandexDirectClientReportExecutor", 1)[1]
    assert "timeout" not in report_block

    # Running again on the patched text is a byte-for-byte no-op.
    assert pvi._patch_stub_text(first) == first
