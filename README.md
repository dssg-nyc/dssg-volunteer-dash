# DSSG NYC Volunteer Dashboard

Internal Streamlit dashboard for DSSG NYC to track volunteer growth, conversion to participation, retention, and estimated impact.

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
├── .streamlit/
│   ├── config.toml                # Default app theme (light / brand colors)
│   └── secrets.toml.example        # Streamlit secrets template
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

Supported config keys:

- `USE_GOOGLE_SHEETS=true` (default: `true`)
- `GOOGLE_SHEETS_ID` (default: `1AyvBMU87yUHmn9m74-NX6yDrTERYVVOXs8McvrKFqP4`)
- `GOOGLE_SHEETS_VOLUNTEER_TAB` (default: `Form Responses 1`)
- `GOOGLE_SHEETS_EVENT_TAB` (default: `Eventbrite: Meet-ups participants`)
- Credentials (choose one):
  - `GOOGLE_APPLICATION_CREDENTIALS=/absolute/path/to/service-account.json`
  - `GOOGLE_SERVICE_ACCOUNT_JSON='{"type":"service_account", ...}'`
  - `gcp_service_account` (Streamlit secrets TOML table)

Config loading order:

1. Environment variables
2. Streamlit secrets (`st.secrets`)
3. Local defaults

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

## Streamlit Community Cloud Deployment

1. Push this repo to GitHub (done).
2. Open [share.streamlit.io](https://share.streamlit.io) and create a new app:
   - Repository: `fisher-c/dssg-volunteer-dash`
   - Branch: `main`
   - Main file path: `app.py`
3. In app Settings -> Secrets, paste values from `.streamlit/secrets.toml.example`:
   - Keep `USE_GOOGLE_SHEETS="true"`
   - Set sheet/tab keys
   - Add credentials as either:
     - `GOOGLE_SERVICE_ACCOUNT_JSON` string, or
     - `[gcp_service_account]` table (recommended)
4. Save secrets and deploy/reboot app.

Notes:
- If Google API is unavailable, the app automatically falls back to local CSV files.
- Google Sheets reads are cached for 1 day by design.
- The app defaults to a light theme (`.streamlit/config.toml`) for consistent chart readability.

## Business Logic Implemented

- Event classification:
  - `event_name` contains `Hackathon` => `hackathon`
  - otherwise => `meetup`
- Active volunteers KPI (365 days): registered volunteers with >=1 attendance in trailing 365 days
- Activation rate: `active_volunteers_365 / total_registered_volunteers`
- Repeat participation rate (retention proxy): `% of unique attendee emails with attendance in >=2 distinct events`
- Participation concentration (Top 2): `% of total event registrations that come from top 2 events by registrations`
- Total event registrations are non-deduplicated and summed from Eventbrite `Ticket quantity`
- Hackathon hours: `participants * 9`
- Dollar impact: `hackathon_hours * $40`

## Executive KPI Definitions

- `Total Registered Volunteers`: unique emails from volunteer form submissions.
- `Active Volunteers (365 Days)`: registered volunteer emails found in event data within trailing 365 days.
- `Activation Rate`: active volunteers divided by total registered volunteers.
- `Total Event Registrations (Non-Deduplicated)`: sum of Eventbrite `Ticket quantity` across all events.
- `Unique Event Attendees`: distinct attendee emails in event records.
- `Repeat Participation Rate`: share of unique attendees with participation in 2+ distinct events (used as a retention proxy).
- `Total Events`: distinct Eventbrite events (meetups + hackathons).
- `Total Hackathons`: distinct events classified as hackathons.
- `Estimated Dollar Impact`: hackathon volunteer hours multiplied by `$40/hour`.

## Executive Interpretation Guidance

- **Activation Funnel:** Compare `Total Registered Volunteers` -> `Active Volunteers (365 Days)` to monitor conversion from sign-up to sustained engagement.
- **Retention Signal (Proxy):** Use `Repeat Participation Rate` and the monthly first-time vs repeat trend to assess whether participation is recurring or one-off.
- **Concentration Risk:** `Top 2 Event Concentration` highlights how dependent total participation is on a small set of events.
- **Mission Alignment:** Review skill, role, and nonprofit-interest distributions together to align volunteer supply with program demand.

## Troubleshooting

If you see:

`Google credentials missing. Set GOOGLE_APPLICATION_CREDENTIALS or GOOGLE_SERVICE_ACCOUNT_JSON.`

Check:

1. `GOOGLE_APPLICATION_CREDENTIALS` points to a valid JSON key path
2. Service account has at least Viewer access to the sheet
3. `.env.sh` exists and contains the variables (or shell has exports)
4. On Streamlit Cloud, credentials are set in App Settings -> Secrets
5. You restarted Streamlit after changing env values
6. If credentials are missing/invalid, the app will still run with local CSV fallback and show a diagnostic message in the UI

## Security Notes

- Keep service account keys out of git (`.gitignore` already configured).
- Use `.env.sh` / `.env` for local secrets only.
