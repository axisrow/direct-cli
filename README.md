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

Install with `pip install direct-cli`, then run commands with `direct`.

### Global Options

| Option | Description |
|--------|-------------|
| `--token` | API access token |
| `--login` | Yandex advertiser login |
| `--sandbox` | Use sandbox API |

### Usage

All commands follow the pattern: `direct <resource> <action> [options]`

Plugin-compatible aliases are also available for integrations that expect
canonical MCP-facing names: `dynamictargets`, `smarttargets`,
`negativekeywords`, `list`, `checkcamp`, `checkdict`, and `has-volume`.

#### Campaigns

```bash
# Get campaigns
direct campaigns get
direct campaigns get --status ACTIVE
direct campaigns get --ids 1,2,3 --format table
direct campaigns get --fetch-all --format csv --output campaigns.csv

# Create (use --dry-run to preview the request)
direct campaigns add --name "My Campaign" --start-date 2024-02-01 --type TEXT_CAMPAIGN --budget 1000
direct campaigns add --name "My Campaign" --start-date 2024-02-01 --dry-run

# Update / lifecycle
direct campaigns update --id 12345 --name "New Name"
direct campaigns suspend --id 12345
direct campaigns resume  --id 12345
direct campaigns archive --id 12345
direct campaigns unarchive --id 12345
direct campaigns delete  --id 12345
```

#### Ad Groups

```bash
direct adgroups get --campaign-ids 1,2,3 --limit 50
direct adgroups add --name "Group 1" --campaign-id 12345 --dry-run
direct adgroups update --id 67890 --name "New Name"
direct adgroups delete --id 67890
```

#### Ads

```bash
direct ads get --campaign-ids 1,2,3
direct ads get --adgroup-ids 45678 --format table
direct ads add --adgroup-id 12345 --type TEXT_AD --title "Title" --text "Ad text" --href "https://example.com" --dry-run
direct ads update --id 99999 --status PAUSED
direct ads delete --id 99999
```

#### Keywords

```bash
direct keywords get --campaign-ids 1,2,3
direct keywords add --adgroup-id 12345 --keyword "buy laptop" --bid 10.50 --dry-run
direct keywords update --id 88888 --bid 15.00
direct keywords delete --id 88888
```

#### Reports

```bash
# Get a report (saved to file)
direct reports get \
  --type CAMPAIGN_PERFORMANCE_REPORT \
  --from 2024-01-01 --to 2024-01-31 \
  --name "January Report" \
  --fields "Date,CampaignId,Clicks,Cost" \
  --format csv --output report.csv

# List available report types
direct reports list-types
```

Available report types: `CAMPAIGN_PERFORMANCE_REPORT`, `ADGROUP_PERFORMANCE_REPORT`, `AD_PERFORMANCE_REPORT`, `CRITERIA_PERFORMANCE_REPORT`, `CUSTOM_REPORT`, `REACH_AND_FREQUENCY_CAMPAIGN_REPORT`, `SEARCH_QUERY_PERFORMANCE_REPORT`

#### Other Resources

```bash
# Reference dictionaries
direct dictionaries get --names Currencies,GeoRegions

# Client info
direct clients get --fields ClientId,Login,Currency

# Changes feed
direct changes get --campaign-ids 1,2,3

# Retargeting lists
direct retargeting get --limit 10

# Ad extensions, sitelinks, vCards, images, creatives, feeds, bids, etc.
direct adextensions get
direct sitelinks get --ids 1,2,3
direct bids get --campaign-ids 1,2,3
```

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

Commands that affect live ad delivery: `suspend`, `resume`, `archive`, `unarchive` (available on `campaigns`, `ads`, `keywords`).

Commands that affect bids and spending: `bids set`, `keywordbids set`, `bidmodifiers set`.

Use `--dry-run` on `add` / `update` commands to preview the API request before sending:

```bash
direct campaigns add --name "Test" --start-date 2024-01-01 --dry-run
```

### Testing

Three tiers of tests live under `tests/`:

| Tier | Marker | Network | Token required |
|---|---|---|---|
| Unit / CLI wiring / dry-run | *(none)* | No | No |
| Read-only integration | `-m integration` | Yes (production API, read-only) | Yes |
| Write integration | `-m integration_write` | No (replays VCR cassettes) | No |

