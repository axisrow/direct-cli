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
direct auth login --profile agency1 --format json
direct auth login --code abc123 --profile agency1
printf '%s\n' abc123 | direct auth login --code - --profile agency1
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
- In a non-interactive shell, run `direct auth login --profile NAME` first, then finish with `direct auth login --code - --profile NAME` and pass the browser code on stdin.
- `direct auth login --code CODE --profile NAME` remains supported for compatibility, but automation should use `--code -` to avoid exposing the code in process arguments.
- If the first non-interactive step includes `--client-secret`, the secret is remembered for the matching completion step.
- If a profile already stores a confidential OAuth client, `direct auth login --code CODE --profile NAME` reuses the saved `client_id` and `client_secret`.
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

> **Tests use the inverted order.** Live-API test suites (e.g. `tests/test_v4_live_contracts.py`) read `YANDEX_DIRECT_TOKEN` / `YANDEX_DIRECT_LOGIN` from the environment first, only then fall back to the active `direct auth` profile, and skip the test if neither is set. This is intentional: a developer machine with an active profile must not silently hit production on a plain `pytest` invocation. See `CLAUDE.md` for the contract.

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

### V4 Live Tags

Campaign tags are managed as `{TagID, Tag}` pairs. Use `TagID=0` to create a
new campaign tag. Banner/ad tags are assigned by campaign tag IDs. Update
methods replace the full tag list for the target campaign or banner, so pass
existing tags again if they must remain assigned. Ad group tags are filter-only
through `direct adgroups get --tag-ids/--tags`; this release does not add ad
group tag mutation commands.

```bash
direct v4tags get-campaigns --campaign-ids 3193279,1634563
direct v4tags get-banners --banner-ids 2571700,2571745
direct v4tags get-banners --campaign-ids 3193279
direct v4tags update-campaigns --campaign-id 3193279 --tag 0=akapulko --tag 16590=orange --dry-run
direct v4tags update-banners --banner-ids 2571700,2571745 --tag-ids 16590,16734 --dry-run
direct v4tags update-banners --banner-ids 2571700 --clear-tags --dry-run
```

### V4 Live Events

```bash
direct v4events get-events-log --from 2026-04-14T00:00:00 --to 2026-04-15T00:00:00
direct v4events get-events-log --from 2026-04-14T00:00:00 --to 2026-04-15T00:00:00 --currency RUB --limit 100 --offset 0 --format table
```

### V4 Live Wordstat Reports

Wordstat reports are asynchronous. Direct CLI makes exactly one API call per
command and does not poll automatically; repeat `list-reports` or `get-report`
yourself until the report is ready.

```bash
direct v4wordstat create-report --phrases "buy laptop,buy desktop" --geo-ids 213
direct v4wordstat list-reports --format table
direct v4wordstat get-report --report-id 123 --format table
direct v4wordstat delete-report --report-id 123
```

### V4 Live Budget Forecasts

Budget forecasts are asynchronous. Direct CLI makes exactly one API call per
command and does not poll automatically; repeat `list` or `get` yourself until
the forecast is ready.

```bash
direct v4forecast create --phrases "buy laptop,buy desktop" --geo-ids 213 --currency RUB
direct v4forecast list --format table
direct v4forecast get --forecast-id 123 --format table
direct v4forecast delete --forecast-id 123
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
`YANDEX_DIRECT_FINANCE_TOKEN`, and `YANDEX_DIRECT_OPERATION_NUM`.
`transfer-money` and `pay-campaigns` are dry-run-only in this release and
always require `--dry-run`; `create-invoice` can be sent live when `--dry-run`
is omitted. Dry-run output masks the financial token.

```bash
direct v4finance get-clients-units --logins client-login,other-client --format table
direct v4finance get-credit-limits --master-token MASTER_TOKEN --operation-num 123 --finance-login agency-login
direct v4finance create-invoice --payment 123=100.50 --payment 456=25 --currency RUB --master-token MASTER_TOKEN --operation-num 124 --finance-login agency-login --dry-run
direct v4finance check-payment --custom-transaction-id A123456789012345678901234567890B
direct v4finance transfer-money --from-campaign-id 123 --to-campaign-id 456 --amount 100.50 --currency RUB --master-token MASTER_TOKEN --operation-num 123 --finance-login agency-login --dry-run
direct v4finance pay-campaigns --campaign-ids 123,456 --amount 100.50 --currency RUB --contract-id CONTRACT_ID --pay-method Bank --master-token MASTER_TOKEN --operation-num 123 --finance-login agency-login --dry-run
```

### V4 Live Shared Account

`EnableSharedAccount` accepts one client `Login` (agencies only).
`AccountManagement` exposes the five official v4 Live actions:
`Get`, `Update`, `Deposit`, `Invoice`, and `TransferMoney`. `Get` is
read-only and runs against production without `--dry-run`. `Update`,
`Deposit`, `Invoice`, and `TransferMoney` are mutations: they require
`--dry-run` in production and can be sent live only with top-level
`--sandbox`. `Deposit`, `Invoice`, and `TransferMoney` are financial
operations that need `--finance-token` (or `--master-token` +
`--operation-num` + `--finance-login`); dry-run output masks the
financial token.

```bash
direct v4account enable-shared-account --client-login client-login --dry-run
direct v4account account-management --action Get
direct v4account account-management --action Get --logins client-a,client-b
direct v4account account-management --action Get --account-ids 1327944,1327945
direct v4account account-management --action Update --account-id 1327944 --day-budget 100.50 --spend-mode Default --money-in-sms Yes --money-out-sms No --email ops@example.com --money-warning-value 25 --dry-run
direct v4account account-management --action Deposit --payment 1327944=100.50 --currency RUB --master-token MASTER_TOKEN --operation-num 124 --finance-login agency-login --dry-run
direct v4account account-management --action Deposit --payment 1327944=100.50 --currency RUB --origin Overdraft --contract CONTRACT_ID --master-token MASTER_TOKEN --operation-num 125 --finance-login agency-login --dry-run
direct v4account account-management --action Invoice --payment 1327944=100.50 --currency RUB --master-token MASTER_TOKEN --operation-num 126 --finance-login agency-login --dry-run
direct v4account account-management --action TransferMoney --from-account-id 1327944 --to-account-id 1327945 --amount 50.00 --currency RUB --master-token MASTER_TOKEN --operation-num 127 --finance-login agency-login --dry-run
direct --sandbox v4account enable-shared-account --client-login client-login
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

Not allowed: splitting a canonical `direct ...` command over multiple shell
lines with `\`.

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

Do not use: a timestamp with a `Z` suffix, or a quoted timestamp that contains
a space between the date and time.

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

Invalid examples include command lines that pass raw JSON flags, use shell
line continuations, add timezone suffixes to CLI datetimes, or quote
space-separated datetime values.

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

# CPA strategy (single goal): --goal-id required, --average-cpa / --bid-ceiling are micro-rubles
direct campaigns add --name "CPA Campaign" --start-date 2026-06-01 --type TEXT_CAMPAIGN --search-strategy AVERAGE_CPA --network-strategy SERVING_OFF --goal-id 1234567 --average-cpa 500000000 --bid-ceiling 1000000000 --counter-ids 111,222 --dry-run

# Multi-goal CPA via PriorityGoals (goal_id:value pairs, WSDL PriorityGoalsItem)
direct campaigns add --name "Multi-Goal CPA" --start-date 2026-06-01 --type TEXT_CAMPAIGN --search-strategy AVERAGE_CPA_MULTIPLE_GOALS --network-strategy SERVING_OFF --priority-goals 1234567:80,9876543:20 --bid-ceiling 1000000000 --dry-run

# TextCampaign optional controls
direct campaigns add --name "Text Controls" --start-date 2026-06-01 --type TEXT_CAMPAIGN --counter-ids 111,222 --relevant-keywords-budget-percent 40 --relevant-keywords-mode OPTIMAL --attribution-model AUTO --negative-keyword-shared-set-ids 10,11 --dry-run
direct campaigns update --id 12345 --type TEXT_CAMPAIGN --setting ADD_METRICA_TAG=NO --priority-goals 1234567:80:YES --tracking-params "utm_source=direct" --dry-run
direct campaigns add --name "Package Text" --start-date 2026-06-01 --type TEXT_CAMPAIGN --package-strategy-id 700 --package-platform-search-result YES --package-platform-product-gallery YES --package-platform-network NO --dry-run
direct campaigns add --name "Unified Controls" --start-date 2026-06-01 --type UNIFIED_CAMPAIGN --setting ADD_METRICA_TAG=YES --counter-ids 111,222 --priority-goals 1234567:80:YES --tracking-params "utm_source=direct" --attribution-model AUTO --negative-keyword-shared-set-ids 10,11 --dry-run
direct campaigns add --name "Unified Package" --start-date 2026-06-01 --type UNIFIED_CAMPAIGN --package-strategy-id 700 --package-platform-search-result YES --package-platform-product-gallery YES --package-platform-maps NO --package-platform-search-organization-list YES --package-platform-network YES --dry-run

# Notification (Sms/Email) and TimeTargeting via typed CLI flags
direct campaigns add --name "Notify+Schedule" --start-date 2026-06-01 --type TEXT_CAMPAIGN --search-strategy HIGHEST_POSITION --network-strategy SERVING_OFF --notification-email ops@example.com --notification-send-warnings YES --time-targeting-schedule 1A0123456789ABCDEFGHIJKL --consider-working-weekends YES --dry-run

# TrackingParams (campaign subtype UTM / tracking query string)
direct campaigns add --name "UTM" --start-date 2026-06-01 --type TEXT_CAMPAIGN --tracking-params "utm_source=direct&utm_campaign={campaign_id}" --dry-run

# Update / lifecycle
direct campaigns update --id 12345 --name "New Name" --status SUSPENDED --budget 100000000 --start-date 2024-02-10 --end-date 2024-03-01
direct campaigns update --id 12345 --type TEXT_CAMPAIGN --tracking-params "utm_source=direct&utm_medium=cpc" --dry-run
direct campaigns suspend --id 12345
direct campaigns resume --id 12345
direct campaigns archive --id 12345
direct campaigns unarchive --id 12345
direct campaigns delete --id 12345
```

