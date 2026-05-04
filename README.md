# Milan Housing Bot

Hourly bot that scrapes Milan apartment listings for 5 Xavier University students attending Università Cattolica del Sacro Cuore (Fall 2026). Writes new listings to a shared Google Sheet and sends email alerts.

## Project structure

```
milan-housing-bot/
├── src/
│   ├── scrapers/
│   │   ├── base.py            # Listing dataclass + BaseScraper ABC
│   │   ├── spotahome.py
│   │   ├── housinganywhere.py
│   │   ├── uniplaces.py
│   │   ├── idealista.py
│   │   └── immobiliare.py
│   ├── sheets.py              # gspread writer
│   ├── notifier.py            # Gmail notifier
│   └── dedupe.py              # SQLite deduplication
├── logs/                      # Rotating log files (gitignored)
├── main.py                    # Entry point
├── config.yaml                # All tunable parameters
├── .env.example               # Environment variable template
├── requirements.txt
└── README.md
```

## Setup

### 1. Clone and install

```bash
git clone <repo>
cd milan-housing-bot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium   # for JS-rendered scrapers
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your credentials
```

Required variables (see `.env.example`):
- `GOOGLE_SERVICE_ACCOUNT_JSON_PATH` — path to service account JSON (local dev)
- `GOOGLE_SERVICE_ACCOUNT_JSON` — full JSON string (Render production)
- `GOOGLE_SHEET_ID` — ID from the sheet URL
- `GMAIL_USER` / `GMAIL_APP_PASSWORD` — Gmail sender credentials
- `NOTIFY_EMAILS` — comma-separated recipient list

### 3. Google Sheet setup

The sheet must already exist and be shared with the service account email (Editor access). Column order must match `sheet_columns` in `config.yaml`.

### 4. Run locally

```bash
python main.py
```

### 5. Deploy to Render

See deployment instructions in Step 10 of the build guide.

## Tuning search criteria

All search parameters live in `config.yaml` — budgets, date range, neighborhoods, walk-time approximations. No code changes needed.

## Enabling precise walking times

Set `USE_DISTANCE_MATRIX_API=true` in `.env` and provide a `GOOGLE_MAPS_API_KEY`. The bot will call the Distance Matrix API with each listing's actual address instead of using the neighborhood lookup table.
