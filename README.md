# Direct CLI

[English](#english) | [Русский](#русский)

---

## English

Command-line interface for the Yandex Direct API.

### Installation

```bash
pip install direct-cli
```

### Configuration

Create a `.env` file in your working directory:

```env
YANDEX_DIRECT_TOKEN=your_access_token
YANDEX_DIRECT_LOGIN=your_yandex_login
```

Or pass credentials directly per command:

```bash
direct --token YOUR_TOKEN --login YOUR_LOGIN campaigns get
```

Use profile-specific credentials from `.env`:

```env
YANDEX_DIRECT_TOKEN_AGENCY1=token-1
YANDEX_DIRECT_LOGIN_AGENCY1=client-login-1
YANDEX_DIRECT_TOKEN_AGENCY2=token-2
YANDEX_DIRECT_LOGIN_AGENCY2=client-login-2
```

OAuth and profile commands:

```bash
direct auth login
direct auth login --profile agency1
direct auth login --code abc123 --profile agency1
direct auth list
direct auth use --profile agency1
direct auth status --profile agency1
direct --profile agency1 campaigns get
```

Notes:
- Legacy profile environment variable is not used.
- Select credentials with `--profile`.
- `--login` remains Direct client login.
- Authorization is performed via `direct auth login`.
- OAuth profiles store refresh tokens and refresh access tokens automatically.
- `direct auth login --oauth-token TOKEN` is a manual access-token import and does not auto-refresh.
- Alias `auth_login` is not supported.

Credential resolution priority:

| Priority | Source | Example |
|----------|--------|---------|
| 1 | Explicit CLI options | `direct --token TOKEN --login LOGIN campaigns get` |
| 2 | OAuth profile storage | `direct --profile agency1 campaigns get` |
| 3 | Profile-specific env vars | `YANDEX_DIRECT_TOKEN_AGENCY1`, `YANDEX_DIRECT_LOGIN_AGENCY1` |
| 4 | Base env vars or project `.env` | `YANDEX_DIRECT_TOKEN`, `YANDEX_DIRECT_LOGIN` |
| 5 | 1Password references | `--op-token-ref`, `YANDEX_DIRECT_OP_TOKEN_REF` |
| 6 | Bitwarden references | `--bw-token-ref`, `YANDEX_DIRECT_BW_TOKEN_REF` |

The project `.env` file is loaded automatically. If a profile is selected
with `--profile` or `direct auth use --profile NAME`, Direct CLI does not
fall back to base `YANDEX_DIRECT_LOGIN`; this prevents mixing a profile token
with a login from the project `.env`. For multi-account setups, prefer OAuth
profiles or profile-specific env vars instead of base credentials.

Install with `pip install direct-cli`, then run commands with `direct`.
Invoking the deprecated `direct-cli` entrypoint exits with
`use direct instead of direct-cli`.

### Quick Start: Check Balance

Yandex removed the legacy v4 `GetBalance` method. Direct CLI uses the v4 Live
`AccountManagement` method with `Action=Get` for `direct balance`, returning
money fields such as `Amount`, `AmountAvailableForTransfer`, and `Currency`.

```bash
direct balance
direct balance --logins client-login,other-client --format table
direct balance --logins client-login --dry-run
```

### Global Options

| Option | Description |
|--------|-------------|
| `--token` | API access token |
| `--login` | Direct client login |
| `--profile` | Credential profile name |
| `--sandbox` | Use sandbox API |

### V4 Live Goals

```bash
direct v4goals get-stat-goals --campaign-ids 123,456
direct v4goals get-retargeting-goals --campaign-ids 123,456 --format table
direct v4goals get-stat-goals --campaign-ids 123 --dry-run
```

### V4 Live Events

```bash
direct v4events get-events-log --from 2026-04-14T00:00:00 --to 2026-04-15T00:00:00
direct v4events get-events-log --from 2026-04-14T00:00:00 --to 2026-04-15T00:00:00 --currency RUB --limit 100 --offset 0 --format table
```

### V4 Live Finance

Finance methods require an extra financial token for money operations. In the
Yandex Direct web UI, open Tools -> API -> Financial operations, enable the
financial operations checkbox, click Save, then issue the master token on the
same Financial operations page and confirm by SMS. Direct CLI can compute the
per-request token from `--master-token`, `--operation-num`, and
`--finance-login`; alternatively pass a precomputed token with `--finance-token`.
Environment variables are
`YANDEX_DIRECT_MASTER_TOKEN`, `YANDEX_DIRECT_FINANCE_LOGIN`,
`YANDEX_DIRECT_FINANCE_TOKEN`, and `YANDEX_DIRECT_OPERATION_NUM`. Money mutation
commands are dry-run-only in this release and always require `--dry-run`; dry-run
output masks the financial token.

```bash
direct v4finance get-credit-limits --logins client-login --master-token MASTER_TOKEN --operation-num 123 --finance-login agency-login
direct v4finance get-credit-limits --logins client-login,other-client --format table
direct v4finance check-payment --custom-transaction-id A123456789012345678901234567890B
direct v4finance transfer-money --from-campaign-id 123 --to-campaign-id 456 --amount 100.50 --currency RUB --master-token MASTER_TOKEN --operation-num 123 --finance-login agency-login --dry-run
direct v4finance pay-campaigns --campaign-ids 123,456 --amount 100.50 --currency RUB --contract-id CONTRACT_ID --pay-method Bank --master-token MASTER_TOKEN --operation-num 123 --finance-login agency-login --dry-run
```

### V4 Live Shared Account

Shared-account mutations are dry-run-only in this release and always require
`--dry-run`. These commands follow the official v4 Live shared-account method
shapes: `EnableSharedAccount` accepts one client `Login`, and
`AccountManagement` updates shared-account settings through `Accounts`.

```bash
direct v4account enable-shared-account --client-login client-login --dry-run
direct v4account account-management --action Update --account-id 1327944 --day-budget 100.50 --spend-mode Default --money-in-sms Yes --money-out-sms No --email ops@example.com --money-warning-value 25 --dry-run
```

### CLI Convention

The current CLI convention is defined as follows.

#### CLI Contract

The canonical command shape is:

```bash
direct <group> <command> [flags]
```

Naming rules:

- `group`:
  - lowercase ASCII only
  - no underscores
  - multiword groups are concatenated
  - examples: `dynamicads`, `smartadtargets`, `negativekeywordsharedsets`

- `command`:
  - lowercase only
  - multiword commands use kebab-case
  - examples: `get`, `set-bids`, `check-campaigns`, `has-search-volume`

The `direct` executable defines the public naming contract. The
`direct-cli` package name and deprecated shim do not define canonical CLI
names. `tapi-yandex-direct` may influence the internal transport layer, but it
does not define canonical CLI names.

The current policy is canonical-only. Historical aliases are not preserved in
the runtime CLI by default. If compatibility is ever needed, an alias must be
added as an explicit exception with the concrete legacy syntax that still has to
be supported.

#### Removed Legacy Names

| Legacy name                | Canonical name               |
|----------------------------|------------------------------|
| `dynamictargets`           | `dynamicads`                 |
| `smarttargets`             | `smartadtargets`             |
| `negativekeywords`         | `negativekeywordsharedsets`  |
| `list`                     | `get`                        |
| `checkcamp`                | `check-campaigns`            |
| `checkdict`                | `check-dictionaries`         |

#### Input Rules

- All user-facing input must be passed only through typed CLI flags.
- `--json` is not part of the public CLI contract.
- User-facing parameters must not be passed through `--json`.
- The CLI must not accept `SelectionCriteria`, nested payloads, update payloads, bidding rules, or any other user-facing command input through `--json`.
- Typed flags and JSON blobs must not be mixed as part of one public command contract.
- If the API requires a complex object, the CLI must expose explicit flags or subcommands instead of forwarding raw JSON.

#### Command Formatting Rules

- Every canonical CLI command must be written strictly on a single line.
- Multi-line command formatting is not allowed.
- Shell line continuation using `\` is forbidden in canonical documentation, help text, tests, and examples.

Allowed:

```bash
direct dictionaries get-geo-regions --region-ids 225,187 --fields GeoRegionId,GeoRegionName
```

Not allowed:

```bash
direct dictionaries get-geo-regions \
  --region-ids 225,187 \
  --fields GeoRegionId,GeoRegionName
```

#### Flag Design Rules

- List inputs use comma-separated CLI syntax where appropriate.
- Money and bid values are passed in micro-rubles (API-native format). Values below 100,000 trigger a validation hint suggesting the correct scale.
- Selector fields remain explicit flags, for example:
  - `--id`
  - `--campaign-id`
  - `--adgroup-id`
- Nested API structures must be projected into typed flags instead of blob JSON.
- Help text must not advertise JSON as an alternative input path.

#### Datetime Rules

- Datetime parameters must be passed in the format `YYYY-MM-DDTHH:MM:SS`.
- Datetime values must be passed as a single shell token.
- Canonical examples must not use timezone suffixes like `Z`.
- Canonical examples must not use quoted space-separated datetime values.

Use:

```bash
direct changes check-campaigns --timestamp 2026-04-14T00:00:00
```

Do not use:

```bash
direct changes check-campaigns --timestamp 2026-04-14T00:00:00Z
direct changes check-campaigns --timestamp "2026-04-14 00:00:00"
```

#### Documentation Contract

- `README` must use only canonical syntax.
- `README` must use only single-line command examples.
- Canonical examples must not contain `--json`.
- Help output and tests must enforce the same contract.

#### Examples

Valid canonical examples:

```bash
direct campaigns get --ids 1,2,3
direct changes check-campaigns --timestamp 2026-04-14T00:00:00
direct keywordsresearch has-search-volume --keywords "buy laptop,buy desktop"
direct smartadtargets update --id 456 --priority HIGH
direct dynamicads set-bids --id 789 --bid 12500000 --context-bid 9000000 --priority HIGH
direct dictionaries get-geo-regions --name Moscow --region-ids 225,187 --exact-names Москва,Санкт-Петербург --fields GeoRegionId,GeoRegionName
```

Invalid examples:

```bash
direct dictionaries get-geo-regions --json '{"GeoRegionIds":[225]}' --fields GeoRegionId,GeoRegionName
direct dynamicads set-bids --id 789 --bid 12500000 --json '{"StrategyPriority":"HIGH"}'
direct dictionaries get-geo-regions \
  --region-ids 225 \
  --fields GeoRegionId,GeoRegionName
direct changes check-campaigns --timestamp 2026-04-14T00:00:00Z
direct changes check-campaigns --timestamp "2026-04-14 00:00:00"
```

#### Campaigns

```bash
# Get campaigns
direct campaigns get
direct campaigns get --status ACTIVE
direct campaigns get --ids 1,2,3 --format table
direct campaigns get --fetch-all --format csv --output campaigns.csv

# Create (use --dry-run to preview the request)
direct campaigns add --name "My Campaign" --start-date 2024-02-01 --type TEXT_CAMPAIGN --budget 1000000000 --setting ADD_METRICA_TAG=YES --search-strategy HIGHEST_POSITION --network-strategy SERVING_OFF --dry-run
direct campaigns add --name "Dynamic Campaign" --start-date 2024-02-01 --type DYNAMIC_TEXT_CAMPAIGN --setting ADD_METRICA_TAG=NO --search-strategy HIGHEST_POSITION --network-strategy SERVING_OFF --dry-run
direct campaigns add --name "Smart Campaign" --start-date 2024-02-01 --type SMART_CAMPAIGN --network-strategy AVERAGE_CPC_PER_FILTER --filter-average-cpc 1000000 --counter-id 123 --dry-run

# Update / lifecycle
direct campaigns update --id 12345 --name "New Name" --status SUSPENDED --budget 100000000 --start-date 2024-02-10 --end-date 2024-03-01
direct campaigns suspend --id 12345
direct campaigns resume --id 12345
direct campaigns archive --id 12345
direct campaigns unarchive --id 12345
direct campaigns delete --id 12345
```

#### Ad Groups

```bash
direct adgroups get --campaign-ids 1,2,3 --limit 50
direct adgroups add --name "Group 1" --campaign-id 12345 --region-ids 1,225 --dry-run
direct adgroups add --name "Dynamic Group" --campaign-id 12345 --type DYNAMIC_TEXT_AD_GROUP --region-ids 1,225 --domain-url example.com --dry-run
direct adgroups add --name "Smart Group" --campaign-id 12345 --type SMART_AD_GROUP --region-ids 1,225 --feed-id 170 --ad-title-source FEED_NAME --ad-body-source FEED_NAME --dry-run
direct adgroups update --id 67890 --name "New Name" --status SUSPENDED --region-ids 1,225
direct adgroups delete --id 67890
```

#### Ads

```bash
direct ads get --campaign-ids 1,2,3
direct ads get --adgroup-ids 45678 --format table
direct ads add --adgroup-id 12345 --type TEXT_AD --title "Title" --text "Ad text" --href "https://example.com" --dry-run
direct ads add --adgroup-id 12345 --type TEXT_IMAGE_AD --image-hash abcdefghijklmnopqrst --href "https://example.com" --title "Banner" --text "Image ad" --dry-run
direct ads update --id 99999 --status PAUSED --title "New Title" --text "New text" --href "https://example.com" --image-hash abcdefghijklmnopqrst
direct ads delete --id 99999
```

#### Keywords

```bash
direct keywords get --campaign-ids 1,2,3
direct keywords add --adgroup-id 12345 --keyword "buy laptop" --bid 10500000 --context-bid 5250000 --user-param-1 segment-a --user-param-2 segment-b --dry-run
direct keywords update --id 88888 --keyword "updated keyword text"
direct keywords delete --id 88888
```

#### Reports

```bash
# Get a report (saved to file)
direct reports get --type CAMPAIGN_PERFORMANCE_REPORT --from 2024-01-01 --to 2024-01-31 --name "January Report" --fields "Date,CampaignId,Clicks,Cost" --format csv --output report.csv
direct reports get --type CUSTOM_REPORT --from 2024-01-01 --to 2024-01-31 --name "Goals Report" --fields "Date,CampaignId,GoalsRoi" --goals 12345,67890 --attribution-models AUTO --format csv --output goals-report.csv

# List available report types
direct reports list-types
```

Available report types: `CAMPAIGN_PERFORMANCE_REPORT`, `ADGROUP_PERFORMANCE_REPORT`, `AD_PERFORMANCE_REPORT`, `CRITERIA_PERFORMANCE_REPORT`, `CUSTOM_REPORT`, `REACH_AND_FREQUENCY_CAMPAIGN_REPORT`, `SEARCH_QUERY_PERFORMANCE_REPORT`

#### Other Resources

```bash
# Reference dictionaries and changes
direct dictionaries get --names Currencies,GeoRegions
direct dictionaries get-geo-regions --name Moscow --region-ids 225,187 --exact-names Москва,Санкт-Петербург --fields GeoRegionId,GeoRegionName

# Client info
direct clients get --fields ClientId,Login,Currency

# Changes
direct changes check --campaign-ids 1,2,3 --timestamp 2026-04-14T00:00:00 --fields CampaignIds,AdGroupIds,AdIds,CampaignsStat
direct changes check-campaigns --timestamp 2026-04-14T00:00:00
direct changes check-dictionaries

# Keyword research and retargeting
direct keywordsresearch has-search-volume --keywords "buy laptop,buy desktop"
direct retargeting add --name "List A" --type AUDIENCE --rule "ALL:12345:30|67890:7" --dry-run
direct retargeting update --id 55 --name "Renamed" --rule "ANY:12345:30" --dry-run

# Bids and modifiers
direct bids get --campaign-ids 123 --fields CampaignId,AdGroupId,KeywordId,Bid
direct bids set --keyword-id 123 --bid 15000000
direct bids set-auto --keyword-id 123 --max-bid 20000000 --position PREMIUMBLOCK --scope SEARCH --dry-run
direct keywordbids set --keyword-id 321 --search-bid 8000000 --network-bid 3000000
direct keywordbids set-auto --keyword-id 321 --target-traffic-volume 100 --increase-percent 10 --bid-ceiling 12500000 --dry-run
direct bidmodifiers get --campaign-ids 123 --fields Id,CampaignId,AdGroupId,Level,Type
direct bidmodifiers add --campaign-id 123 --type DEMOGRAPHICS_ADJUSTMENT --value 150 --gender GENDER_MALE --age AGE_25_34 --dry-run
direct bidmodifiers set --id 99 --value 130 --dry-run

# Canonical multiword groups
direct negativekeywordsharedsets update --id 123 --keywords "foo,bar"
direct audiencetargets get --campaign-ids 123 --fields Id,AdGroupId,RetargetingListId,State,ContextBid
direct audiencetargets add --adgroup-id 100 --retargeting-list-id 200 --bid 12000000 --priority HIGH --dry-run
direct audiencetargets set-bids --id 101 --context-bid 7000000 --priority LOW --dry-run
direct dynamicads add --adgroup-id 33 --name "Webpage A" --condition "URL:CONTAINS_ANY:test|shop" --condition "PAGE_CONTENT:CONTAINS:baz" --bid 3000000 --context-bid 2000000 --priority HIGH --dry-run
direct smartadtargets add --adgroup-id 55 --name "Audience A" --audience ALL_SEGMENTS --condition "CATEGORY_ID:EQUALS:42" --average-cpc 3000000 --average-cpa 4000000 --priority HIGH --available-items-only YES --dry-run
direct smartadtargets update --id 456 --priority HIGH
direct smartadtargets set-bids --id 456 --average-cpc 10500000 --average-cpa 15000000 --priority HIGH
direct dynamicads set-bids --id 789 --bid 12500000 --context-bid 9000000 --priority HIGH

# Shared bidding strategies
direct strategies get --limit 5
direct strategies add --name "Shared Clicks" --type WbMaximumClicks --params '{"SpendLimit":1000000000,"AverageCpc":30000000}' --dry-run
direct strategies update --id 42 --params '{"AverageCpc":35000000}' --dry-run
direct strategies archive --id 42 --dry-run

# Dynamic feed ad targets
direct dynamicfeedadtargets get --adgroup-ids 123 --limit 5
direct dynamicfeedadtargets add --adgroup-id 33 --name "Feed slice A" --condition "CATEGORY:EQUALS:shoes" --bid 5000000 --dry-run
direct dynamicfeedadtargets set-bids --id 789 --bid 6500000 --context-bid 4000000 --dry-run

# Extensions, assets, feeds, and clients
direct sitelinks add --sitelink "Docs|https://example.com/docs" --sitelink "Help|https://example.com/help|Desk" --dry-run
direct vcards add --campaign-id 555 --country "Russia" --city "Moscow" --company-name "Acme" --work-time 1#5#9#0#18#0 --phone-country-code +7 --phone-city-code 495 --phone-number 1234567 --dry-run
direct adextensions add --callout-text "Free shipping" --dry-run
direct adimages add --name banner.png --image-data BASE64DATA --type ICON --dry-run
direct creatives add --video-id video-id --dry-run
direct feeds add --name "Feed A" --url "https://example.com/feed.xml" --dry-run
direct feeds update --id 18 --name "Feed A v2" --url "https://example.com/feed-v2.xml" --dry-run
direct clients update --client-info "Priority client" --phone +70000000000 --notification-email user@example.com --notification-lang EN --email-subscription RECEIVE_RECOMMENDATIONS=YES --setting DISPLAY_STORE_RATING=NO --dry-run
direct --login CLIENT_LOGIN clients update --phone +70000000000 --notification-email user@example.com --dry-run
direct agencyclients add-passport-organization --name "Org" --currency RUB --notification-email ops@example.com --notification-lang EN --no-send-account-news --send-warnings --dry-run
direct agencyclients add-passport-organization-member --passport-organization-login org-login --role CHIEF --invite-email user@example.com --dry-run
direct agencyclients update --client-id 42 --phone +70000000000 --notification-email user@example.com --grant EDIT_CAMPAIGNS=YES --grant IMPORT_XLS=NO --dry-run
```

`direct agencyclients add` is runtime-deprecated by Yandex Direct and is blocked by the CLI. Use `direct agencyclients add-passport-organization` instead.

### Known Unsupported API Operation

`dynamicads update` is unsupported by API. The Yandex Direct
`dynamictextadtargets` service exposes `add`, `get`, `delete`, `suspend`,
`resume`, and `setBids`, but no `update` operation. Do not add or rely on
`direct dynamicads update` unless Yandex exposes a real API method.

### Output Formats

All `get` commands support `--format`:

| Format | Description |
|--------|-------------|
| `json` | JSON (default) |
| `table` | Formatted table |
| `csv` | CSV |
| `tsv` | TSV |

```bash
direct campaigns get --format table
direct campaigns get --format csv --output campaigns.csv
```

### Pagination

```bash
direct campaigns get --limit 10        # first 10 results
direct campaigns get --fetch-all       # all pages
```

### ⚠️ Destructive Commands

The following commands make **irreversible changes** — use with caution:

| Command | Effect |
|---------|--------|
| `campaigns delete --id` | Permanently deletes a campaign and all its contents |
| `adgroups delete --id` | Permanently deletes an ad group |
| `ads delete --id` | Permanently deletes an ad |
| `keywords delete --id` | Permanently deletes a keyword |
| `audiencetargets delete --id` | Permanently deletes an audience target |

Commands that affect live ad delivery: `suspend`, `resume`, `archive`, `unarchive` (available on `campaigns`, `ads`), `suspend`, `resume` (also on `keywords`).

Commands that affect bids and spending: `bids set`, `keywordbids set`, `bidmodifiers set`.

Use `--dry-run` on `add` / `update` commands to preview the API request before sending:

```bash
direct campaigns add --name "Test" --start-date 2024-01-01 --dry-run
```

### Testing

Four tiers of tests live under `tests/`:

| Tier | Marker | Network | Token required |
|---|---|---|---|
| Unit / CLI wiring / dry-run | *(none)* | No | No |
| Read-only integration | `-m integration` | Yes (production API, read-only) | Yes |
| Write integration | `-m integration_write` | No (replays VCR cassettes) | No |
| Live draft write integration | `-m integration_live_write` | Yes when recording, otherwise VCR replay | Yes + `YANDEX_DIRECT_LIVE_WRITE=1` |

```bash
pip install -e ".[dev]"
pytest                              # fast tier — no token
pytest -m integration -v            # read-only integration tests (needs token)
pytest -m integration_write -v      # write cassette replay (no token needed)
YANDEX_DIRECT_LIVE_WRITE=1 pytest -m integration_live_write -v  # live draft cassette replay
YANDEX_DIRECT_LIVE_WRITE=1 pytest -m integration_live_write -v --record-mode=rewrite  # re-record live draft cassette
```

#### Smoke command scripts

Every CLI subcommand is classified in `direct_cli/smoke_matrix.py`.

| Category | Script | When to run |
|---|---|---|
| SAFE | `scripts/test_safe_commands.sh` | Production read-only smoke checks; requires `YANDEX_DIRECT_TOKEN` and `YANDEX_DIRECT_LOGIN` |
| WRITE_SANDBOX | `scripts/test_sandbox_write.sh` | Live sandbox write smoke checks; requires `YANDEX_DIRECT_TOKEN` and `YANDEX_DIRECT_LOGIN`; reports `PASS`, `FAIL`, `SANDBOX_LIMITATION`, or `NOT_COVERED` for each command |
| DANGEROUS | `scripts/test_dangerous_commands.sh` | Manual checklist only; exits with status 1 by design |

Current command surface:

| Metric | Count |
|---|---:|
| WSDL-backed API services | 29 |
| Supported API services including Reports | 30 |
| WSDL operations | 112 |
| CLI groups including `auth` | 39 |
| CLI subcommands including `auth` | 130 |
| API CLI subcommands excluding `auth` | 126 |

### API Coverage And Drift Monitoring

The project now distinguishes four surfaces:

| Surface | Coverage strategy |
|---|---|
| Canonical WSDL-backed SOAP services | `tests/test_api_coverage.py` verifies strict service/method parity and dry-run request-schema coverage or explicit exclusions |
| Live-discovered WSDL model gaps | `scripts/build_api_coverage_report.py` reports services seen in the audited live API surface but not yet declared in the CLI coverage model |
| Non-WSDL services (`reports`) | Explicit contract tests |
| Historical aliases retained by exception | None currently retained |
| Intentional CLI-only helpers | Explicitly allowlisted with reasons in `direct_cli/wsdl_coverage.py` |

`100% coverage` in this project means full coverage of the supported
**declared canonical API surface**. The API coverage report also includes a
`model_gaps` section for live-discovered Yandex Direct services that are not
yet part of that declared model. Alias groups and CLI-only helpers remain
supported, but they are tracked outside the strict parity metric.

Useful maintenance commands:

```bash
python scripts/build_api_coverage_report.py
python scripts/refresh_wsdl_cache.py
python scripts/check_wsdl_drift.py
```

CI runs a scheduled API coverage workflow that:
- runs the fast coverage suites;
- uploads a machine-readable API coverage report artifact, including declared
  parity and live-discovered model gap counts;
- checks the cached WSDL files against the live Yandex Direct API on schedule.

#### Live sandbox write smoke

`WRITE_SANDBOX` smoke is a live check against the Yandex Direct **sandbox**.
It does not replay stored HTTP traffic and it does not create new recordings.
Run it only when you intentionally want to call `api-sandbox.direct.yandex.ru`:

```bash
set -a && source .env && set +a
scripts/test_sandbox_write.sh
```

The runner executes matrix commands through `direct --sandbox ...`, creates
temporary sandbox prerequisites where possible, and cleans them up best-effort.
The report contains one row per `WRITE_SANDBOX` command:

- `PASS` means the command completed against the live sandbox API.
- `SANDBOX_LIMITATION` means the request reached the API and hit a known
  sandbox-only limitation such as codes `8800`, `1000`, `3500`, or `5004`.
- `FAIL` means an unexpected CLI or API error.
- `NOT_COVERED` means the runner does not yet know how to safely build the
  prerequisites for that command.

The same OAuth token works for both production and the sandbox; no separate
sandbox token is needed.

#### Re-recording write cassettes

The `integration_write` pytest tier still replays stored write-test traffic
for regression coverage. If you change those tests or their payloads and
intentionally need to refresh the fixtures, regenerate them separately:

```bash
set -a && source .env && set +a        # load YANDEX_DIRECT_TOKEN / LOGIN
pytest -m integration_write -v --record-mode=rewrite
```

After recording, **always audit the generated YAMLs for leaked secrets**:

```bash
grep -r "$YANDEX_DIRECT_TOKEN" tests/cassettes/   # must return nothing
grep -r "$YANDEX_DIRECT_LOGIN" tests/cassettes/   # must return nothing
```

The VCR config in `tests/conftest.py` already strips `Authorization`,
`Client-Login`, cookies and any response header containing the substring
`login`, but manual verification is mandatory before committing.

#### Live draft write tests

The `integration_live_write` tier is manual-only and intentionally separate
from sandbox cassette tests. In rewrite mode it runs against the production
Yandex Direct API, but it may only create disposable draft resources and
delete the exact IDs it created in the same test run. Current coverage is
limited to a guarded campaign draft create -> get -> delete check.

Replay the checked-in cassette:

```bash
YANDEX_DIRECT_LIVE_WRITE=1 pytest -m integration_live_write -v
```

Re-record it only when you intentionally want to verify live draft behavior:

```bash
YANDEX_DIRECT_LIVE_WRITE=1 pytest -m integration_live_write -v --record-mode=rewrite
```

Do not add tests to this tier that accept external IDs, resume/suspend/archive
existing resources, mutate bids, or touch serving campaigns.

### Release Process

Build, validate and upload to PyPI:

```bash
pip install -e ".[dev]"
scripts/release_pypi.sh testpypi   # upload to TestPyPI
scripts/release_pypi.sh pypi       # upload to PyPI
scripts/release_pypi.sh all        # both
```

The script reads credentials from `.env`:

```dotenv
TWINE_USERNAME=__token__
TEST_PYPI_TOKEN=pypi-...
PYPI_TOKEN=pypi-...
```

#### PyPI Token Scoping

PyPI API tokens can be **account-wide** or **project-scoped**:

- **Project-scoped** tokens only allow uploads to the specific project they were created for. A token scoped to `telethon-cli` cannot upload `direct-cli` — you will get **403 Forbidden**.
- **Account-wide** tokens allow uploads to any project under your account.
- For the **first publication** of a new project, you **must** use an account-wide token (project-scoped tokens cannot be created until the project exists on PyPI).
- After the first successful upload, create a project-scoped token at https://pypi.org/manage/account/token/ and replace the account-wide token in `.env`.

Bump `version` in `pyproject.toml` before each release — PyPI rejects duplicate versions.

### License

MIT

---

## Русский

Интерфейс командной строки для Яндекс.Директ API.

### Установка

```bash
pip install direct-cli
```

### Настройка

Создайте файл `.env` в рабочей директории:

```env
YANDEX_DIRECT_TOKEN=ваш_токен
YANDEX_DIRECT_LOGIN=ваш_логин_на_яндексе
```

Или передавайте credentials напрямую в команду:

```bash
direct --token ВАШ_ТОКЕН --login ВАШ_ЛОГИН campaigns get
```

Используйте профильные credentials из `.env`:

```env
YANDEX_DIRECT_TOKEN_AGENCY1=token-1
YANDEX_DIRECT_LOGIN_AGENCY1=client-login-1
YANDEX_DIRECT_TOKEN_AGENCY2=token-2
YANDEX_DIRECT_LOGIN_AGENCY2=client-login-2
```

OAuth и profile-команды:

```bash
direct auth login
direct auth login --profile agency1
direct auth login --code abc123 --profile agency1
direct auth list
direct auth use --profile agency1
direct auth status --profile agency1
direct --profile agency1 campaigns get
```

Примечания:
- OAuth profiles сохраняют refresh token и автоматически обновляют access token.
- `direct auth login --oauth-token TOKEN` импортирует access token вручную и не включает auto-refresh.

Порядок выбора credentials:

| Приоритет | Источник | Пример |
|-----------|----------|--------|
| 1 | Явные CLI-опции | `direct --token TOKEN --login LOGIN campaigns get` |
| 2 | OAuth profile storage | `direct --profile agency1 campaigns get` |
| 3 | Профильные env vars | `YANDEX_DIRECT_TOKEN_AGENCY1`, `YANDEX_DIRECT_LOGIN_AGENCY1` |
| 4 | Базовые env vars или project `.env` | `YANDEX_DIRECT_TOKEN`, `YANDEX_DIRECT_LOGIN` |
| 5 | 1Password references | `--op-token-ref`, `YANDEX_DIRECT_OP_TOKEN_REF` |
| 6 | Bitwarden references | `--bw-token-ref`, `YANDEX_DIRECT_BW_TOKEN_REF` |

Файл `.env` в проекте загружается автоматически. Если профиль выбран через
`--profile` или `direct auth use --profile NAME`, Direct CLI не подставляет
base `YANDEX_DIRECT_LOGIN`; это защищает от смешивания токена из профиля с
логином из project `.env`. Для нескольких аккаунтов используйте OAuth profiles
или профильные env vars, а не базовые credentials.

Установка остаётся через `pip install direct-cli`, а запуск команд теперь идет
через `direct`. Вызов deprecated entrypoint `direct-cli` завершается ошибкой с
подсказкой `use direct instead of direct-cli`.

### Глобальные опции

| Опция | Описание |
|-------|----------|
| `--token` | OAuth-токен доступа к API |
| `--login` | Direct client login |
| `--profile` | Имя credential profile |
| `--sandbox` | Использовать тестовое API (песочница) |

### Использование

Канонический transport-контракт выглядит так:

```bash
direct <group> <command> [flags]
```

Group naming rules:
- только lowercase ASCII
- без `_`
- многословные группы склеиваются, например `negativekeywordsharedsets`

Command naming rules:
- только lowercase
- kebab-case для многословных действий, например `check-campaigns`
- в документации и примерах каноническими считаются `get`,
  `check-dictionaries` и `has-search-volume`

Публичный naming contract задаёт исполняемый файл `direct`. Имя пакета
`direct-cli` и deprecated shim не определяют канонические CLI-имена.
`tapi-yandex-direct` может влиять на внутренний transport layer, но не
определяет канонические CLI-имена.

Текущая политика — canonical-only. Исторические aliases по умолчанию не
сохраняются в runtime CLI. Если совместимость когда-нибудь понадобится, alias
должен быть добавлен как явное exception-правило с конкретным legacy syntax из
`tapi-yandex-direct`, который действительно нужно поддержать.

Удалённые исторические имена:

| Историческое имя           | Каноническое имя             |
|----------------------------|------------------------------|
| `dynamictargets`           | `dynamicads`                 |
| `smarttargets`             | `smartadtargets`             |
| `negativekeywords`         | `negativekeywordsharedsets`  |
| `list`                     | `get`                        |
| `checkcamp`                | `check-campaigns`            |
| `checkdict`                | `check-dictionaries`         |

`direct` — это канонический transport entrypoint над API Яндекс Директа,
устанавливаемый пакетом `direct-cli`. Канонические имена CLI-групп следуют
нормализованным Python-именам из `tapi-yandex-direct`, а имена подкоманд —
это kebab-case проекции API-методов.

Базовые соответствия:

- API `dynamictextadtargets` -> Python `dynamicads` -> CLI `direct dynamicads`
- API `retargetinglists` -> Python `retargeting` -> CLI `direct retargeting`
- API `checkCampaigns` -> CLI `direct changes check-campaigns`
- API `checkDictionaries` -> CLI `direct changes check-dictionaries`
- API `hasSearchVolume` -> CLI `direct keywordsresearch has-search-volume`

### CLI Convention

The current CLI convention is defined as follows.

#### CLI Contract

The canonical command shape is:

```bash
direct <group> <command> [flags]
```

Naming rules:

- `group`:
  - lowercase ASCII only
  - no underscores
  - multiword groups are concatenated
  - examples: `dynamicads`, `smartadtargets`, `negativekeywordsharedsets`

- `command`:
  - lowercase only
  - multiword commands use kebab-case
  - examples: `get`, `set-bids`, `check-campaigns`, `has-search-volume`

Публичный naming contract задаёт исполняемый файл `direct`. Имя пакета
`direct-cli` и deprecated shim не определяют канонические CLI-имена.
`tapi-yandex-direct` может влиять на внутренний transport layer, но не
определяет канонические CLI-имена.

Текущая политика — canonical-only. Исторические aliases по умолчанию не
сохраняются в runtime CLI. Если совместимость когда-нибудь понадобится, alias
должен быть добавлен как явное explicit exception-правило с конкретным legacy
syntax, который действительно нужно поддержать.

#### Input Rules

- All user-facing input must be passed only through typed CLI flags.
- `--json` is not part of the public CLI contract.
- User-facing parameters must not be passed through `--json`.
- The CLI must not accept `SelectionCriteria`, nested payloads, update payloads, bidding rules, or any other user-facing command input through `--json`.
- Typed flags and JSON blobs must not be mixed as part of one public command contract.
- If the API requires a complex object, the CLI must expose explicit flags or subcommands instead of forwarding raw JSON.

#### Command Formatting Rules

- Every canonical CLI command must be written strictly on a single line.
- Multi-line command formatting is not allowed.
- Shell line continuation using `\` is forbidden in canonical documentation, help text, tests, and examples.

Allowed:

```bash
direct dictionaries get-geo-regions --region-ids 225,187 --fields GeoRegionId,GeoRegionName
```

Not allowed:

```bash
direct dictionaries get-geo-regions \
  --region-ids 225,187 \
  --fields GeoRegionId,GeoRegionName
```

#### Flag Design Rules

- List inputs use comma-separated CLI syntax where appropriate.
- Money and bid values are passed in micro-rubles (API-native format). Values below 100,000 trigger a validation hint suggesting the correct scale.
- Selector fields remain explicit flags, for example:
  - `--id`
  - `--campaign-id`
  - `--adgroup-id`
- Nested API structures must be projected into typed flags instead of blob JSON.
- Help text must not advertise JSON as an alternative input path.

#### Datetime Rules

- Datetime parameters must be passed in the format `YYYY-MM-DDTHH:MM:SS`.
- Datetime values must be passed as a single shell token.
- Canonical examples must not use timezone suffixes like `Z`.
- Canonical examples must not use quoted space-separated datetime values.

Use:

```bash
direct changes check-campaigns --timestamp 2026-04-14T00:00:00
```

Do not use:

```bash
direct changes check-campaigns --timestamp 2026-04-14T00:00:00Z
direct changes check-campaigns --timestamp "2026-04-14 00:00:00"
```

#### Documentation Contract

- `README` must use only canonical syntax.
- `README` must use only single-line command examples.
- Canonical examples must not contain `--json`.
- Help output and tests must enforce the same contract.

#### Examples

Valid canonical examples:

```bash
direct campaigns get --ids 1,2,3
direct changes check-campaigns --timestamp 2026-04-14T00:00:00
direct keywordsresearch has-search-volume --keywords "buy laptop,buy desktop"
direct dynamicads set-bids --id 789 --bid 12500000
direct dictionaries get-geo-regions --region-ids 225 --fields GeoRegionId,GeoRegionName
```

Invalid examples:

```bash
direct dictionaries get-geo-regions --json '{"GeoRegionIds":[225]}' --fields GeoRegionId,GeoRegionName
direct dynamicads set-bids --id 789 --bid 12500000 --json '{"StrategyPriority":"HIGH"}'
direct dictionaries get-geo-regions \
  --region-ids 225 \
  --fields GeoRegionId,GeoRegionName
direct changes check-campaigns --timestamp 2026-04-14T00:00:00Z
direct changes check-campaigns --timestamp "2026-04-14 00:00:00"
```

#### Кампании

```bash
# Получить кампании
direct campaigns get
direct campaigns get --status ACTIVE
direct campaigns get --ids 1,2,3 --format table
direct campaigns get --fetch-all --format csv --output campaigns.csv

# Создать (--dry-run покажет запрос без отправки)
direct campaigns add --name "Моя кампания" --start-date 2024-02-01 --type TEXT_CAMPAIGN --budget 1000000000 --setting ADD_METRICA_TAG=YES --search-strategy HIGHEST_POSITION --network-strategy SERVING_OFF --dry-run
direct campaigns add --name "Динамическая кампания" --start-date 2024-02-01 --type DYNAMIC_TEXT_CAMPAIGN --setting ADD_METRICA_TAG=NO --search-strategy HIGHEST_POSITION --network-strategy SERVING_OFF --dry-run
direct campaigns add --name "Смарт-кампания" --start-date 2024-02-01 --type SMART_CAMPAIGN --network-strategy AVERAGE_CPC_PER_FILTER --filter-average-cpc 1000000 --counter-id 123 --dry-run

# Обновление и управление статусом
direct campaigns update --id 12345 --name "Новое название" --status SUSPENDED --budget 100000000 --start-date 2024-02-10 --end-date 2024-03-01
direct campaigns suspend --id 12345
direct campaigns resume --id 12345
direct campaigns archive --id 12345
direct campaigns unarchive --id 12345
direct campaigns delete --id 12345
```

#### Группы объявлений

```bash
direct adgroups get --campaign-ids 1,2,3 --limit 50
direct adgroups add --name "Группа 1" --campaign-id 12345 --region-ids 1,225 --dry-run
direct adgroups add --name "Динамическая группа" --campaign-id 12345 --type DYNAMIC_TEXT_AD_GROUP --region-ids 1,225 --domain-url example.com --dry-run
direct adgroups add --name "Смарт-группа" --campaign-id 12345 --type SMART_AD_GROUP --region-ids 1,225 --feed-id 170 --ad-title-source FEED_NAME --ad-body-source FEED_NAME --dry-run
direct adgroups update --id 67890 --name "Новое название" --status SUSPENDED --region-ids 1,225
direct adgroups delete --id 67890
```

#### Объявления

```bash
direct ads get --campaign-ids 1,2,3
direct ads get --adgroup-ids 45678 --format table
direct ads add --adgroup-id 12345 --type TEXT_AD --title "Заголовок" --text "Текст объявления" --href "https://example.com" --dry-run
direct ads add --adgroup-id 12345 --type TEXT_IMAGE_AD --image-hash abcdefghijklmnopqrst --href "https://example.com" --title "Баннер" --text "Имиджевое объявление" --dry-run
direct ads update --id 99999 --status PAUSED --title "Новый заголовок" --text "Новый текст" --href "https://example.com" --image-hash abcdefghijklmnopqrst
direct ads delete --id 99999
```

#### Ключевые слова

```bash
direct keywords get --campaign-ids 1,2,3
direct keywords add --adgroup-id 12345 --keyword "купить ноутбук" --bid 10500000 --context-bid 5250000 --user-param-1 segment-a --user-param-2 segment-b --dry-run
direct keywords update --id 88888 --keyword "updated keyword text"
direct keywords delete --id 88888
```

#### Отчёты

```bash
# Сформировать отчёт (сохраняется в файл)
direct reports get --type CAMPAIGN_PERFORMANCE_REPORT --from 2024-01-01 --to 2024-01-31 --name "Отчёт за январь" --fields "Date,CampaignId,Clicks,Cost" --format csv --output report.csv
direct reports get --type CUSTOM_REPORT --from 2024-01-01 --to 2024-01-31 --name "Отчёт по целям" --fields "Date,CampaignId,GoalsRoi" --goals 12345,67890 --attribution-models AUTO --format csv --output goals-report.csv

# Список доступных типов отчётов
direct reports list-types
```

Доступные типы: `CAMPAIGN_PERFORMANCE_REPORT`, `ADGROUP_PERFORMANCE_REPORT`, `AD_PERFORMANCE_REPORT`, `CRITERIA_PERFORMANCE_REPORT`, `CUSTOM_REPORT`, `REACH_AND_FREQUENCY_CAMPAIGN_REPORT`, `SEARCH_QUERY_PERFORMANCE_REPORT`

#### Другие ресурсы

```bash
# Справочники и изменения
direct dictionaries get --names Currencies,GeoRegions
direct dictionaries get-geo-regions --name Москва --region-ids 225,187 --exact-names Москва,Санкт-Петербург --fields GeoRegionId,GeoRegionName

# Информация о клиенте
direct clients get --fields ClientId,Login,Currency

# Изменения
direct changes check --campaign-ids 1,2,3 --timestamp 2026-04-14T00:00:00 --fields CampaignIds,AdGroupIds,AdIds,CampaignsStat
direct changes check-campaigns --timestamp 2026-04-14T00:00:00
direct changes check-dictionaries

# Исследование ключевых слов и ретаргетинг
direct keywordsresearch has-search-volume --keywords "купить ноутбук,купить компьютер"
direct retargeting add --name "Список A" --type AUDIENCE --rule "ALL:12345:30|67890:7" --dry-run
direct retargeting update --id 55 --name "Переименованный список" --rule "ANY:12345:30" --dry-run

# Ставки и модификаторы
direct bids get --campaign-ids 123 --fields CampaignId,AdGroupId,KeywordId,Bid
direct bids set --keyword-id 123 --bid 15000000
direct bids set-auto --keyword-id 123 --max-bid 20000000 --position PREMIUMBLOCK --scope SEARCH --dry-run
direct keywordbids set --keyword-id 321 --search-bid 8000000 --network-bid 3000000
direct keywordbids set-auto --keyword-id 321 --target-traffic-volume 100 --increase-percent 10 --bid-ceiling 12500000 --dry-run
direct bidmodifiers get --campaign-ids 123 --fields Id,CampaignId,AdGroupId,Level,Type
direct bidmodifiers add --campaign-id 123 --type DEMOGRAPHICS_ADJUSTMENT --value 150 --gender GENDER_MALE --age AGE_25_34 --dry-run
direct bidmodifiers set --id 99 --value 130 --dry-run

# Канонические многословные группы
direct negativekeywordsharedsets update --id 123 --keywords "foo,bar"
direct audiencetargets get --campaign-ids 123 --fields Id,AdGroupId,RetargetingListId,State,ContextBid
direct audiencetargets add --adgroup-id 100 --retargeting-list-id 200 --bid 12000000 --priority HIGH --dry-run
direct audiencetargets set-bids --id 101 --context-bid 7000000 --priority LOW --dry-run
direct dynamicads add --adgroup-id 33 --name "Webpage A" --condition "URL:CONTAINS_ANY:test|shop" --condition "PAGE_CONTENT:CONTAINS:baz" --bid 3000000 --context-bid 2000000 --priority HIGH --dry-run
direct smartadtargets add --adgroup-id 55 --name "Audience A" --audience ALL_SEGMENTS --condition "CATEGORY_ID:EQUALS:42" --average-cpc 3000000 --average-cpa 4000000 --priority HIGH --available-items-only YES --dry-run
direct smartadtargets update --id 456 --priority HIGH
direct smartadtargets set-bids --id 456 --average-cpc 10500000 --average-cpa 15000000 --priority HIGH
direct dynamicads set-bids --id 789 --bid 12500000 --context-bid 9000000 --priority HIGH

# Общие стратегии ставок
direct strategies get --limit 5
direct strategies add --name "Общая стратегия" --type WbMaximumClicks --params '{"SpendLimit":1000000000,"AverageCpc":30000000}' --dry-run
direct strategies update --id 42 --params '{"AverageCpc":35000000}' --dry-run
direct strategies archive --id 42 --dry-run

# Динамические таргеты по фиду
direct dynamicfeedadtargets get --adgroup-ids 123 --limit 5
direct dynamicfeedadtargets add --adgroup-id 33 --name "Срез фида А" --condition "CATEGORY:EQUALS:shoes" --bid 5000000 --dry-run
direct dynamicfeedadtargets set-bids --id 789 --bid 6500000 --context-bid 4000000 --dry-run

# Расширения, ассеты, фиды и клиенты
direct sitelinks add --sitelink "Docs|https://example.com/docs" --sitelink "Help|https://example.com/help|Desk" --dry-run
direct vcards add --campaign-id 555 --country "Россия" --city "Москва" --company-name "Acme" --work-time 1#5#9#0#18#0 --phone-country-code +7 --phone-city-code 495 --phone-number 1234567 --dry-run
direct adextensions add --callout-text "Free shipping" --dry-run
direct adimages add --name banner.png --image-data BASE64DATA --type ICON --dry-run
direct creatives add --video-id video-id --dry-run
direct feeds add --name "Фид A" --url "https://example.com/feed.xml" --dry-run
direct feeds update --id 18 --name "Фид A v2" --url "https://example.com/feed-v2.xml" --dry-run
direct clients update --client-info "Приоритетный клиент" --phone +70000000000 --notification-email user@example.com --notification-lang EN --email-subscription RECEIVE_RECOMMENDATIONS=YES --setting DISPLAY_STORE_RATING=NO --dry-run
direct --login CLIENT_LOGIN clients update --phone +70000000000 --notification-email user@example.com --dry-run
direct agencyclients add-passport-organization --name "Org" --currency RUB --notification-email ops@example.com --notification-lang EN --no-send-account-news --send-warnings --dry-run
direct agencyclients add-passport-organization-member --passport-organization-login org-login --role CHIEF --invite-email user@example.com --dry-run
direct agencyclients update --client-id 42 --phone +70000000000 --notification-email user@example.com --grant EDIT_CAMPAIGNS=YES --grant IMPORT_XLS=NO --dry-run
```

`direct agencyclients add` runtime-deprecated в Yandex Direct и блокируется CLI. Используйте `direct agencyclients add-passport-organization`.

### Известная неподдерживаемая API-операция

`dynamicads update` unsupported by API. Сервис Яндекс Директа
`dynamictextadtargets` экспортирует `add`, `get`, `delete`, `suspend`,
`resume` и `setBids`, но не экспортирует `update`. Не добавляйте и не
используйте `direct dynamicads update`, пока Яндекс не предоставит реальный
API-метод.

### Форматы вывода

Все команды `get` поддерживают `--format`:

| Формат | Описание |
|--------|----------|
| `json` | JSON (по умолчанию) |
| `table` | Таблица |
| `csv` | CSV |
| `tsv` | TSV |

```bash
direct campaigns get --format table
direct campaigns get --format csv --output campaigns.csv
```

### Пагинация

```bash
direct campaigns get --limit 10    # первые 10 результатов
direct campaigns get --fetch-all   # все страницы
```

### ⚠️ Опасные команды

Следующие команды вносят **необратимые изменения** — используйте осторожно:

| Команда | Эффект |
|---------|--------|
| `campaigns delete --id` | Безвозвратно удаляет кампанию и весь её контент |
| `adgroups delete --id` | Безвозвратно удаляет группу объявлений |
| `ads delete --id` | Безвозвратно удаляет объявление |
| `keywords delete --id` | Безвозвратно удаляет ключевое слово |
| `audiencetargets delete --id` | Безвозвратно удаляет условие подбора аудитории |

Команды, влияющие на показ рекламы: `suspend`, `resume`, `archive`, `unarchive` (доступны для `campaigns`, `ads`), `suspend`, `resume` (также для `keywords`).

Команды, влияющие на ставки и расходы: `bids set`, `keywordbids set`, `bidmodifiers set`.

Используйте `--dry-run` в командах `add` / `update`, чтобы увидеть тело запроса до отправки:

```bash
direct campaigns add --name "Тест" --start-date 2024-01-01 --dry-run
```

### Тестирование

В `tests/` четыре уровня тестов:

| Уровень | Маркер | Сеть | Нужен токен |
|---|---|---|---|
| Юнит / CLI / dry-run | *(без маркера)* | Нет | Нет |
| Read-only интеграция | `-m integration` | Да (prod API, только чтение) | Да |
| Write интеграция | `-m integration_write` | Нет (replay VCR-кассет) | Нет |
| Live draft write интеграция | `-m integration_live_write` | Да при записи, иначе VCR replay | Да + `YANDEX_DIRECT_LIVE_WRITE=1` |

```bash
pip install -e ".[dev]"
pytest                              # быстрый уровень — без токена
pytest -m integration -v            # read-only интеграция (нужен токен)
pytest -m integration_write -v      # replay write-кассет (токен не нужен)
YANDEX_DIRECT_LIVE_WRITE=1 pytest -m integration_live_write -v  # replay live draft-кассеты
YANDEX_DIRECT_LIVE_WRITE=1 pytest -m integration_live_write -v --record-mode=rewrite  # перезапись live draft-кассеты
```

#### Smoke-скрипты команд

Каждая CLI-подкоманда классифицирована в `direct_cli/smoke_matrix.py`.

| Категория | Скрипт | Когда запускать |
|---|---|---|
| SAFE | `scripts/test_safe_commands.sh` | Production smoke-проверки только на чтение; нужны `YANDEX_DIRECT_TOKEN` и `YANDEX_DIRECT_LOGIN` |
| WRITE_SANDBOX | `scripts/test_sandbox_write.sh` | Live sandbox write-проверки; нужны `YANDEX_DIRECT_TOKEN` и `YANDEX_DIRECT_LOGIN`; отчёт печатает `PASS`, `FAIL`, `SANDBOX_LIMITATION` или `NOT_COVERED` для каждой команды |
| DANGEROUS | `scripts/test_dangerous_commands.sh` | Только ручной checklist; специально завершается с кодом 1 |

Текущая поверхность команд:

| Метрика | Количество |
|---|---:|
| WSDL-backed API services | 29 |
| API services с учётом Reports | 30 |
| WSDL operations | 112 |
| CLI groups с `auth` | 39 |
| CLI subcommands с `auth` | 130 |
| API CLI subcommands без `auth` | 126 |

#### Live sandbox write smoke

`WRITE_SANDBOX` smoke — это live-проверка против **sandbox-окружения**
Яндекс Директа. Она не воспроизводит сохранённый HTTP-трафик и не создаёт
новые записи. Запускайте её только когда намеренно хотите обратиться к
`api-sandbox.direct.yandex.ru`:

```bash
set -a && source .env && set +a
scripts/test_sandbox_write.sh
```

Runner выполняет команды matrix через `direct --sandbox ...`, создаёт
временные sandbox prerequisites там, где это безопасно, и удаляет их
best-effort. Отчёт содержит одну строку на каждую команду `WRITE_SANDBOX`:

- `PASS`: команда прошла против live sandbox API.
- `SANDBOX_LIMITATION`: запрос дошёл до API и получил известное ограничение
  sandbox, например коды `8800`, `1000`, `3500` или `5004`.
- `FAIL`: неожиданный CLI/API error.
- `NOT_COVERED`: runner пока не умеет безопасно построить prerequisites.

Один и тот же OAuth-токен работает и для продакшена, и для sandbox; отдельный
sandbox-токен не нужен.

#### Перезапись write-кассет

Уровень `integration_write` в pytest всё ещё воспроизводит сохранённый
write-трафик для регрессионного покрытия. Если вы меняете эти тесты или их
payload и намеренно хотите обновить fixtures, перезаписывайте их отдельно:

```bash
set -a && source .env && set +a        # загрузить YANDEX_DIRECT_TOKEN / LOGIN
pytest -m integration_write -v --record-mode=rewrite
```

После перезаписи **обязательно проверьте YAML-ы на утечку секретов**:

```bash
grep -r "$YANDEX_DIRECT_TOKEN" tests/cassettes/   # должно быть пусто
grep -r "$YANDEX_DIRECT_LOGIN" tests/cassettes/   # должно быть пусто
```

VCR-конфиг в `tests/conftest.py` уже стрипает `Authorization`, `Client-Login`,
куки и любые response-заголовки с подстрокой `login`, но ручная проверка
перед коммитом обязательна.

#### Live write только на черновиках

Уровень `integration_live_write` запускается только вручную и отделен от
sandbox/VCR-тестов. В rewrite-режиме он ходит в production API Яндекс Директа,
но может только создавать одноразовые черновики и удалять ровно те ID, которые
были созданы в этом же тестовом прогоне. Текущее покрытие: guarded create ->
get -> delete для draft-кампании.

Replay закоммиченной кассеты:

```bash
YANDEX_DIRECT_LIVE_WRITE=1 pytest -m integration_live_write -v
```

Перезапись после явного решения проверить live draft-поведение:

```bash
YANDEX_DIRECT_LIVE_WRITE=1 pytest -m integration_live_write -v --record-mode=rewrite
```

В этот уровень нельзя добавлять тесты, которые принимают внешние ID,
возобновляют/останавливают/архивируют существующие ресурсы, меняют ставки или
трогают кампании, которые могут показываться.

### Публикация на PyPI

Сборка, проверка и загрузка на PyPI:

```bash
pip install -e ".[dev]"
scripts/release_pypi.sh testpypi   # загрузить на TestPyPI
scripts/release_pypi.sh pypi       # загрузить на PyPI
scripts/release_pypi.sh all        # оба
```

Скрипт читает credentials из `.env`:

```dotenv
TWINE_USERNAME=__token__
TEST_PYPI_TOKEN=pypi-...
PYPI_TOKEN=pypi-...
```

#### Области действия токенов PyPI

API-токены PyPI могут быть **account-wide** (на весь аккаунт) или **project-scoped** (на конкретный проект):

- **Project-scoped** токены работают только для конкретного проекта. Токен от `telethon-cli` не может загрузить `direct-cli` — будет **403 Forbidden**.
- **Account-wide** токены позволяют загружать в любой проект аккаунта.
- Для **первой публикации** нового проекта **необходим** account-wide токен (project-scoped нельзя создать, пока проект не зарегистрирован на PyPI).
- После первой успешной загрузки создайте project-scoped токен на https://pypi.org/manage/account/token/ и замените account-wide токен в `.env`.

Перед каждым релизом обновите `version` в `pyproject.toml` — PyPI отклоняет дубли версий.

### Лицензия

MIT