#### Ad Groups

```bash
direct adgroups get --campaign-ids 1,2,3 --limit 50
direct adgroups add --name "Group 1" --campaign-id 12345 --region-ids 1,225 --negative-keywords "repair,used" --tracking-params "utm_source=direct" --dry-run
direct adgroups add --name "Text Feed Group" --campaign-id 12345 --region-ids 1,225 --feed-id 170 --feed-category-ids 10,11 --dry-run
direct adgroups add --name "Dynamic Group" --campaign-id 12345 --type DYNAMIC_TEXT_AD_GROUP --region-ids 1,225 --domain-url example.com --autotargeting-category EXACT=YES --dry-run
direct adgroups add --name "Dynamic Feed Group" --campaign-id 12345 --type DYNAMIC_TEXT_FEED_AD_GROUP --region-ids 1,225 --feed-id 170 --autotargeting-category EXACT=YES --dry-run
direct adgroups add --name "CPM Keywords Group" --campaign-id 12345 --type CPM_BANNER_KEYWORDS_AD_GROUP --region-ids 1,225 --dry-run
direct adgroups add --name "CPM User Profile Group" --campaign-id 12345 --type CPM_BANNER_USER_PROFILE_AD_GROUP --region-ids 1,225 --dry-run
direct adgroups add --name "CPM Video Group" --campaign-id 12345 --type CPM_VIDEO_AD_GROUP --region-ids 1,225 --dry-run
direct adgroups add --name "Smart Group" --campaign-id 12345 --type SMART_AD_GROUP --region-ids 1,225 --feed-id 170 --ad-title-source FEED_NAME --ad-body-source FEED_NAME --dry-run
direct adgroups add --name "Unified Group" --campaign-id 12345 --type UNIFIED_AD_GROUP --region-ids 1,225 --offer-retargeting YES --dry-run
direct adgroups add --name "Mobile App Group" --campaign-id 12345 --type MOBILE_APP_AD_GROUP --region-ids 1,225 --store-url https://apps.apple.com/app/id123456789 --target-device-types DEVICE_TYPE_MOBILE,DEVICE_TYPE_TABLET --target-carrier WI_FI_AND_CELLULAR --target-operating-system-version 14.0 --dry-run
direct adgroups update --id 67890 --negative-keyword-shared-set-ids 10,11 --tracking-params "utm_source=direct"
direct adgroups update --id 67890 --feed-id 170 --feed-category-ids 10,11
direct adgroups update --id 67890 --domain-url example.com --autotargeting-settings-exact YES --autotargeting-settings-without-brands YES --dry-run
direct adgroups update --id 67890 --dynamic-feed --autotargeting-category EXACT=YES --dry-run
direct adgroups update --id 67890 --target-device-types DEVICE_TYPE_TABLET --target-carrier WI_FI_ONLY --target-operating-system-version 13.0
direct adgroups update --id 67890 --ad-title-source FEED_NAME --ad-body-source FEED_DESCRIPTION
direct adgroups update --id 67890 --offer-retargeting NO
direct adgroups delete --id 67890
```

#### Ads

```bash
direct ads get --campaign-ids 1,2,3
direct ads get --adgroup-ids 45678 --format table
direct ads add --adgroup-id 12345 --type TEXT_AD --title "Title" --text "Ad text" --href "https://example.com" --dry-run
direct ads add --adgroup-id 12345 --type TEXT_AD --title "Title" --text "Ad text" --href "https://example.com" --title2 "Second headline" --display-url-path "deals" --mobile YES --vcard-id 111 --sitelink-set-id 222 --turbo-page-id 333 --ad-extensions "444,555" --dry-run
direct ads add --adgroup-id 12345 --type TEXT_AD --title "Title" --text "Ad text" --href "https://example.com" --final-url "https://final.example.com" --video-extension-creative-id 777 --price-extension-price 123.45 --price-extension-price-qualifier FROM --price-extension-price-currency RUB --business-id 777 --prefer-vcard-over-business NO --erir-ad-description "Text ad object" --dry-run
direct ads add --adgroup-id 12345 --type RESPONSIVE_AD --texts "Text one,Text two" --titles "Title one,Title two" --image-hashes hash1,hash2 --video-extension-ids 111,222 --href "https://example.com" --price-extension-price 123.45 --price-extension-price-qualifier FROM --price-extension-price-currency RUB --business-id 777 --erir-ad-description "Responsive ad object" --dry-run
direct ads add --adgroup-id 12345 --type SHOPPING_AD --feed-id 170 --default-texts "Default product text" --sitelink-set-id 222 --ad-extensions "333,444" --business-id 777 --feed-filter-condition "CATEGORY:EQUALS_ANY:shoes|boots" --title-sources NAME,BRAND --text-sources DESCRIPTION --dry-run
direct ads add --adgroup-id 12345 --type LISTING_AD --feed-id 171 --default-texts "Default listing text" --feed-filter-condition "CATEGORY:EQUALS_ANY:appliances" --title-sources TITLE --text-sources DESCRIPTION --dry-run
direct ads add --adgroup-id 12345 --type TEXT_AD_BUILDER_AD --creative-id 123 --href "https://example.com" --turbo-page-id 456 --erir-ad-description "Builder ad object" --dry-run
direct ads add --adgroup-id 12345 --type MOBILE_APP_AD_BUILDER_AD --creative-id 123 --tracking-url "https://track.example.com" --erir-ad-description "Mobile builder ad" --dry-run
direct ads add --adgroup-id 12345 --type CPM_BANNER_AD_BUILDER_AD --creative-id 123 --href "https://example.com" --tracking-pixels "https://pixel.example.com/a,https://pixel.example.com/b" --dry-run
direct ads add --adgroup-id 12345 --type TEXT_IMAGE_AD --image-hash abcdefghijklmnopqrst --href "https://example.com" --turbo-page-id 555 --final-url "https://final.example.com" --erir-ad-description "Image ad object" --dry-run
direct ads add --adgroup-id 12345 --type DYNAMIC_TEXT_AD --text "Dynamic ad text" --image-hash abcdefghijklmnopqrst --vcard-id 111 --sitelink-set-id 222 --ad-extensions "333,444" --dry-run
direct ads add --adgroup-id 12345 --type MOBILE_APP_AD --title "Install app" --text "App promo text" --action INSTALL --tracking-url "https://track.example.com" --mobile-app-feature PRICE=YES --video-extension-creative-id 777 --erir-ad-description "Mobile app object" --dry-run
direct ads add --adgroup-id 12345 --type MOBILE_APP_IMAGE_AD --image-hash abcdefghijklmnopqrst --tracking-url "https://track.example.com" --erir-ad-description "Mobile image ad" --dry-run
direct ads add --adgroup-id 12345 --type SMART_AD_BUILDER_AD --logo-extension-hash logoabcdefghijklmnop --dry-run
direct ads update --id 99999 --type TEXT_AD --title "New Title" --text "New text" --href "https://example.com"
direct ads update --id 99999 --type TEXT_AD --image-hash abcdefghijklmnopqrst
direct ads update --id 99999 --type TEXT_AD --title2 "New second headline" --vcard-id 222
direct ads update --id 99999 --type TEXT_AD --callouts-add "111,222" --callouts-remove "333"
direct ads update --id 99999 --type TEXT_AD --callouts-set "444,555"
direct ads update --id 99999 --type TEXT_AD --video-extension-creative-id 777 --price-extension-price 123.45 --price-extension-price-qualifier FROM --price-extension-price-currency RUB
direct ads update --id 99999 --type TEXT_AD --final-url "https://final.example.com" --age-label AGE_18 --business-id 777 --prefer-vcard-over-business NO --erir-ad-description "Text ad object"
direct ads update --id 99999 --type DYNAMIC_TEXT_AD --text "Updated dynamic text" --callouts-add "111,222"
direct ads update --id 99999 --type MOBILE_APP_AD --mobile-app-feature PRICE=YES --mobile-app-feature CUSTOMER_RATING=NO --video-extension-creative-id 777 --erir-ad-description "Mobile app object"
direct ads update --id 99999 --type RESPONSIVE_AD --texts "Text one,Text two" --titles "Title one,Title two" --image-hashes hash1,hash2 --video-extension-ids 111,222 --href "https://example.com" --price-extension-price 123.45 --price-extension-price-qualifier FROM --price-extension-price-currency RUB
direct ads update --id 99999 --type TEXT_IMAGE_AD --final-url "https://final.example.com" --erir-ad-description "Image ad object"
direct ads update --id 99999 --type SHOPPING_AD --sitelink-set-id 222 --callouts-set "444,555" --business-id 777 --feed-filter-condition "CATEGORY:EQUALS_ANY:shoes|boots" --title-sources NAME,BRAND --text-sources DESCRIPTION --default-texts "Default product text"
direct ads update --id 99999 --type MOBILE_APP_IMAGE_AD --image-hash abcdefghijklmnopqrst --tracking-url "https://track.example.com" --erir-ad-description "Mobile image ad"
direct ads update --id 99999 --type TEXT_AD_BUILDER_AD --creative-id 123 --creative-erir-ad-description "Creative object" --href "https://example.com" --turbo-page-id 456
direct ads update --id 99999 --type SMART_AD_BUILDER_AD --logo-extension-hash logoabcdefghijklmnop --erir-ad-description "Smart builder ad"
direct ads update --id 99999 --type CPM_BANNER_AD_BUILDER_AD --creative-id 123 --href "https://example.com" --tracking-pixels "https://pixel.example.com/a,https://pixel.example.com/b"
direct ads delete --id 99999
```

