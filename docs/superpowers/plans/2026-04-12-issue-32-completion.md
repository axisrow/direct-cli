# Issue #32 Completion: WSDL Coverage & Known Gaps

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Завершить issue #32 — реализовать модуль `advideos`, исправить payload-баг `BidModifiers.add` (DemographicsAdjustments plural), и добавить скрипт обновления WSDL-кэша.

**Architecture:** Три независимых улучшения: (1) новый CLI-модуль `advideos` с командами `get`/`add`, (2) исправление поля в `bidmodifiers add` — `DemographicsAdjustment` (singular) → `DemographicsAdjustments` (plural array), (3) скрипт `scripts/refresh_wsdl_cache.py` для обновления 27 кэшированных XML. После каждого исправления обновляются `wsdl_coverage.py` (KNOWN_MISSING_SERVICES/KNOWN_MISSING_METHODS) и `test_comprehensive.py` (EXPECTED_COMMANDS).

**Tech Stack:** Python, Click, xml.etree.ElementTree, requests, pytest, click.testing.CliRunner

---

## Файлы затрагиваемые планом

| Действие | Файл |
|---|---|
| Создать | `direct_cli/commands/advideos.py` |
| Создать | `scripts/refresh_wsdl_cache.py` |
| Изменить | `direct_cli/cli.py` (импорт + регистрация advideos) |
| Изменить | `direct_cli/wsdl_coverage.py` (убрать advideos из KNOWN_MISSING_SERVICES, добавить в CLI_TO_API_SERVICE) |
| Изменить | `tests/test_comprehensive.py` (добавить "advideos" в EXPECTED_COMMANDS) |
| Изменить | `tests/test_dry_run.py` (тест payload advideos add) |
| Изменить | `tests/test_api_coverage.py` (убрать Demographics из KNOWN_MISSING_METHODS если нужно) |
| Изменить | `direct_cli/commands/bidmodifiers.py` (исправить DemographicsAdjustments) |

---

## Task 1: Реализовать модуль `advideos`

WSDL (`tests/wsdl_cache/advideos.xml`) объявляет два метода: `get` и `add`.
- `get` принимает `SelectionCriteria: {Ids: [string]}` и `FieldNames: [AdVideoFieldEnum]` (возможные значения: `Id`, `Status`)
- `add` принимает список `AdVideos: [{Url?, VideoData?, Name?}]`

**Files:**
- Create: `direct_cli/commands/advideos.py`
- Modify: `direct_cli/cli.py`
- Modify: `tests/test_comprehensive.py`
- Modify: `direct_cli/wsdl_coverage.py`
- Test: `tests/test_dry_run.py`

- [ ] **Step 1: Написать failing тест для advideos add dry-run**

Добавить в конец `tests/test_dry_run.py`:

```python
class TestAdvideosDryRun:
    def test_add_by_url(self):
        body = _dry_run(
            "advideos", "add",
            "--url", "https://example.com/video.mp4",
            "--name", "Test Video",
        )
        assert body["method"] == "add"
        item = body["params"]["AdVideos"][0]
        assert item["Url"] == "https://example.com/video.mp4"
        assert item["Name"] == "Test Video"
        assert "Type" not in item

    def test_add_requires_url_or_data(self):
        from click.testing import CliRunner
        from direct_cli.cli import cli
        result = CliRunner().invoke(cli, ["advideos", "add", "--dry-run"])
        assert result.exit_code != 0
```

- [ ] **Step 2: Запустить тест и убедиться что FAIL**

```bash
.venv/bin/pytest tests/test_dry_run.py::TestAdvideosDryRun -v
```

Ожидается: `FAILED` — команда `advideos` не существует.

- [ ] **Step 3: Создать `direct_cli/commands/advideos.py`**

