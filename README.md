# DSSG NYC Volunteer Dashboard

Internal Streamlit dashboard for DSSG NYC to track volunteer growth, event participation, and estimated impact.

## Repository Structure

```text
.
├── app.py                          # Thin Streamlit entrypoint
├── src/
│   └── dssg_dashboard/
│       ├── __init__.py
│       └── dashboard.py            # Data loading, transforms, and UI rendering
├── data/
│   └── raw/
│       ├── volunteer_registrations.csv
│       └── eventbrite_participants.csv
├── assets/
│   └── dssg_logo.png
├── docs/
│   └── PRD.md
├── .env.example                    # Environment template
├── .env.sh                         # Local env vars (ignored by git)
├── requirements.txt
└── README.md
```

## Data Source Strategy

The app uses **Google Sheets API first** and falls back to local CSV files.

1. Primary: Google Sheets API (cached for 1 day)
2. Fallback: `data/raw/*.csv`

This allows near real-time updates while keeping a stable offline path.

## Environment Variables

Supported env vars:

- `USE_GOOGLE_SHEETS=true` (default: `true`)
- `GOOGLE_SHEETS_ID` (default: `1AyvBMU87yUHmn9m74-NX6yDrTERYVVOXs8McvrKFqP4`)
- `GOOGLE_SHEETS_VOLUNTEER_TAB` (default: `Form Responses 1`)
- `GOOGLE_SHEETS_EVENT_TAB` (default: `Eventbrite: Meet-ups participants`)
- Credentials (choose one):
  - `GOOGLE_APPLICATION_CREDENTIALS=/absolute/path/to/service-account.json`
  - `GOOGLE_SERVICE_ACCOUNT_JSON='{"type":"service_account", ...}'`

Local env handling:

- On app startup, it auto-loads values from `.env` and `.env.sh` (if present).
- This prevents refresh/session issues where shell exports are missing.

## Local Setup

1. Create/activate virtualenv

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install dependencies

```bash
pip install -r requirements.txt
```

3. Configure env file

```bash
cp .env.example .env.sh
# edit .env.sh and set GOOGLE_APPLICATION_CREDENTIALS
```

4. Run app

```bash
streamlit run app.py
```

## Business Logic Implemented

- Event classification:
  - `event_name` contains `Hackathon` => `hackathon`
  - otherwise => `meetup`
- Active volunteers KPI (365 days): registered volunteers with >=1 attendance in trailing 365 days
- Short-term active context (90 days): same logic over trailing 90 days
- Hackathon hours: `participants * 9`
- Dollar impact: `hackathon_hours * $40`

## Troubleshooting

If you see:

`Google credentials missing. Set GOOGLE_APPLICATION_CREDENTIALS or GOOGLE_SERVICE_ACCOUNT_JSON.`

Check:

1. `GOOGLE_APPLICATION_CREDENTIALS` points to a valid JSON key path
2. Service account has at least Viewer access to the sheet
3. `.env.sh` exists and contains the variables (or shell has exports)
4. You restarted Streamlit after changing env values

## Security Notes

- Keep service account keys out of git (`.gitignore` already configured).
- Use `.env.sh` / `.env` for local secrets only.