```bash
pip install -e ".[dev]"
pytest                              # fast tier — no token
pytest -m integration -v            # read-only integration tests (needs token)
pytest -m integration_write -v      # write cassette replay (no token needed)
```

### API Coverage And Drift Monitoring

The project now distinguishes four surfaces:

| Surface | Coverage strategy |
|---|---|
| Canonical WSDL-backed SOAP services | `tests/test_api_coverage.py` verifies strict service/method parity and dry-run request-schema coverage or explicit exclusions |
| Non-WSDL services (`reports`) | Explicit contract tests |
| Canonical CLI aliases | Checked as aliases, not counted as separate API surface |
| Intentional CLI-only helpers | Explicitly allowlisted with reasons in `direct_cli/wsdl_coverage.py` |

`100% coverage` in this project means full coverage of the supported
**canonical API surface**. Alias groups and CLI-only helpers remain supported,
but they are tracked outside the strict parity metric.

Useful maintenance commands:

```bash
python scripts/build_api_coverage_report.py
python scripts/refresh_wsdl_cache.py
python scripts/check_wsdl_drift.py
```

CI runs a scheduled API coverage workflow that:
- runs the fast coverage suites;
- uploads a machine-readable API coverage report artifact;
- checks the cached WSDL files against the live Yandex Direct API on schedule.

#### Re-recording write cassettes

The write tests replay HTTP traffic captured from the Yandex Direct **sandbox**
(`--sandbox` is injected automatically).  Cassettes live under
`tests/cassettes/test_integration_write/` and are checked into git.

If you change the request payload of any write command (e.g. adding a field),
the matching cassette stops replaying and the test fails with a body-mismatch
error.  To regenerate:

```bash
set -a && source .env && set +a        # load YANDEX_DIRECT_TOKEN / LOGIN
pytest -m integration_write -v --record-mode=rewrite
```

**The same OAuth token works for both production and the sandbox** — no
separate sandbox token is needed.  After recording, **always audit the
generated YAMLs for leaked secrets**:

```bash
grep -r "$YANDEX_DIRECT_TOKEN" tests/cassettes/   # must return nothing
grep -r "$YANDEX_DIRECT_LOGIN" tests/cassettes/   # must return nothing
```

The VCR config in `tests/conftest.py` already strips `Authorization`,
`Client-Login`, cookies and any response header containing the substring
`login`, but manual verification is mandatory before committing.

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

Установка остаётся через `pip install direct-cli`, а запуск команд теперь идет через `direct`.

### Глобальные опции

| Опция | Описание |
|-------|----------|
| `--token` | OAuth-токен доступа к API |
| `--login` | Логин рекламодателя на Яндексе |
| `--sandbox` | Использовать тестовое API (песочница) |

### Использование

Для интеграций доступны и alias-имена, совместимые с MCP-контрактом:
`dynamictargets`, `smarttargets`, `negativekeywords`, `list`, `checkcamp`,
`checkdict`, `has-volume`.

Все команды следуют шаблону: `direct <ресурс> <действие> [опции]`

#### Кампании

```bash
# Получить кампании
direct campaigns get
direct campaigns get --status ACTIVE
direct campaigns get --ids 1,2,3 --format table
direct campaigns get --fetch-all --format csv --output campaigns.csv

# Создать (--dry-run покажет запрос без отправки)
direct campaigns add --name "Моя кампания" --start-date 2024-02-01 --type TEXT_CAMPAIGN --budget 1000
direct campaigns add --name "Моя кампания" --start-date 2024-02-01 --dry-run

# Обновление и управление статусом
direct campaigns update   --id 12345 --name "Новое название"
direct campaigns suspend  --id 12345
direct campaigns resume   --id 12345
direct campaigns archive  --id 12345
direct campaigns unarchive --id 12345
direct campaigns delete   --id 12345
```

#### Группы объявлений

```bash
direct adgroups get --campaign-ids 1,2,3 --limit 50
direct adgroups add --name "Группа 1" --campaign-id 12345 --dry-run
direct adgroups update --id 67890 --name "Новое название"
direct adgroups delete --id 67890
```

#### Объявления