```python
"""
AdVideos commands
"""

import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import parse_ids


@click.group()
def advideos():
    """Manage ad videos"""


@advideos.command()
@click.option("--ids", help="Comma-separated video IDs")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.pass_context
def get(ctx, ids, limit, fetch_all, output_format, output):
    """Get ad videos"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        criteria = {}
        if ids:
            criteria["Ids"] = parse_ids(ids)

        params = {
            "SelectionCriteria": criteria,
            "FieldNames": ["Id", "Status"],
        }

        if limit:
            params["Page"] = {"Limit": limit}

        body = {"method": "get", "params": params}

        result = client.advideos().post(data=body)

        if fetch_all:
            items = []
            for item in result().iter_items():
                items.append(item)
            format_output(items, output_format, output)
        else:
            data = result().extract()
            format_output(data, output_format, output)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@advideos.command()
@click.option("--url", help="Video URL (mutually exclusive with --video-data)")
@click.option("--video-data", help="Base64-encoded video binary (mutually exclusive with --url)")
@click.option("--name", help="Video name")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def add(ctx, url, video_data, name, dry_run):
    """Add a new ad video (by URL or binary data)"""
    try:
        if not url and not video_data:
            raise click.UsageError("Either --url or --video-data is required.")
        if url and video_data:
            raise click.UsageError("Use either --url or --video-data, not both.")

        item = {}
        if url:
            item["Url"] = url
        if video_data:
            item["VideoData"] = video_data
        if name:
            item["Name"] = name

        body = {"method": "add", "params": {"AdVideos": [item]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.advideos().post(data=body)
        format_output(result().extract(), "json", None)

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


advideos.add_command(get, name="list")
```

- [ ] **Step 4: Зарегистрировать в `direct_cli/cli.py`**

Добавить импорт после строки `from .commands.dynamicads import dynamicads`:

```python
from .commands.advideos import advideos
```

Добавить регистрацию после `cli.add_command(dynamicads)`:

```python
cli.add_command(advideos)
```

- [ ] **Step 5: Обновить `tests/test_comprehensive.py`**

Найти список `EXPECTED_COMMANDS` и добавить `"advideos"` (в алфавитном порядке, перед `"adextensions"` нет — advideos идёт после adimages):

```python
# Было:
        "adimages",
        "adextensions",
# Стало:
        "adimages",
        "advideos",
        "adextensions",
```

- [ ] **Step 6: Обновить `direct_cli/wsdl_coverage.py`**

В `CLI_TO_API_SERVICE` добавить запись (после `"adimages": "adimages"`):

```python
    "advideos": "advideos",
```

В `KNOWN_MISSING_SERVICES` убрать `"advideos"`:

```python
# Было:
KNOWN_MISSING_SERVICES = {"advideos"}
# Стало:
KNOWN_MISSING_SERVICES = set()
```

- [ ] **Step 7: Запустить тесты и проверить что всё проходит**

```bash
.venv/bin/pytest tests/test_dry_run.py::TestAdvideosDryRun tests/test_comprehensive.py tests/test_api_coverage.py -v
```

Ожидается: все PASS.

- [ ] **Step 8: Запустить полный unit-suite**

```bash
.venv/bin/pytest -m "not integration and not integration_write" -q
```

Ожидается: все PASS, количество тестов увеличилось на 2.

- [ ] **Step 9: Commit**

```bash
git add direct_cli/commands/advideos.py direct_cli/cli.py tests/test_dry_run.py tests/test_comprehensive.py direct_cli/wsdl_coverage.py
git commit -m "feat: implement advideos command (get/add) — closes KNOWN_MISSING_SERVICES"
```

---

## Task 2: Исправить payload-баги `BidModifiers.add` — plural-поля по WSDL

Issue #32 зафиксировал баг с `DemographicsAdjustment` → `DemographicsAdjustments`. Проверка WSDL `BidModifierAddItem` показывает, что plural-форму имеют пять полей:

