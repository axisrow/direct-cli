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
direct-cli --token YOUR_TOKEN --login YOUR_LOGIN campaigns get
```

### Global Options

| Option | Description |
|--------|-------------|
| `--token` | API access token |
| `--login` | Yandex advertiser login |
| `--sandbox` | Use sandbox API |

### Usage

All commands follow the pattern: `direct-cli <resource> <action> [options]`

#### Campaigns

```bash
# Get campaigns
direct-cli campaigns get
direct-cli campaigns get --status ACTIVE
direct-cli campaigns get --ids 1,2,3 --format table
direct-cli campaigns get --fetch-all --format csv --output campaigns.csv

# Create (use --dry-run to preview the request)
direct-cli campaigns add --name "My Campaign" --start-date 2024-02-01 --type TEXT_CAMPAIGN --budget 1000
direct-cli campaigns add --name "My Campaign" --start-date 2024-02-01 --dry-run

# Update / lifecycle
direct-cli campaigns update --id 12345 --name "New Name"
direct-cli campaigns suspend --id 12345
direct-cli campaigns resume  --id 12345
direct-cli campaigns archive --id 12345
direct-cli campaigns unarchive --id 12345
direct-cli campaigns delete  --id 12345
```

#### Ad Groups

```bash
direct-cli adgroups get --campaign-ids 1,2,3 --limit 50
direct-cli adgroups add --name "Group 1" --campaign-id 12345 --dry-run
direct-cli adgroups update --id 67890 --name "New Name"
direct-cli adgroups delete --id 67890
```

#### Ads

```bash
direct-cli ads get --campaign-ids 1,2,3
direct-cli ads get --adgroup-ids 45678 --format table
direct-cli ads add --adgroup-id 12345 --type TEXT_AD --title "Title" --text "Ad text" --href "https://example.com" --dry-run
direct-cli ads update --id 99999 --status PAUSED
direct-cli ads delete --id 99999
```

#### Keywords

```bash
direct-cli keywords get --campaign-ids 1,2,3
direct-cli keywords add --adgroup-id 12345 --keyword "buy laptop" --bid 10.50 --dry-run
direct-cli keywords update --id 88888 --bid 15.00
direct-cli keywords delete --id 88888
```

#### Reports

```bash
# Get a report (saved to file)
direct-cli reports get \
  --type CAMPAIGN_PERFORMANCE_REPORT \
  --from 2024-01-01 --to 2024-01-31 \
  --name "January Report" \
  --fields "Date,CampaignId,Clicks,Cost" \
  --format csv --output report.csv

# List available report types
direct-cli reports list-types
```

Available report types: `CAMPAIGN_PERFORMANCE_REPORT`, `ADGROUP_PERFORMANCE_REPORT`, `AD_PERFORMANCE_REPORT`, `CRITERIA_PERFORMANCE_REPORT`, `CUSTOM_REPORT`, `REACH_AND_FREQUENCY_CAMPAIGN_REPORT`, `SEARCH_QUERY_PERFORMANCE_REPORT`

#### Other Resources

```bash
# Reference dictionaries
direct-cli dictionaries get --names Currencies,GeoRegions

# Client info
direct-cli clients get --fields ClientId,Login,Currency

# Changes feed
direct-cli changes get --campaign-ids 1,2,3

# Retargeting lists
direct-cli retargeting get --limit 10

# Ad extensions, sitelinks, vCards, images, creatives, feeds, bids, etc.
direct-cli adextensions get
direct-cli sitelinks get --ids 1,2,3
direct-cli bids get --campaign-ids 1,2,3
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
direct-cli campaigns get --format table
direct-cli campaigns get --format csv --output campaigns.csv
```

### Pagination

```bash
direct-cli campaigns get --limit 10        # first 10 results
direct-cli campaigns get --fetch-all       # all pages
```

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
direct-cli --token ВАШ_ТОКЕН --login ВАШ_ЛОГИН campaigns get
```

### Глобальные опции