Available TEXT_AD typed flags for `ads add` / `ads update`: `--title`, `--text`,
`--href`, `--image-hash`, `--title2`, `--display-url-path`, `--vcard-id`,
`--sitelink-set-id`, `--turbo-page-id`, `--final-url`,
`--video-extension-creative-id`, `--price-extension-*`, `--business-id`,
`--prefer-vcard-over-business`, and `--erir-ad-description`. For `ads add`,
`TextAd.PriceExtension` requires `--price-extension-price`,
`--price-extension-price-qualifier`, and `--price-extension-price-currency`
when any price-extension flag is used. `ads update` additionally exposes
`--callouts-add`, `--callouts-remove`, and `--callouts-set` for managing the
`TextAdUpdateBase.CalloutSetting` (`ext:AdExtensionSetting`) field on an
existing ad — `--callouts-set` replaces the whole callout list and is mutually
exclusive with the incremental `--callouts-add` / `--callouts-remove` pair.
Price-extension values are human-readable money amounts and are converted to
the Yandex Direct API long-unit format internally. `ads update` also supports
`--age-label`.
`--mobile` (default `NO`) and `--ad-extensions` are `ads add`-only —
`TextAdUpdate` does not contain `Mobile`, and on update ad-extensions are
managed through the `--callouts-*` flags above. TEXT_IMAGE_AD additionally
accepts `--turbo-page-id`, `--final-url`, and `--erir-ad-description`.
DYNAMIC_TEXT_AD add requires `--text` and supports `--image-hash`,
`--vcard-id`, `--sitelink-set-id`, and `--ad-extensions`; update supports
`--text`, `--image-hash`, `--vcard-id`, `--sitelink-set-id`, and
`--callouts-*`.
RESPONSIVE_AD `ads add` uses `--texts` and `--titles` as required
comma-separated lists and also requires `--href`, `--business-id`, or both.
Optional creation flags include `--image-hashes`, `--video-extension-ids`,
`--age-label`, `--display-url-path`, `--sitelink-set-id`, `--ad-extensions`,
`--price-extension-*`, and `--erir-ad-description`.
SHOPPING_AD and LISTING_AD `ads add` require `--feed-id` and one
`--default-texts` value. Optional creation flags include `--sitelink-set-id`,
`--ad-extensions`, `--business-id`, repeatable `--feed-filter-condition`
(`OPERAND:OPERATOR:ARG1|ARG2`), `--title-sources`, and `--text-sources`.
Non-SMART AdBuilder add subtypes require `--creative-id`. TEXT_AD_BUILDER_AD,
CPC_VIDEO_AD_BUILDER_AD, CPM_BANNER_AD_BUILDER_AD, and
CPM_VIDEO_AD_BUILDER_AD require `--href`, `--turbo-page-id`, or both. Mobile app
builder subtypes use `--tracking-url`. CPM builder subtypes also support
`--tracking-pixels`; non-SMART AdBuilder add subtypes support
`--erir-ad-description`.
MOBILE_APP_AD add requires `--title`, `--text`, and `--action`; optional add
fields include `--mobile-app-feature FEATURE=YES|NO`,
`--video-extension-creative-id`, and `--erir-ad-description`. MOBILE_APP_IMAGE_AD
add requires `--image-hash`; add/update support `--tracking-url` and
`--erir-ad-description`.
RESPONSIVE_AD update supports `--texts`, `--titles`, `--image-hashes`,
`--video-extension-ids`, `--href`, `--age-label`, `--display-url-path`,
`--sitelink-set-id`, `--callouts-*`, `--price-extension-*`, `--business-id`,
and `--erir-ad-description`.
SHOPPING_AD and LISTING_AD update support `--sitelink-set-id`,
`--callouts-*`, `--business-id`, repeatable `--feed-filter-condition`
(`OPERAND:OPERATOR:ARG1|ARG2`), `--title-sources`, `--text-sources`, and
`--default-texts`.
MOBILE_APP_IMAGE_AD update supports `--image-hash`, `--tracking-url`, and
`--erir-ad-description`.
SMART_AD_BUILDER_AD add supports `--logo-extension-hash`.
AdBuilder update subtypes support `--creative-id`, `--creative-erir-ad-description`,
`--erir-ad-description`, and subtype-specific `--final-url`, `--href`,
`--turbo-page-id`, `--tracking-url`, and `--tracking-pixels`. SMART_AD_BUILDER_AD
update supports `--logo-extension-hash` and `--erir-ad-description`.

#### Keywords

```bash
direct keywords get --campaign-ids 1,2,3
direct keywords add --adgroup-id 12345 --keyword "buy laptop" --bid 10500000 --context-bid 5250000 --user-param-1 segment-a --user-param-2 segment-b --dry-run
direct keywords add --adgroup-id 12345 --keyword "---autotargeting" --autotargeting-search-bid-is-auto YES --priority HIGH --autotargeting-category EXACT=YES --autotargeting-category BROADER=NO --autotargeting-brand-option WITHOUT_BRANDS=YES --dry-run
direct keywords add --adgroup-id 12345 --keyword "---autotargeting" --autotargeting-settings-exact YES --autotargeting-settings-narrow NO --autotargeting-settings-without-brands YES --dry-run
direct keywords update --id 88888 --keyword "updated keyword text"
direct keywords update --id 88888 --autotargeting-category EXACT=YES --autotargeting-category BROADER=NO --autotargeting-brand-option WITHOUT_BRANDS=YES
direct keywords update --id 88888 --autotargeting-settings-broader YES --autotargeting-settings-with-competitors-brand NO
direct keywords delete --id 88888
```

**Batch keyword upload** (CLI auto-chunks to the API limit of 10 per request):

```bash
# From a JSONL file (one keyword object per line)
direct keywords add --adgroup-id 12345 --from-file keywords.jsonl

# Inline JSON array
direct keywords add --keywords-json '[{"Keyword":"buy laptop","Bid":10000000},{"Keyword":"buy desktop"}]'
```

Example `keywords.jsonl`:

```jsonl
{"Keyword":"buy laptop","Bid":10000000,"UserParam1":"src=ad1"}
{"Keyword":"buy desktop","ContextBid":5000000}
{"Keyword":"купить ноутбук","AdGroupId":99999}
```