| CLI --type | Текущее (неверное) | Правильное (по WSDL) |
|---|---|---|
| `DEMOGRAPHICS_ADJUSTMENT` | `DemographicsAdjustment` | `DemographicsAdjustments` |
| `RETARGETING_ADJUSTMENT` | `RetargetingAdjustment` | `RetargetingAdjustments` |
| `REGIONAL_ADJUSTMENT` | `RegionalAdjustment` | `RegionalAdjustments` |
| `SERP_LAYOUT_ADJUSTMENT` | `SerpLayoutAdjustment` | `SerpLayoutAdjustments` |
| `INCOME_GRADE_ADJUSTMENT` | `IncomeGradeAdjustment` | `IncomeGradeAdjustments` |

Одиночные (singular) остаются: `MobileAdjustment`, `TabletAdjustment`, `DesktopAdjustment`, `DesktopOnlyAdjustment`, `VideoAdjustment`, `SmartAdAdjustment`, `AdGroupAdjustment`.

Проверка по WSDL (`tests/wsdl_cache/bidmodifiers.xml`): тип `BidModifierAddItem`.

**Files:**
- Modify: `direct_cli/commands/bidmodifiers.py`
- Modify: `tests/test_dry_run.py`

- [ ] **Step 1: Проверить WSDL и убедиться что plural правильный**

```bash
python3 -c "
import xml.etree.ElementTree as ET
from pathlib import Path
xml = Path('tests/wsdl_cache/bidmodifiers.xml').read_text()
root = ET.fromstring(xml)
ns = {'xs': 'http://www.w3.org/2001/XMLSchema'}
for el in root.findall('.//xs:element', ns):
    name = el.get('name', '')
    if 'emographic' in name:
        print(name, el.attrib)
"
```

Ожидается: найти `DemographicsAdjustments` с `maxOccurs`.

- [ ] **Step 2: Написать failing тесты**

Добавить в `tests/test_dry_run.py` новый класс (или в существующий `TestBidModifiersDryRun` если есть):

```python
class TestBidModifiersAddPluralFields:
    """WSDL BidModifierAddItem uses plural array fields for 5 adjustment types."""

    def test_demographics_plural(self):
        body = _dry_run(
            "bidmodifiers", "add",
            "--campaign-id", "123",
            "--type", "DEMOGRAPHICS_ADJUSTMENT",
            "--value", "150",
            "--json", '{"Gender": "GENDER_MALE", "Age": "AGE_25_34"}',
        )
        item = body["params"]["BidModifiers"][0]
        assert "DemographicsAdjustments" in item, f"got keys: {list(item.keys())}"
        assert "DemographicsAdjustment" not in item
        assert isinstance(item["DemographicsAdjustments"], list)
        assert item["DemographicsAdjustments"][0]["BidModifier"] == 150

    def test_retargeting_plural(self):
        body = _dry_run(
            "bidmodifiers", "add",
            "--campaign-id", "123",
            "--type", "RETARGETING_ADJUSTMENT",
            "--value", "120",
            "--json", '{"RetargetingConditionId": 456}',
        )
        item = body["params"]["BidModifiers"][0]
        assert "RetargetingAdjustments" in item, f"got keys: {list(item.keys())}"
        assert isinstance(item["RetargetingAdjustments"], list)

    def test_regional_plural(self):
        body = _dry_run(
            "bidmodifiers", "add",
            "--campaign-id", "123",
            "--type", "REGIONAL_ADJUSTMENT",
            "--value", "110",
            "--json", '{"RegionId": 1}',
        )
        item = body["params"]["BidModifiers"][0]
        assert "RegionalAdjustments" in item, f"got keys: {list(item.keys())}"
        assert isinstance(item["RegionalAdjustments"], list)

    def test_mobile_singular(self):
        """MobileAdjustment stays singular — regression guard."""
        body = _dry_run(
            "bidmodifiers", "add",
            "--campaign-id", "123",
            "--type", "MOBILE_ADJUSTMENT",
            "--value", "130",
        )
        item = body["params"]["BidModifiers"][0]
        assert "MobileAdjustment" in item
        assert isinstance(item["MobileAdjustment"], dict)
```

- [ ] **Step 3: Запустить тесты и убедиться что FAIL**

