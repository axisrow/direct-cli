# Copilot Instructions — Direct CLI

Command-line interface for the Yandex Direct API, built with Python and Click.

## Commands

```bash
# Install in dev mode
pip install -e ".[dev]"

# Run all unit tests
pytest

# Run integration tests (requires .env with real token)
pytest -m integration -v

# Run a single test
pytest tests/test_cli.py::TestCLI::test_cli_help

# Run tests matching pattern
pytest -k "campaigns"

# Format
black .

# Lint
flake8 direct_cli tests
```

## Architecture

The CLI is a Click group-of-groups. Each API resource maps to one file in `direct_cli/commands/` that defines a Click group (e.g. `campaigns`) with subcommands (`get`, `add`, `update`, `delete`, etc.). All groups are imported and registered in `direct_cli/cli.py`.

Request flow: `cli.py` → `auth.py` (resolves token/login) → `api.py` (`create_client`) → `tapi_yandex_direct.YandexDirect` → Yandex Direct API → `output.py` (format and print).

`utils.py` holds shared helpers: `parse_ids`, `parse_json`, `build_selection_criteria`, `build_common_params`, `get_default_fields`. All command modules import from these; don't duplicate logic there.

## Key Conventions

**Adding a new command module:**
1. Create `direct_cli/commands/<resource>.py` with a `@click.group()` and subcommands.
2. Import and register it in `direct_cli/cli.py` with `cli.add_command(...)`.
3. Add the command name to `TestCommandsRegistered.EXPECTED_COMMANDS` in `tests/test_comprehensive.py`.

**`--dry-run` flag:** `add` and `update` commands support `--dry-run` — they print the request body as JSON without making an API call. Use this as a test seam: these subcommands can be tested without mocking the HTTP layer.

**SelectionCriteria requirements:** Some resources (`adgroups`, `ads`, `keywords`) require at least one of `Ids`, `CampaignIds`, or `AdGroupIds` in `SelectionCriteria`. Calling `get` without any filter raises API error 4001. Integration tests handle this by fetching a campaign ID first via `get_first_campaign_id()`.

**Default fields in `utils.py`:** `COMMON_FIELDS` maps resource names to default `FieldNames`. Not all fields are valid for all resources — for example, `adimages` uses `AdImageHash` (not `Id`) as its key, and neither `clients` nor `creatives` accept `Status`. When adding a resource, verify field names against the Yandex Direct API docs.

**Error handling in commands:** All command functions wrap API calls in `try/except Exception` and call `print_error(str(e))` + `raise click.Abort()`. Keep this pattern consistent.

**Test types:**
- Unit tests (`tests/test_cli.py`, `tests/test_comprehensive.py`) — no API calls, run without a token.
- Integration tests (`tests/test_integration.py`, `@pytest.mark.integration`) — require `.env` with `YANDEX_DIRECT_TOKEN` and `YANDEX_DIRECT_LOGIN`. Auto-skip if token is absent.

**Credentials:** `.env` in the project root. `YANDEX_DIRECT_LOGIN` is the Yandex advertiser login (required). `load_dotenv()` is called at `cli.py` module import, so it is loaded before any Click invocation.

## Dangerous Commands — Do Not Auto-Test

Never invoke these commands in automated tests against a real account.

### 🔴 Irreversible — permanently destroy data
| Command | Risk |
|---------|------|
| `campaigns delete` | Permanently deletes a campaign and all its content |
| `adgroups delete` | Permanently deletes an ad group and its ads/keywords |
| `ads delete` | Permanently deletes an ad |
| `keywords delete` | Permanently deletes a keyword |
| `audiencetargets delete` | Permanently deletes an audience target |

### 🟠 Financial impact — change bids or spending
| Command | Risk |
|---------|------|
| `bids set` | Changes search/network bids on campaigns — direct cost impact |
| `keywordbids set` | Changes per-keyword bids |
| `bidmodifiers set` | Changes bid multipliers (device, region, time, etc.) |

### 🟡 Reversible but affect live traffic
`campaigns suspend/resume/archive/unarchive`, `ads suspend/resume/archive/unarchive`, `keywords suspend/resume/archive/unarchive`, `audiencetargets suspend/resume`

### 🟡 Account-wide mutations
`clients update` — modifies account-level settings.

### 🟡 Content creation (hard to clean up in bulk)
All `add` and `update` subcommands across: `campaigns`, `adgroups`, `ads`, `keywords`, `feeds`, `retargeting`, `sitelinks`, `turbopages`, `vcards`, `adextensions`, `negativekeywordsharedsets`, `smartadtargets`, `dynamicads`, `audiencetargets`.

These can be safely tested using `--dry-run` (outputs the request body as JSON without sending it).

### ✅ Safe to auto-test (read-only, no side effects)
All `get` subcommands, plus: `changes check*`, `dictionaries list-names`, `keywordsresearch has-search-volume`, `reports list-types`.