| Опция | Описание |
|-------|----------|
| `--token` | OAuth-токен доступа к API |
| `--login` | Логин рекламодателя на Яндексе |
| `--sandbox` | Использовать тестовое API (песочница) |

### Использование

Все команды следуют шаблону: `direct-cli <ресурс> <действие> [опции]`

#### Кампании

```bash
# Получить кампании
direct-cli campaigns get
direct-cli campaigns get --status ACTIVE
direct-cli campaigns get --ids 1,2,3 --format table
direct-cli campaigns get --fetch-all --format csv --output campaigns.csv

# Создать (--dry-run покажет запрос без отправки)
direct-cli campaigns add --name "Моя кампания" --start-date 2024-02-01 --type TEXT_CAMPAIGN --budget 1000
direct-cli campaigns add --name "Моя кампания" --start-date 2024-02-01 --dry-run

# Обновление и управление статусом
direct-cli campaigns update   --id 12345 --name "Новое название"
direct-cli campaigns suspend  --id 12345
direct-cli campaigns resume   --id 12345
direct-cli campaigns archive  --id 12345
direct-cli campaigns unarchive --id 12345
direct-cli campaigns delete   --id 12345
```

#### Группы объявлений

```bash
direct-cli adgroups get --campaign-ids 1,2,3 --limit 50
direct-cli adgroups add --name "Группа 1" --campaign-id 12345 --dry-run
direct-cli adgroups update --id 67890 --name "Новое название"
direct-cli adgroups delete --id 67890
```

#### Объявления

```bash
direct-cli ads get --campaign-ids 1,2,3
direct-cli ads get --adgroup-ids 45678 --format table
direct-cli ads add --adgroup-id 12345 --type TEXT_AD --title "Заголовок" --text "Текст объявления" --href "https://example.com" --dry-run
direct-cli ads update --id 99999 --status PAUSED
direct-cli ads delete --id 99999
```

#### Ключевые слова

```bash
direct-cli keywords get --campaign-ids 1,2,3
direct-cli keywords add --adgroup-id 12345 --keyword "купить ноутбук" --bid 10.50 --dry-run
direct-cli keywords update --id 88888 --bid 15.00
direct-cli keywords delete --id 88888
```

#### Отчёты

```bash
# Сформировать отчёт (сохраняется в файл)
direct-cli reports get \
  --type CAMPAIGN_PERFORMANCE_REPORT \
  --from 2024-01-01 --to 2024-01-31 \
  --name "Отчёт за январь" \
  --fields "Date,CampaignId,Clicks,Cost" \
  --format csv --output report.csv

# Список доступных типов отчётов
direct-cli reports list-types
```

Доступные типы: `CAMPAIGN_PERFORMANCE_REPORT`, `ADGROUP_PERFORMANCE_REPORT`, `AD_PERFORMANCE_REPORT`, `CRITERIA_PERFORMANCE_REPORT`, `CUSTOM_REPORT`, `REACH_AND_FREQUENCY_CAMPAIGN_REPORT`, `SEARCH_QUERY_PERFORMANCE_REPORT`

#### Другие ресурсы

```bash
# Справочники
direct-cli dictionaries get --names Currencies,GeoRegions

# Информация о клиенте
direct-cli clients get --fields ClientId,Login,Currency

# Лента изменений
direct-cli changes get --campaign-ids 1,2,3

# Списки ретаргетинга
direct-cli retargeting get --limit 10

# Расширения объявлений, быстрые ссылки, визитки, изображения, ставки и т.д.
direct-cli adextensions get
direct-cli sitelinks get --ids 1,2,3
direct-cli bids get --campaign-ids 1,2,3
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
direct-cli campaigns get --format table
direct-cli campaigns get --format csv --output campaigns.csv
```

### Пагинация

```bash
direct-cli campaigns get --limit 10    # первые 10 результатов
direct-cli campaigns get --fetch-all   # все страницы
```

### Лицензия

MIT