```bash
.venv/bin/pytest tests/test_dry_run.py::TestBidModifiersAddPluralFields -v
```

Ожидается: `FAILED` — поля называются singular (`DemographicsAdjustment`, `RetargetingAdjustment`, `RegionalAdjustment`).

- [ ] **Step 4: Исправить `_BIDMODIFIER_TYPE_TO_NESTED` в `direct_cli/commands/bidmodifiers.py`**

Заменить весь словарь `_BIDMODIFIER_TYPE_TO_NESTED`:

```python
# Было:
_BIDMODIFIER_TYPE_TO_NESTED = {
    "MOBILE_ADJUSTMENT": "MobileAdjustment",
    "TABLET_ADJUSTMENT": "TabletAdjustment",
    "DESKTOP_ADJUSTMENT": "DesktopAdjustment",
    "DESKTOP_ONLY_ADJUSTMENT": "DesktopOnlyAdjustment",
    "DEMOGRAPHICS_ADJUSTMENT": "DemographicsAdjustment",
    "RETARGETING_ADJUSTMENT": "RetargetingAdjustment",
    "REGIONAL_ADJUSTMENT": "RegionalAdjustment",
    "VIDEO_ADJUSTMENT": "VideoAdjustment",
    "SMART_AD_ADJUSTMENT": "SmartAdAdjustment",
    "SERP_LAYOUT_ADJUSTMENT": "SerpLayoutAdjustment",
    "INCOME_GRADE_ADJUSTMENT": "IncomeGradeAdjustment",
    "AD_GROUP_ADJUSTMENT": "AdGroupAdjustment",
}

# Стало (plural-поля исправлены по WSDL BidModifierAddItem):
_BIDMODIFIER_TYPE_TO_NESTED = {
    "MOBILE_ADJUSTMENT": "MobileAdjustment",
    "TABLET_ADJUSTMENT": "TabletAdjustment",
    "DESKTOP_ADJUSTMENT": "DesktopAdjustment",
    "DESKTOP_ONLY_ADJUSTMENT": "DesktopOnlyAdjustment",
    "DEMOGRAPHICS_ADJUSTMENT": "DemographicsAdjustments",   # plural
    "RETARGETING_ADJUSTMENT": "RetargetingAdjustments",     # plural
    "REGIONAL_ADJUSTMENT": "RegionalAdjustments",           # plural
    "VIDEO_ADJUSTMENT": "VideoAdjustment",
    "SMART_AD_ADJUSTMENT": "SmartAdAdjustment",
    "SERP_LAYOUT_ADJUSTMENT": "SerpLayoutAdjustments",      # plural
    "INCOME_GRADE_ADJUSTMENT": "IncomeGradeAdjustments",    # plural
    "AD_GROUP_ADJUSTMENT": "AdGroupAdjustment",
}

# Множество plural-ключей для формирования payload как списка:
_PLURAL_NESTED_KEYS = {
    "DemographicsAdjustments",
    "RetargetingAdjustments",
    "RegionalAdjustments",
    "SerpLayoutAdjustments",
    "IncomeGradeAdjustments",
}
```

Затем в команде `add` найти место сборки `modifier_data` и добавить обработку plural:

```python
        nested_key = _BIDMODIFIER_TYPE_TO_NESTED[modifier_type.upper()]
        nested = {"BidModifier": value}
        if extra_json:
            extra = json.loads(extra_json)
            if not isinstance(extra, dict):
                raise click.UsageError(
                    "--json must be a JSON object (dict), "
                    f"got {type(extra).__name__}"
                )
            nested.update(extra)

        # Plural fields expect a list per WSDL BidModifierAddItem
        if nested_key in _PLURAL_NESTED_KEYS:
            modifier_data = {nested_key: [nested]}
        else:
            modifier_data = {nested_key: nested}
```

- [ ] **Step 5: Запустить тесты и убедиться что PASS**

