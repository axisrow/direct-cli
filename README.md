# Direct CLI

Command-line interface for Yandex Direct API

## Installation

```bash
pip install direct-cli
```

## Configuration

Create `.env` file in your working directory:

```env
YANDEX_DIRECT_TOKEN=your_access_token
YANDEX_DIRECT_LOGIN=your_login
```

Or pass credentials via command line:

```bash
direct-cli --token YOUR_TOKEN --login YOUR_LOGIN get-campaigns
```

## Usage

### Campaigns

```bash
# List campaigns
direct-cli get-campaigns
direct-cli get-campaigns --status ACTIVE
direct-cli get-campaigns --ids 1,2,3
direct-cli get-campaigns --fetch-all

# Create campaign
direct-cli add-campaign --name "Test Campaign" --start-date 2024-02-01 --type TEXT_CAMPAIGN --budget 1000

# Update campaign
direct-cli update-campaign --id 12345 --name "New Name"

# Archive/unarchive/delete
direct-cli archive-campaign --id 12345
direct-cli unarchive-campaign --id 12345
direct-cli delete-campaign --id 12345
```

### Ad Groups

```bash
# List ad groups
direct-cli get-adgroups
direct-cli get-adgroups --campaign-ids 1,2,3

# Create ad group
direct-cli add-adgroup --name "Test Group" --campaign-id 12345

# Update/delete
direct-cli update-adgroup --id 67890 --name "New Name"
direct-cli delete-adgroup --id 67890
```

### Ads

```bash
# List ads
direct-cli get-ads
direct-cli get-ads --campaign-ids 1,2,3

# Create text ad
direct-cli add-ad --adgroup-id 12345 --type TEXT_AD --title "Title" --text "Ad text" --href "https://example.com"

# Update/delete
direct-cli update-ad --id 99999 --status PAUSED
direct-cli delete-ad --id 99999
```

### Keywords

```bash
# List keywords
direct-cli get-keywords
direct-cli get-keywords --campaign-ids 1,2,3

# Add keyword
direct-cli add-keyword --adgroup-id 12345 --keyword "test keyword" --bid 10.50

# Update/delete
direct-cli update-keyword --id 88888 --bid 15.00
direct-cli delete-keyword --id 88888
```

### Reports

```bash
# Generate report
direct-cli get-report --type CAMPAIGN_PERFORMANCE_REPORT --from 2024-01-01 --to 2024-01-31 --name "Report" --fields "Date,CampaignId,Clicks,Cost" --format csv --output report.csv

# List report types
direct-cli list-report-types
```

### Output Formats

All commands support `--format` option:
- `json` (default) - JSON output
- `table` - Formatted table
- `csv` - CSV format
- `tsv` - TSV format

```bash
direct-cli get-campaigns --format table
direct-cli get-campaigns --format csv --output campaigns.csv
```

### Other Resources

```bash
# Dictionaries
direct-cli get-dictionaries --names Currencies,GeoRegions
direct-cli list-dictionary-names

# Clients
direct-cli get-clients
direct-cli update-client --client-id 123 --json '{"Settings": [...]}'

# Changes
direct-cli check --campaign-ids 1,2,3
direct-cli check-campaigns
direct-cli check-dictionaries
```

### Global Options

- `--token` - API access token
- `--login` - Client login
- `--sandbox` - Use sandbox API
- `--format` - Output format (json/table/csv/tsv)
- `--output` - Output file
- `--fetch-all` - Fetch all pages (for pagination)
- `--limit` - Limit number of results
- `--dry-run` - Show request without sending

## License

MIT