```bash
direct ads get --campaign-ids 1,2,3
direct ads get --adgroup-ids 45678 --format table
direct ads add --adgroup-id 12345 --type TEXT_AD --title "Заголовок" --text "Текст объявления" --href "https://example.com" --dry-run
direct ads update --id 99999 --status PAUSED
direct ads delete --id 99999
```

#### Ключевые слова

```bash
direct keywords get --campaign-ids 1,2,3
direct keywords add --adgroup-id 12345 --keyword "купить ноутбук" --bid 10.50 --dry-run
direct keywords update --id 88888 --bid 15.00
direct keywords delete --id 88888
```

#### Отчёты

```bash
# Сформировать отчёт (сохраняется в файл)
direct reports get \
  --type CAMPAIGN_PERFORMANCE_REPORT \
  --from 2024-01-01 --to 2024-01-31 \
  --name "Отчёт за январь" \
  --fields "Date,CampaignId,Clicks,Cost" \
  --format csv --output report.csv

# Список доступных типов отчётов
direct reports list-types
```

Доступные типы: `CAMPAIGN_PERFORMANCE_REPORT`, `ADGROUP_PERFORMANCE_REPORT`, `AD_PERFORMANCE_REPORT`, `CRITERIA_PERFORMANCE_REPORT`, `CUSTOM_REPORT`, `REACH_AND_FREQUENCY_CAMPAIGN_REPORT`, `SEARCH_QUERY_PERFORMANCE_REPORT`

#### Другие ресурсы

```bash
# Справочники
direct dictionaries get --names Currencies,GeoRegions

# Информация о клиенте
direct clients get --fields ClientId,Login,Currency

# Лента изменений
direct changes get --campaign-ids 1,2,3

# Списки ретаргетинга
direct retargeting get --limit 10

# Расширения объявлений, быстрые ссылки, визитки, изображения, ставки и т.д.
direct adextensions get
direct sitelinks get --ids 1,2,3
direct bids get --campaign-ids 1,2,3
```

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

Команды, влияющие на показ рекламы: `suspend`, `resume`, `archive`, `unarchive` (доступны для `campaigns`, `ads`, `keywords`).

Команды, влияющие на ставки и расходы: `bids set`, `keywordbids set`, `bidmodifiers set`.

Используйте `--dry-run` в командах `add` / `update`, чтобы увидеть тело запроса до отправки:

```bash
direct campaigns add --name "Тест" --start-date 2024-01-01 --dry-run
```

### Тестирование

В `tests/` три уровня тестов:

| Уровень | Маркер | Сеть | Нужен токен |
|---|---|---|---|
| Юнит / CLI / dry-run | *(без маркера)* | Нет | Нет |
| Read-only интеграция | `-m integration` | Да (prod API, только чтение) | Да |
| Write интеграция | `-m integration_write` | Нет (replay VCR-кассет) | Нет |

```bash
pip install -e ".[dev]"
pytest                              # быстрый уровень — без токена
pytest -m integration -v            # read-only интеграция (нужен токен)
pytest -m integration_write -v      # replay write-кассет (токен не нужен)
```

#### Перезапись write-кассет

Write-тесты воспроизводят HTTP-трафик, записанный против **sandbox-окружения**
Яндекс Директа (`--sandbox` подставляется автоматически). Кассеты лежат в
`tests/cassettes/test_integration_write/` и закоммичены в git.

Если меняется payload какой-то из write-команд (например, добавили поле),
соответствующая кассета перестанет воспроизводиться, тест упадёт с
body-mismatch. Перезапись:

```bash
set -a && source .env && set +a        # загрузить YANDEX_DIRECT_TOKEN / LOGIN
pytest -m integration_write -v --record-mode=rewrite
```

**Один и тот же OAuth-токен работает и для продакшена, и для sandbox** —
отдельный sandbox-токен не нужен. После перезаписи **обязательно проверьте
YAML-ы на утечку секретов**:

```bash
grep -r "$YANDEX_DIRECT_TOKEN" tests/cassettes/   # должно быть пусто
grep -r "$YANDEX_DIRECT_LOGIN" tests/cassettes/   # должно быть пусто
```

VCR-конфиг в `tests/conftest.py` уже стрипает `Authorization`, `Client-Login`,
куки и любые response-заголовки с подстрокой `login`, но ручная проверка
перед коммитом обязательна.

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