- Row keys use WSDL CamelCase: `Keyword`, `AdGroupId`, `Bid`, `ContextBid`, `UserParam1`, `UserParam2`.
- Autotargeting row fields are intentionally not accepted in batch mode; use single-item typed flags such as `--autotargeting-search-bid-is-auto`, `--priority`, `--autotargeting-category`, `--autotargeting-brand-option`, or `--autotargeting-settings-*`.
- `--adgroup-id` provides the default group ID; rows can override it via per-row `AdGroupId`.
- Each effective row must resolve `Keyword` and `AdGroupId`; unknown fields are rejected with the row number.
- API limit: 10 items per `keywords.add` request — see [Yandex Direct docs](https://yandex.ru/dev/direct/doc/dg/objects/keyword.html). The CLI sends as many chunks as needed and merges `AddResults`.
- API limit: 200 keywords per ad group. The CLI prints a warning if any `AdGroupId` in the input exceeds it; the API rejects the excess as per-item errors.
- Item-level errors from the API do not abort the batch; the merged output includes successes and per-item errors.
- If a chunk fails with a network-level error mid-batch, already-created Ids are printed to stderr (`Partial success before failure`) so a retry doesn't duplicate them.
- `--dry-run` shows the first chunk's payload plus `{chunks, totalItems, chunkSize}`.

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
direct retargeting add --name "List A" --description "High intent users" --type AUDIENCE --rule "ALL:12345:30|67890:7" --dry-run
direct retargeting update --id 55 --name "Renamed" --description "Updated note" --rule "ANY:12345:30" --dry-run

# Bids and modifiers
direct bids get --campaign-ids 123 --fields CampaignId,AdGroupId,KeywordId,Bid
direct bids set --keyword-id 123 --bid 15000000
direct bids set --campaign-id 123 --context-bid 9000000 --autotargeting-search-bid-is-auto YES --priority HIGH
direct bids set-auto --keyword-id 123 --max-bid 20000000 --position PREMIUMBLOCK --scope SEARCH --dry-run
direct keywordbids set --adgroup-id 321 --search-bid 8000000 --network-bid 3000000 --autotargeting-search-bid-is-auto NO --priority NORMAL
direct keywordbids set-auto --keyword-id 321 --target-traffic-volume 100 --increase-percent 10 --bid-ceiling 12500000 --dry-run
direct bidmodifiers get --campaign-ids 123 --fields Id,CampaignId,AdGroupId,Level,Type
direct bidmodifiers add --campaign-id 123 --type DEMOGRAPHICS_ADJUSTMENT --value 150 --gender GENDER_MALE --age AGE_25_34 --dry-run
direct bidmodifiers add --campaign-id 123 --type MOBILE_ADJUSTMENT --value 120 --operating-system-type IOS --dry-run
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
direct strategies add --name "Shared Clicks" --type WbMaximumClicks --weekly-spend-limit 1000000000 --bid-ceiling 30000000 --dry-run
direct strategies add --name "Custom Period Clicks" --type WbMaximumClicks --custom-period-spend-limit 1000000000 --custom-period-start-date 2026-06-01 --custom-period-end-date 2026-06-30 --custom-period-auto-continue YES --dry-run
direct strategies add --name "Exploration CPA" --type AverageCpa --average-cpa 4000000 --goal-id 123 --minimum-exploration-budget 200000000 --dry-run
direct strategies add --name "CRR Goal Values" --type AverageCrr --average-crr 10 --goal-id 123 --priority-goal 123:2000000:YES --dry-run
direct strategies update --id 42 --type WbMaximumClicks --weekly-spend-limit 35000000 --dry-run
direct strategies update --id 42 --type WbMaximumClicks --custom-period-spend-limit 35000000 --custom-period-start-date 2026-07-01 --custom-period-end-date 2026-07-31 --custom-period-auto-continue NO --dry-run
direct strategies update --id 42 --type MaxProfit --minimum-exploration-budget 0 --dry-run
direct strategies update --id 42 --priority-goal 123:2000000:YES --dry-run
direct strategies archive --id 42 --dry-run

# Dynamic feed ad targets
direct dynamicfeedadtargets get --adgroup-ids 123 --limit 5
direct dynamicfeedadtargets add --adgroup-id 33 --name "Feed slice A" --condition "CATEGORY:EQUALS:shoes" --bid 5000000 --dry-run
direct dynamicfeedadtargets set-bids --id 789 --bid 6500000 --context-bid 4000000 --dry-run

# Extensions, assets, feeds, and clients
direct sitelinks add --sitelink "Docs|https://example.com/docs|API docs|12345" --sitelink "Help|https://example.com/help|Desk" --dry-run
direct vcards add --campaign-id 555 --country "Russia" --city "Moscow" --company-name "Acme" --work-time 1#5#9#0#18#0 --phone-country-code +7 --phone-city-code 495 --phone-number 1234567 --instant-messenger-client telegram --instant-messenger-login acme_support --point-on-map-x 37.6173 --point-on-map-y 55.7558 --point-on-map-x1 37.60 --point-on-map-y1 55.74 --point-on-map-x2 37.63 --point-on-map-y2 55.77 --dry-run
direct adextensions add --callout-text "Free shipping" --dry-run
direct adimages add --name banner.png --image-data BASE64DATA --type ICON --dry-run
direct creatives add --video-id video-id --dry-run
direct feeds add --name "Feed A" --url "https://example.com/feed.xml" --business-type RETAIL --remove-utm-tags YES --feed-login feedbot --dry-run
direct feeds add --name "Feed File" --file-feed-path ./feed.xml --business-type RETAIL --dry-run
direct feeds update --id 18 --name "Feed A v2" --url "https://example.com/feed-v2.xml" --remove-utm-tags NO --clear-feed-login --clear-feed-password --dry-run
direct feeds update --id 18 --file-feed-path ./feed-v2.xml --file-feed-filename feed-v2.xml --dry-run
direct clients update --client-info "Priority client" --phone +70000000000 --notification-email user@example.com --notification-lang EN --email-subscription RECEIVE_RECOMMENDATIONS=YES --setting DISPLAY_STORE_RATING=NO --dry-run
direct clients update --erir-organization-name "Advertiser LLC" --erir-organization-kpp 770101001 --erir-organization-epay-number epay123 --erir-organization-reg-number 1027700132195 --erir-organization-oksm-number 643 --erir-organization-okved-code 62.01 --dry-run
direct clients update --erir-contract-number C-2026-01 --erir-contract-date 2026-01-15 --erir-contract-type CONTRACT --erir-contract-action-type COMMERCIAL --erir-contract-subject-type REPRESENTATION --erir-contract-is-agency-payment NO --erir-contract-price-amount 120000.5 --erir-contract-price-including-vat YES --dry-run
direct clients update --erir-contragent-name "Counterparty LLC" --erir-contragent-kpp 770201001 --erir-contragent-phone +70000000001 --erir-contragent-epay-number epay456 --erir-contragent-reg-number 1027700132196 --erir-contragent-oksm-number 643 --erir-contragent-tin-type LEGAL --erir-contragent-tin 1234567890 --dry-run
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

### API Errors

Yandex Direct can return a successful HTTP response that still contains
item-level `Errors` for one object. Direct CLI treats those responses as
failed operations: it exits non-zero and prints the error code, message, and
details.

Code `8800` with `Object not found` usually means the object is not available
under the current `Client-Login` or account. Check the selected `--login`,
`YANDEX_DIRECT_LOGIN`, or auth profile before retrying.

### Testing

Four tiers of tests live under `tests/`:

| Tier | Marker | Network | Token required |
|---|---|---|---|
| Unit / CLI wiring / dry-run | *(none)* | No | No |
| Read-only integration | `-m integration` | Yes (production API, read-only) | Yes |
| Write integration | `-m integration_write` | No (replays VCR cassettes) | No |
| Live draft write integration (v5) | `-m integration_live_write` | Yes when recording, otherwise VCR replay | Yes + `YANDEX_DIRECT_LIVE_WRITE=1` |
| v4 live read | `-m v4_live_read` | Yes (production v4 JSON API, read-only) | Yes |
| v4 live account-level report write (opt-in) | `-k _opt_in_write` in `tests/test_v4_live_contracts.py` | Yes (production v4) | Yes + `YANDEX_DIRECT_V4_LIVE_REPORT_WRITE=1` |

```bash
pip install -e ".[dev]"
pytest                              # fast tier — no token
pytest -m integration -v            # read-only integration tests (needs token)
pytest -m integration_write -v      # write cassette replay (no token needed)
YANDEX_DIRECT_LIVE_WRITE=1 pytest -m integration_live_write -v  # live draft cassette replay (v5)
YANDEX_DIRECT_LIVE_WRITE=1 pytest -m integration_live_write -v --record-mode=rewrite  # re-record live draft cassette
YANDEX_DIRECT_V4_LIVE_REPORT_WRITE=1 pytest tests/test_v4_live_contracts.py -k _opt_in_write -v  # v4 wordstat/forecast account-level lifecycle
```

The v4 account-level write tier (`YANDEX_DIRECT_V4_LIVE_REPORT_WRITE=1`) creates real Wordstat and forecast reports in the production account and deletes them in the same run. There are **no cassettes** — these tests run against live API only. Created IDs are tracked in `~/.direct-cli/test-orphans.json` so that if the run is interrupted between create and delete, the next invocation will retry the cleanup automatically (see `tests/_orphan_store.py`).

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
| CLI groups including `auth` | 40 |
| CLI subcommands including `auth` | 144 |
| API CLI subcommands excluding `auth` | 140 |

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

For `v4account` sandbox smoke, `enable-shared-account` uses
`YANDEX_DIRECT_V4ACCOUNT_CLIENT_LOGIN` or falls back to `YANDEX_DIRECT_LOGIN`.
`account-management` requires `YANDEX_DIRECT_V4ACCOUNT_ACCOUNT_ID`; without it
the runner reports `NOT_COVERED` for that command.

`clients.update` is opt-in because it mutates client-level account metadata.
Set `YANDEX_DIRECT_CLIENTS_UPDATE_LOGIN` to an expendable sandbox
`Client-Login`; the runner passes it through `--login` and updates only
`ClientInfo` with a unique smoke marker. Without that variable, the runner
reports `NOT_COVERED` for `clients.update`.

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
direct auth login --profile agency1 --format json
direct auth login --code abc123 --profile agency1
printf '%s\n' abc123 | direct auth login --code - --profile agency1
direct auth list
direct auth use --profile agency1
direct auth status --profile agency1
direct --profile agency1 campaigns get
```

Примечания:
- OAuth profiles сохраняют refresh token и автоматически обновляют access token.
- В non-interactive shell сначала выполните `direct auth login --profile NAME`, затем завершите через `direct auth login --code - --profile NAME` и передайте browser code через stdin.
- `direct auth login --code CODE --profile NAME` сохраняется для совместимости, но автоматизация должна использовать `--code -`, чтобы не раскрывать код в process arguments.
- Если первый non-interactive шаг включает `--client-secret`, secret запоминается для последующего completion step.
- Если profile уже хранит confidential OAuth client, `direct auth login --code CODE --profile NAME` использует сохраненные `client_id` и `client_secret`.
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

> **В тестах порядок инвертирован.** Live-API тесты (например `tests/test_v4_live_contracts.py`) сначала читают `YANDEX_DIRECT_TOKEN` / `YANDEX_DIRECT_LOGIN` из окружения, затем падают на активный профиль `direct auth`, и скипают тест если ни того ни другого нет. Это сделано специально: на машине разработчика с активным профилем обычный `pytest` не должен молча идти в боевой API. Контракт зафиксирован в `CLAUDE.md`.

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

Not allowed: splitting a canonical `direct ...` command over multiple shell
lines with `\`.

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

Do not use: a timestamp with a `Z` suffix, or a quoted timestamp that contains
a space between the date and time.

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

Invalid examples include command lines that pass raw JSON flags, use shell
line continuations, add timezone suffixes to CLI datetimes, or quote
space-separated datetime values.

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

# CPA-стратегия (одна цель): --goal-id обязателен, --average-cpa/--bid-ceiling — micro-рубли
direct campaigns add --name "CPA-кампания" --start-date 2026-06-01 --type TEXT_CAMPAIGN --search-strategy AVERAGE_CPA --network-strategy SERVING_OFF --goal-id 1234567 --average-cpa 500000000 --bid-ceiling 1000000000 --counter-ids 111,222 --dry-run

# Мульти-целевой CPA через PriorityGoals (пары goal_id:value, WSDL PriorityGoalsItem)
direct campaigns add --name "Мульти-целевой CPA" --start-date 2026-06-01 --type TEXT_CAMPAIGN --search-strategy AVERAGE_CPA_MULTIPLE_GOALS --network-strategy SERVING_OFF --priority-goals 1234567:80,9876543:20 --bid-ceiling 1000000000 --dry-run

# Дополнительные настройки TextCampaign
direct campaigns add --name "Текстовые настройки" --start-date 2026-06-01 --type TEXT_CAMPAIGN --counter-ids 111,222 --relevant-keywords-budget-percent 40 --relevant-keywords-mode OPTIMAL --attribution-model AUTO --negative-keyword-shared-set-ids 10,11 --dry-run
direct campaigns update --id 12345 --type TEXT_CAMPAIGN --setting ADD_METRICA_TAG=NO --priority-goals 1234567:80:YES --tracking-params "utm_source=direct" --dry-run
direct campaigns add --name "Пакетная текстовая" --start-date 2026-06-01 --type TEXT_CAMPAIGN --package-strategy-id 700 --package-platform-search-result YES --package-platform-product-gallery YES --package-platform-network NO --dry-run
direct campaigns add --name "Единые настройки" --start-date 2026-06-01 --type UNIFIED_CAMPAIGN --setting ADD_METRICA_TAG=YES --counter-ids 111,222 --priority-goals 1234567:80:YES --tracking-params "utm_source=direct" --attribution-model AUTO --negative-keyword-shared-set-ids 10,11 --dry-run
direct campaigns add --name "Единая пакетная" --start-date 2026-06-01 --type UNIFIED_CAMPAIGN --package-strategy-id 700 --package-platform-search-result YES --package-platform-product-gallery YES --package-platform-maps NO --package-platform-search-organization-list YES --package-platform-network YES --dry-run

# Notification (Sms/Email) и TimeTargeting через явные CLI-флаги
direct campaigns add --name "Уведомления+Расписание" --start-date 2026-06-01 --type TEXT_CAMPAIGN --search-strategy HIGHEST_POSITION --network-strategy SERVING_OFF --notification-email ops@example.com --notification-send-warnings YES --time-targeting-schedule 1A0123456789ABCDEFGHIJKL --consider-working-weekends YES --dry-run

# TrackingParams — UTM/трекинг в подтипе кампании (TextCampaign/UnifiedCampaign/DynamicTextCampaign/SmartCampaign.TrackingParams)
direct campaigns add --name "UTM" --start-date 2026-06-01 --type TEXT_CAMPAIGN --tracking-params "utm_source=direct&utm_campaign={campaign_id}" --dry-run

# Обновление и управление статусом
direct campaigns update --id 12345 --name "Новое название" --status SUSPENDED --budget 100000000 --start-date 2024-02-10 --end-date 2024-03-01
direct campaigns update --id 12345 --type TEXT_CAMPAIGN --tracking-params "utm_source=direct&utm_medium=cpc" --dry-run
direct campaigns suspend --id 12345
direct campaigns resume --id 12345
direct campaigns archive --id 12345
direct campaigns unarchive --id 12345
direct campaigns delete --id 12345
```

#### Группы объявлений

```bash
direct adgroups get --campaign-ids 1,2,3 --limit 50
direct adgroups add --name "Группа 1" --campaign-id 12345 --region-ids 1,225 --negative-keywords "ремонт,б/у" --tracking-params "utm_source=direct" --dry-run
direct adgroups add --name "ТГО-группа с фидом" --campaign-id 12345 --region-ids 1,225 --feed-id 170 --feed-category-ids 10,11 --dry-run
direct adgroups add --name "Динамическая группа" --campaign-id 12345 --type DYNAMIC_TEXT_AD_GROUP --region-ids 1,225 --domain-url example.com --autotargeting-category EXACT=YES --dry-run
direct adgroups add --name "Динамическая группа с фидом" --campaign-id 12345 --type DYNAMIC_TEXT_FEED_AD_GROUP --region-ids 1,225 --feed-id 170 --autotargeting-category EXACT=YES --dry-run
direct adgroups add --name "CPM группа с ключевыми фразами" --campaign-id 12345 --type CPM_BANNER_KEYWORDS_AD_GROUP --region-ids 1,225 --dry-run
direct adgroups add --name "CPM группа с профилем пользователя" --campaign-id 12345 --type CPM_BANNER_USER_PROFILE_AD_GROUP --region-ids 1,225 --dry-run
direct adgroups add --name "CPM видео группа" --campaign-id 12345 --type CPM_VIDEO_AD_GROUP --region-ids 1,225 --dry-run
direct adgroups add --name "Смарт-группа" --campaign-id 12345 --type SMART_AD_GROUP --region-ids 1,225 --feed-id 170 --ad-title-source FEED_NAME --ad-body-source FEED_NAME --dry-run
direct adgroups add --name "ЕПК-группа" --campaign-id 12345 --type UNIFIED_AD_GROUP --region-ids 1,225 --offer-retargeting YES --dry-run
direct adgroups add --name "Группа мобильного приложения" --campaign-id 12345 --type MOBILE_APP_AD_GROUP --region-ids 1,225 --store-url https://apps.apple.com/app/id123456789 --target-device-types DEVICE_TYPE_MOBILE,DEVICE_TYPE_TABLET --target-carrier WI_FI_AND_CELLULAR --target-operating-system-version 14.0 --dry-run
direct adgroups update --id 67890 --negative-keyword-shared-set-ids 10,11 --tracking-params "utm_source=direct"
direct adgroups update --id 67890 --feed-id 170 --feed-category-ids 10,11
direct adgroups update --id 67890 --domain-url example.com --autotargeting-settings-exact YES --autotargeting-settings-without-brands YES --dry-run
direct adgroups update --id 67890 --dynamic-feed --autotargeting-category EXACT=YES --dry-run
direct adgroups update --id 67890 --target-device-types DEVICE_TYPE_TABLET --target-carrier WI_FI_ONLY --target-operating-system-version 13.0
direct adgroups update --id 67890 --ad-title-source FEED_NAME --ad-body-source FEED_DESCRIPTION
direct adgroups update --id 67890 --offer-retargeting NO
direct adgroups delete --id 67890
```

#### Объявления

```bash
direct ads get --campaign-ids 1,2,3
direct ads get --adgroup-ids 45678 --format table
direct ads add --adgroup-id 12345 --type TEXT_AD --title "Заголовок" --text "Текст объявления" --href "https://example.com" --dry-run
direct ads add --adgroup-id 12345 --type TEXT_AD --title "Заголовок" --text "Текст" --href "https://example.com" --title2 "Второй заголовок" --display-url-path "deals" --mobile YES --vcard-id 111 --sitelink-set-id 222 --turbo-page-id 333 --ad-extensions "444,555" --dry-run
direct ads add --adgroup-id 12345 --type TEXT_AD --title "Заголовок" --text "Текст объявления" --href "https://example.com" --final-url "https://final.example.com" --video-extension-creative-id 777 --price-extension-price 123.45 --price-extension-price-qualifier FROM --price-extension-price-currency RUB --business-id 777 --prefer-vcard-over-business NO --erir-ad-description "Объект текстового объявления" --dry-run
direct ads add --adgroup-id 12345 --type RESPONSIVE_AD --texts "Текст один,Текст два" --titles "Заголовок один,Заголовок два" --image-hashes hash1,hash2 --video-extension-ids 111,222 --href "https://example.com" --price-extension-price 123.45 --price-extension-price-qualifier FROM --price-extension-price-currency RUB --business-id 777 --erir-ad-description "Объект адаптивного объявления" --dry-run
direct ads add --adgroup-id 12345 --type SHOPPING_AD --feed-id 170 --default-texts "Текст по умолчанию" --sitelink-set-id 222 --ad-extensions "333,444" --business-id 777 --feed-filter-condition "CATEGORY:EQUALS_ANY:shoes|boots" --title-sources NAME,BRAND --text-sources DESCRIPTION --dry-run
direct ads add --adgroup-id 12345 --type LISTING_AD --feed-id 171 --default-texts "Текст листинга по умолчанию" --feed-filter-condition "CATEGORY:EQUALS_ANY:appliances" --title-sources TITLE --text-sources DESCRIPTION --dry-run
direct ads add --adgroup-id 12345 --type TEXT_AD_BUILDER_AD --creative-id 123 --href "https://example.com" --turbo-page-id 456 --erir-ad-description "Объект объявления из конструктора" --dry-run
direct ads add --adgroup-id 12345 --type MOBILE_APP_AD_BUILDER_AD --creative-id 123 --tracking-url "https://track.example.com" --erir-ad-description "Мобильное объявление из конструктора" --dry-run
direct ads add --adgroup-id 12345 --type CPM_BANNER_AD_BUILDER_AD --creative-id 123 --href "https://example.com" --tracking-pixels "https://pixel.example.com/a,https://pixel.example.com/b" --dry-run
direct ads add --adgroup-id 12345 --type TEXT_IMAGE_AD --image-hash abcdefghijklmnopqrst --href "https://example.com" --turbo-page-id 555 --final-url "https://final.example.com" --erir-ad-description "Объект графического объявления" --dry-run
direct ads add --adgroup-id 12345 --type DYNAMIC_TEXT_AD --text "Динамический текст" --image-hash abcdefghijklmnopqrst --vcard-id 111 --sitelink-set-id 222 --ad-extensions "333,444" --dry-run
direct ads add --adgroup-id 12345 --type MOBILE_APP_AD --title "Установите приложение" --text "Текст приложения" --action INSTALL --tracking-url "https://track.example.com" --mobile-app-feature PRICE=YES --video-extension-creative-id 777 --erir-ad-description "Объект мобильного объявления" --dry-run
direct ads add --adgroup-id 12345 --type MOBILE_APP_IMAGE_AD --image-hash abcdefghijklmnopqrst --tracking-url "https://track.example.com" --erir-ad-description "Мобильное графическое объявление" --dry-run
direct ads add --adgroup-id 12345 --type SMART_AD_BUILDER_AD --logo-extension-hash logoabcdefghijklmnop --dry-run
direct ads update --id 99999 --type TEXT_AD --title "Новый заголовок" --text "Новый текст" --href "https://example.com"
direct ads update --id 99999 --type TEXT_AD --image-hash abcdefghijklmnopqrst
direct ads update --id 99999 --type TEXT_AD --title2 "Новый второй заголовок" --vcard-id 222
direct ads update --id 99999 --type TEXT_AD --callouts-add "111,222" --callouts-remove "333"
direct ads update --id 99999 --type TEXT_AD --callouts-set "444,555"
direct ads update --id 99999 --type TEXT_AD --video-extension-creative-id 777 --price-extension-price 123.45 --price-extension-price-qualifier FROM --price-extension-price-currency RUB
direct ads update --id 99999 --type TEXT_AD --final-url "https://final.example.com" --age-label AGE_18 --business-id 777 --prefer-vcard-over-business NO --erir-ad-description "Объект текстового объявления"
direct ads update --id 99999 --type DYNAMIC_TEXT_AD --text "Обновленный динамический текст" --callouts-add "111,222"
direct ads update --id 99999 --type MOBILE_APP_AD --mobile-app-feature PRICE=YES --mobile-app-feature CUSTOMER_RATING=NO --video-extension-creative-id 777 --erir-ad-description "Объект мобильного объявления"
direct ads update --id 99999 --type RESPONSIVE_AD --texts "Текст один,Текст два" --titles "Заголовок один,Заголовок два" --image-hashes hash1,hash2 --video-extension-ids 111,222 --href "https://example.com" --price-extension-price 123.45 --price-extension-price-qualifier FROM --price-extension-price-currency RUB
direct ads update --id 99999 --type TEXT_IMAGE_AD --final-url "https://final.example.com" --erir-ad-description "Объект графического объявления"
direct ads update --id 99999 --type SHOPPING_AD --sitelink-set-id 222 --callouts-set "444,555" --business-id 777 --feed-filter-condition "CATEGORY:EQUALS_ANY:shoes|boots" --title-sources NAME,BRAND --text-sources DESCRIPTION --default-texts "Текст по умолчанию"
direct ads update --id 99999 --type MOBILE_APP_IMAGE_AD --image-hash abcdefghijklmnopqrst --tracking-url "https://track.example.com" --erir-ad-description "Мобильное графическое объявление"
direct ads update --id 99999 --type TEXT_AD_BUILDER_AD --creative-id 123 --creative-erir-ad-description "Объект креатива" --href "https://example.com" --turbo-page-id 456
direct ads update --id 99999 --type SMART_AD_BUILDER_AD --logo-extension-hash logoabcdefghijklmnop --erir-ad-description "Смарт-объявление из конструктора"
direct ads update --id 99999 --type CPM_BANNER_AD_BUILDER_AD --creative-id 123 --href "https://example.com" --tracking-pixels "https://pixel.example.com/a,https://pixel.example.com/b"
direct ads delete --id 99999
```

Доступные типизированные флаги TEXT_AD для `ads add` / `ads update`:
`--title`, `--text`, `--href`, `--image-hash`, `--title2`, `--display-url-path`,
`--vcard-id`, `--sitelink-set-id`, `--turbo-page-id`, `--final-url`,
`--video-extension-creative-id`, `--price-extension-*`, `--business-id`,
`--prefer-vcard-over-business` и `--erir-ad-description`. Для `ads add`
`TextAd.PriceExtension` требует `--price-extension-price`,
`--price-extension-price-qualifier` и `--price-extension-price-currency`, если
передан любой price-extension флаг. В `ads update` дополнительно доступны
`--callouts-add`, `--callouts-remove` и
`--callouts-set` для управления полем `TextAdUpdateBase.CalloutSetting`
(`ext:AdExtensionSetting`) у существующего объявления — `--callouts-set`
заменяет весь список выносок и взаимоисключим с инкрементальной парой
`--callouts-add` / `--callouts-remove`. Значения price-extension передаются как
человекочитаемые суммы и внутри CLI конвертируются в long-единицы API Яндекс
Директа. В `ads update` также поддерживается `--age-label`.
`--mobile` (по умолчанию `NO`) и
`--ad-extensions` доступны только в `ads add` — WSDL `TextAdUpdate` не
содержит `Mobile`, а в `ads update` расширения управляются через флаги
`--callouts-*` выше. Для TEXT_IMAGE_AD дополнительно доступен
`--turbo-page-id`, `--final-url` и `--erir-ad-description`. Для
DYNAMIC_TEXT_AD в `ads add` обязателен `--text`; доступны `--image-hash`,
`--vcard-id`, `--sitelink-set-id` и `--ad-extensions`. В `ads update`
доступны `--text`, `--image-hash`, `--vcard-id`, `--sitelink-set-id` и
`--callouts-*`.
Для RESPONSIVE_AD в `ads add` обязательны `--texts` и `--titles` как списки
через запятую, а также `--href`, `--business-id` или оба флага. Дополнительные
флаги создания: `--image-hashes`, `--video-extension-ids`, `--age-label`,
`--display-url-path`, `--sitelink-set-id`, `--ad-extensions`,
`--price-extension-*` и `--erir-ad-description`.
Для SHOPPING_AD и LISTING_AD в `ads add` обязательны `--feed-id` и одно
значение `--default-texts`. Дополнительные флаги создания:
`--sitelink-set-id`, `--ad-extensions`, `--business-id`, повторяемый
`--feed-filter-condition` (`OPERAND:OPERATOR:ARG1|ARG2`), `--title-sources` и
`--text-sources`.
Для non-SMART AdBuilder subtype в `ads add` обязателен `--creative-id`.
TEXT_AD_BUILDER_AD, CPC_VIDEO_AD_BUILDER_AD, CPM_BANNER_AD_BUILDER_AD и
CPM_VIDEO_AD_BUILDER_AD требуют `--href`, `--turbo-page-id` или оба флага.
Mobile app builder subtype используют `--tracking-url`. CPM builder subtype
также поддерживают `--tracking-pixels`; non-SMART AdBuilder subtype в
`ads add` поддерживают `--erir-ad-description`.
Для MOBILE_APP_AD в `ads add` обязательны `--title`, `--text` и `--action`;
дополнительно доступны `--mobile-app-feature FEATURE=YES|NO`,
`--video-extension-creative-id` и `--erir-ad-description`. Для
MOBILE_APP_IMAGE_AD в `ads add` обязателен `--image-hash`; в add/update
доступны `--tracking-url` и `--erir-ad-description`.
Для RESPONSIVE_AD в `ads update` доступны `--texts`, `--titles`,
`--image-hashes`, `--video-extension-ids`, `--href`, `--age-label`,
`--display-url-path`, `--sitelink-set-id`, `--callouts-*`,
`--price-extension-*`, `--business-id` и `--erir-ad-description`.
Для SHOPPING_AD и LISTING_AD в `ads update` доступны `--sitelink-set-id`,
`--callouts-*`, `--business-id`, повторяемый `--feed-filter-condition`
(`OPERAND:OPERATOR:ARG1|ARG2`), `--title-sources`, `--text-sources` и
`--default-texts`.
Для MOBILE_APP_IMAGE_AD в `ads update` доступны `--image-hash`,
`--tracking-url` и `--erir-ad-description`.
Для SMART_AD_BUILDER_AD в `ads add` доступен `--logo-extension-hash`.
Для AdBuilder subtype в `ads update` доступны `--creative-id`,
`--creative-erir-ad-description`, `--erir-ad-description` и subtype-specific
`--final-url`, `--href`, `--turbo-page-id`, `--tracking-url`,
`--tracking-pixels`. Для SMART_AD_BUILDER_AD в `ads update` доступны
`--logo-extension-hash` и `--erir-ad-description`.

#### Ключевые слова

```bash
direct keywords get --campaign-ids 1,2,3
direct keywords add --adgroup-id 12345 --keyword "купить ноутбук" --bid 10500000 --context-bid 5250000 --user-param-1 segment-a --user-param-2 segment-b --dry-run
direct keywords add --adgroup-id 12345 --keyword "---autotargeting" --autotargeting-search-bid-is-auto YES --priority HIGH --autotargeting-category EXACT=YES --autotargeting-category BROADER=NO --autotargeting-brand-option WITHOUT_BRANDS=YES --dry-run
direct keywords add --adgroup-id 12345 --keyword "---autotargeting" --autotargeting-settings-exact YES --autotargeting-settings-narrow NO --autotargeting-settings-without-brands YES --dry-run
direct keywords update --id 88888 --keyword "updated keyword text"
direct keywords update --id 88888 --autotargeting-category EXACT=YES --autotargeting-category BROADER=NO --autotargeting-brand-option WITHOUT_BRANDS=YES
direct keywords update --id 88888 --autotargeting-settings-broader YES --autotargeting-settings-with-competitors-brand NO
direct keywords delete --id 88888
```

**Пакетная загрузка ключевых слов** (CLI автоматически режет на куски по API-лимиту 10/запрос):

```bash
# Из JSONL-файла (по одному объекту ключевого слова на строку)
direct keywords add --adgroup-id 12345 --from-file keywords.jsonl

# Inline JSON-массив
direct keywords add --keywords-json '[{"Keyword":"купить ноутбук","Bid":10000000},{"Keyword":"купить ПК"}]'
```

Пример `keywords.jsonl`:

```jsonl
{"Keyword":"купить ноутбук","Bid":10000000,"UserParam1":"src=ad1"}
{"Keyword":"купить ПК","ContextBid":5000000}
{"Keyword":"buy laptop","AdGroupId":99999}
```

- Ключи строки — WSDL CamelCase: `Keyword`, `AdGroupId`, `Bid`, `ContextBid`, `UserParam1`, `UserParam2`.
- Поля автотаргетинга намеренно не принимаются в batch-режиме; используйте single-item typed flags: `--autotargeting-search-bid-is-auto`, `--priority`, `--autotargeting-category`, `--autotargeting-brand-option` или `--autotargeting-settings-*`.
- `--adgroup-id` задаёт значение по умолчанию; в строке можно переопределить через `AdGroupId`.
- В каждой строке должны разрешаться `Keyword` и `AdGroupId`; неизвестные поля отклоняются с указанием номера строки.
- API-лимит: 10 элементов на запрос `keywords.add` — см. [документацию Yandex Direct](https://yandex.ru/dev/direct/doc/dg/objects/keyword.html). CLI отправит нужное число чанков и склеит `AddResults`.
- API-лимит: 200 ключевых слов на одну группу объявлений. CLI печатает предупреждение, если в каком-то `AdGroupId` во входе их больше; API отклонит излишек item-level ошибками.
- Item-level ошибки от API не прерывают batch; объединённый вывод содержит и успешные Id, и ошибки.
- При сетевой ошибке в середине batch уже созданные Id выводятся в stderr (`Partial success before failure`), чтобы при retry не возникли дубли.
- `--dry-run` показывает payload первого чанка плюс `{chunks, totalItems, chunkSize}`.

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
direct retargeting add --name "Список A" --description "Теплая аудитория" --type AUDIENCE --rule "ALL:12345:30|67890:7" --dry-run
direct retargeting update --id 55 --name "Переименованный список" --description "Обновленное примечание" --rule "ANY:12345:30" --dry-run

# Ставки и модификаторы
direct bids get --campaign-ids 123 --fields CampaignId,AdGroupId,KeywordId,Bid
direct bids set --keyword-id 123 --bid 15000000
direct bids set --campaign-id 123 --context-bid 9000000 --autotargeting-search-bid-is-auto YES --priority HIGH
direct bids set-auto --keyword-id 123 --max-bid 20000000 --position PREMIUMBLOCK --scope SEARCH --dry-run
direct keywordbids set --adgroup-id 321 --search-bid 8000000 --network-bid 3000000 --autotargeting-search-bid-is-auto NO --priority NORMAL
direct keywordbids set-auto --keyword-id 321 --target-traffic-volume 100 --increase-percent 10 --bid-ceiling 12500000 --dry-run
direct bidmodifiers get --campaign-ids 123 --fields Id,CampaignId,AdGroupId,Level,Type
direct bidmodifiers add --campaign-id 123 --type DEMOGRAPHICS_ADJUSTMENT --value 150 --gender GENDER_MALE --age AGE_25_34 --dry-run
direct bidmodifiers add --campaign-id 123 --type MOBILE_ADJUSTMENT --value 120 --operating-system-type IOS --dry-run
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
direct strategies add --name "Общая стратегия" --type WbMaximumClicks --weekly-spend-limit 1000000000 --bid-ceiling 30000000 --dry-run
direct strategies add --name "Периодный бюджет" --type WbMaximumClicks --custom-period-spend-limit 1000000000 --custom-period-start-date 2026-06-01 --custom-period-end-date 2026-06-30 --custom-period-auto-continue YES --dry-run
direct strategies add --name "Минимальный бюджет CPA" --type AverageCpa --average-cpa 4000000 --goal-id 123 --minimum-exploration-budget 200000000 --dry-run
direct strategies add --name "CRR по целям" --type AverageCrr --average-crr 10 --goal-id 123 --priority-goal 123:2000000:YES --dry-run
direct strategies update --id 42 --type WbMaximumClicks --weekly-spend-limit 35000000 --dry-run
direct strategies update --id 42 --type WbMaximumClicks --custom-period-spend-limit 35000000 --custom-period-start-date 2026-07-01 --custom-period-end-date 2026-07-31 --custom-period-auto-continue NO --dry-run
direct strategies update --id 42 --type MaxProfit --minimum-exploration-budget 0 --dry-run
direct strategies update --id 42 --priority-goal 123:2000000:YES --dry-run
direct strategies archive --id 42 --dry-run

# Динамические таргеты по фиду
direct dynamicfeedadtargets get --adgroup-ids 123 --limit 5
direct dynamicfeedadtargets add --adgroup-id 33 --name "Срез фида А" --condition "CATEGORY:EQUALS:shoes" --bid 5000000 --dry-run
direct dynamicfeedadtargets set-bids --id 789 --bid 6500000 --context-bid 4000000 --dry-run

# Расширения, ассеты, фиды и клиенты
direct sitelinks add --sitelink "Docs|https://example.com/docs|API docs|12345" --sitelink "Help|https://example.com/help|Desk" --dry-run
direct vcards add --campaign-id 555 --country "Россия" --city "Москва" --company-name "Acme" --work-time 1#5#9#0#18#0 --phone-country-code +7 --phone-city-code 495 --phone-number 1234567 --instant-messenger-client telegram --instant-messenger-login acme_support --point-on-map-x 37.6173 --point-on-map-y 55.7558 --point-on-map-x1 37.60 --point-on-map-y1 55.74 --point-on-map-x2 37.63 --point-on-map-y2 55.77 --dry-run
direct adextensions add --callout-text "Free shipping" --dry-run
direct adimages add --name banner.png --image-data BASE64DATA --type ICON --dry-run
direct creatives add --video-id video-id --dry-run
direct feeds add --name "Фид A" --url "https://example.com/feed.xml" --business-type RETAIL --remove-utm-tags YES --feed-login feedbot --dry-run
direct feeds add --name "Фид-файл" --file-feed-path ./feed.xml --business-type RETAIL --dry-run
direct feeds update --id 18 --name "Фид A v2" --url "https://example.com/feed-v2.xml" --remove-utm-tags NO --clear-feed-login --clear-feed-password --dry-run
direct feeds update --id 18 --file-feed-path ./feed-v2.xml --file-feed-filename feed-v2.xml --dry-run
direct clients update --client-info "Приоритетный клиент" --phone +70000000000 --notification-email user@example.com --notification-lang EN --email-subscription RECEIVE_RECOMMENDATIONS=YES --setting DISPLAY_STORE_RATING=NO --dry-run
direct clients update --erir-organization-name "Рекламодатель ООО" --erir-organization-kpp 770101001 --erir-organization-epay-number epay123 --erir-organization-reg-number 1027700132195 --erir-organization-oksm-number 643 --erir-organization-okved-code 62.01 --dry-run
direct clients update --erir-contract-number C-2026-01 --erir-contract-date 2026-01-15 --erir-contract-type CONTRACT --erir-contract-action-type COMMERCIAL --erir-contract-subject-type REPRESENTATION --erir-contract-is-agency-payment NO --erir-contract-price-amount 120000.5 --erir-contract-price-including-vat YES --dry-run
direct clients update --erir-contragent-name "Контрагент ООО" --erir-contragent-kpp 770201001 --erir-contragent-phone +70000000001 --erir-contragent-epay-number epay456 --erir-contragent-reg-number 1027700132196 --erir-contragent-oksm-number 643 --erir-contragent-tin-type LEGAL --erir-contragent-tin 1234567890 --dry-run
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

### Ошибки API

Яндекс Директ может вернуть успешный HTTP-ответ, внутри которого есть
item-level `Errors` для конкретного объекта. Direct CLI считает такой ответ
ошибкой операции: команда завершается с ненулевым кодом и печатает код ошибки,
сообщение и детали.

Код `8800` с `Object not found` обычно означает, что объект недоступен в
текущем `Client-Login` или аккаунте. Перед повтором проверьте выбранный
`--login`, `YANDEX_DIRECT_LOGIN` или auth profile.

### Тестирование

В `tests/` четыре уровня тестов:

| Уровень | Маркер | Сеть | Нужен токен |
|---|---|---|---|
| Юнит / CLI / dry-run | *(без маркера)* | Нет | Нет |
| Read-only интеграция | `-m integration` | Да (prod API, только чтение) | Да |
| Write интеграция | `-m integration_write` | Нет (replay VCR-кассет) | Нет |
| Live draft write интеграция (v5) | `-m integration_live_write` | Да при записи, иначе VCR replay | Да + `YANDEX_DIRECT_LIVE_WRITE=1` |
| v4 live read | `-m v4_live_read` | Да (prod v4 JSON API, только чтение) | Да |
| v4 live запись отчётов на уровне аккаунта (opt-in) | `-k _opt_in_write` в `tests/test_v4_live_contracts.py` | Да (prod v4) | Да + `YANDEX_DIRECT_V4_LIVE_REPORT_WRITE=1` |

```bash
pip install -e ".[dev]"
pytest                              # быстрый уровень — без токена
pytest -m integration -v            # read-only интеграция (нужен токен)
pytest -m integration_write -v      # replay write-кассет (токен не нужен)
YANDEX_DIRECT_LIVE_WRITE=1 pytest -m integration_live_write -v  # replay live draft-кассеты (v5)
YANDEX_DIRECT_LIVE_WRITE=1 pytest -m integration_live_write -v --record-mode=rewrite  # перезапись live draft-кассеты
YANDEX_DIRECT_V4_LIVE_REPORT_WRITE=1 pytest tests/test_v4_live_contracts.py -k _opt_in_write -v  # жизненный цикл v4 wordstat/forecast
```

Уровень v4 account-level write (`YANDEX_DIRECT_V4_LIVE_REPORT_WRITE=1`) создаёт настоящие Wordstat-отчёты и прогнозы в боевом аккаунте и удаляет их в том же запуске. **Кассет нет** — эти тесты идут только в живой API. Созданные ID пишутся в `~/.direct-cli/test-orphans.json`: если запуск оборвался между create и delete, при следующем вызове осиротевшие ID будут удалены автоматически (см. `tests/_orphan_store.py`).

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
| CLI groups с `auth` | 40 |
| CLI subcommands с `auth` | 144 |
| API CLI subcommands без `auth` | 140 |

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

Для `v4account` sandbox smoke команда `enable-shared-account` использует
`YANDEX_DIRECT_V4ACCOUNT_CLIENT_LOGIN` или fallback на `YANDEX_DIRECT_LOGIN`.
Для `account-management` нужна переменная
`YANDEX_DIRECT_V4ACCOUNT_ACCOUNT_ID`; без неё runner покажет `NOT_COVERED`.

`clients.update` включается только явно, потому что меняет client-level
metadata аккаунта. Укажите `YANDEX_DIRECT_CLIENTS_UPDATE_LOGIN` с disposable
sandbox `Client-Login`; runner передаст его через `--login` и изменит только
`ClientInfo` на уникальный smoke marker. Без этой переменной runner покажет
`NOT_COVERED` для `clients.update`.

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