```bash
.venv/bin/pytest tests/test_dry_run.py::TestBidModifiersAddPluralFields -v
```

Ожидается: все PASS.

- [ ] **Step 6: Запустить полный unit-suite**

```bash
.venv/bin/pytest -m "not integration and not integration_write" -q
```

Ожидается: все PASS.

- [ ] **Step 7: Commit**

```bash
git add direct_cli/commands/bidmodifiers.py tests/test_dry_run.py
git commit -m "fix(bidmodifiers add): use plural field names per WSDL BidModifierAddItem (Demographics/Retargeting/Regional/SerpLayout/IncomeGrade)"
```

---

## Task 3: Добавить скрипт обновления WSDL-кэша

Сейчас нет механизма обновить 27 кэшированных XML-файлов. Нужен скрипт `scripts/refresh_wsdl_cache.py`, который использует уже существующую функцию `refresh_all_caches()` из `wsdl_coverage.py`.

**Files:**
- Create: `scripts/refresh_wsdl_cache.py`

- [ ] **Step 1: Создать `scripts/refresh_wsdl_cache.py`**

```python
#!/usr/bin/env python3
"""Refresh cached WSDL files for all Yandex Direct API v5 services.

Usage:
    python scripts/refresh_wsdl_cache.py

Fetches fresh WSDL XML from https://api.direct.yandex.com/v5/{service}?wsdl
and overwrites files in tests/wsdl_cache/.

Run periodically (e.g. monthly) or when suspecting the API has changed.
"""

import sys
from pathlib import Path

# Allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from direct_cli.wsdl_coverage import refresh_all_caches, CANONICAL_API_SERVICES


def main():
    print(f"Refreshing WSDL cache for {len(CANONICAL_API_SERVICES)} services...")
    errors = refresh_all_caches()

    if errors:
        print("\nFailed services:")
        for service, exc in sorted(errors.items()):
            print(f"  {service}: {exc}")
        print(f"\n{len(CANONICAL_API_SERVICES) - len(errors)} succeeded, {len(errors)} failed.")
        sys.exit(1)
    else:
        print(f"All {len(CANONICAL_API_SERVICES)} services refreshed successfully.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Убедиться что скрипт запускается без ошибок (dry check)**

```bash
python3 scripts/refresh_wsdl_cache.py --help 2>&1 || python3 -c "
import sys; sys.path.insert(0, '.')
from direct_cli.wsdl_coverage import refresh_all_caches, CANONICAL_API_SERVICES
print('Import OK, services:', len(CANONICAL_API_SERVICES))
"
```

Ожидается: `Import OK, services: 27` (без сетевых запросов).

- [ ] **Step 3: Commit**

```bash
git add scripts/refresh_wsdl_cache.py
git commit -m "chore: add scripts/refresh_wsdl_cache.py for updating WSDL cache"
```

---

## Task 4: Закрыть issue и финальная проверка

- [ ] **Step 1: Запустить все unit-тесты включая api_coverage**

```bash
.venv/bin/pytest -m "not integration and not integration_write" -v 2>&1 | tail -20
```

Ожидается: все PASS.

- [ ] **Step 2: Убедиться что issue #32 можно закрыть — сверить требования**

Требования из issue:
- [x] Phase 1: тест покрытия методов по WSDL — реализован в PR #32
- [x] Phase 2: обнаружение новых сервисов — реализован в PR #32
- [x] advideos CLI — реализован в Task 1
- [x] BidModifiers.add DemographicsAdjustments plural — исправлен в Task 2
- [x] Скрипт обновления кэша — реализован в Task 3
- [ ] Phase 3 (optional): payload schema validation — out of scope, отдельный issue если нужен

- [ ] **Step 3: Закрыть issue на GitHub**

```bash
gh issue close 32 --repo axisrow/direct-cli --comment "Implemented: advideos command (get/add), fixed BidModifiers.add DemographicsAdjustments plural payload bug, added scripts/refresh_wsdl_cache.py. Phase 3 (payload schema validation) left as optional future work."
```
