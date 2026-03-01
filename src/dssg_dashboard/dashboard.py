from __future__ import annotations

import base64
import json
import os
import re
import shlex
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots


REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "raw"
ASSETS_DIR = REPO_ROOT / "assets"

VOLUNTEER_FILE = "volunteer_registrations.csv"
EVENT_FILE = "eventbrite_participants.csv"
LOGO_FILE = "dssg_logo.png"
LEGACY_VOLUNTEER_FILE = "DSSG-NYC Volunteer Registration (Responses) - Form Responses 1.csv"
LEGACY_EVENT_FILE = "DSSG-NYC Volunteer Registration (Responses) - Eventbrite_ Meet-ups participants.csv"
LEGACY_LOGO_FILE = "dssg_logo.png"
DEFAULT_GOOGLE_SHEETS_ID = "1AyvBMU87yUHmn9m74-NX6yDrTERYVVOXs8McvrKFqP4"
SOURCE_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/1AyvBMU87yUHmn9m74-NX6yDrTERYVVOXs8McvrKFqP4/edit?usp=sharing"
)
DEFAULT_VOLUNTEER_TAB = "Form Responses 1"
DEFAULT_EVENT_TAB = "Eventbrite: Meet-ups participants"
GOOGLE_SHEETS_CACHE_TTL_SECONDS = 86_400

HACKATHON_HOURS_PER_PERSON = 9
HACKATHON_HOURLY_RATE = 40
ACTIVE_WINDOW_DAYS = 365

BRAND_BLUE = "#0a447e"
BRAND_ORANGE = "#fe803b"
BRAND_BLUE_SCALE = ["#deebf7", "#9fc2e2", "#4f7fad", BRAND_BLUE]
BRAND_ORANGE_SCALE = ["#fee6d6", "#fcb88f", BRAND_ORANGE]


def parse_env_line(line: str) -> Optional[tuple[str, str]]:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None

    if stripped.startswith("export "):
        stripped = stripped[len("export ") :].strip()

    if "=" not in stripped:
        return None

    key, raw_value = stripped.split("=", 1)
    key = key.strip()
    if not key:
        return None

    value = raw_value.strip()
    if not value:
        return key, ""

    try:
        # Handles quoted values and escaped characters.
        parsed_tokens = shlex.split(value, posix=True)
        value = parsed_tokens[0] if parsed_tokens else ""
    except ValueError:
        value = value.strip().strip("\"").strip("'")

    return key, value


def load_local_env_files(base_dir: Path) -> None:
    for env_file_name in [".env", ".env.sh"]:
        env_path = base_dir / env_file_name
        if not env_path.exists():
            continue

        for line in env_path.read_text(encoding="utf-8").splitlines():
            parsed = parse_env_line(line)
            if not parsed:
                continue

            key, value = parsed
            os.environ.setdefault(key, value)


def read_config(name: str, default: Optional[str] = None) -> Optional[str]:
    env_value = os.getenv(name)
    if env_value is not None and env_value != "":
        return env_value

    try:
        secret_value = st.secrets.get(name)  # type: ignore[arg-type]
    except Exception:
        secret_value = None

    if secret_value is None:
        return default
    return str(secret_value)


def read_secret_mapping(name: str) -> Optional[dict[str, Any]]:
    try:
        value = st.secrets.get(name)  # type: ignore[arg-type]
    except Exception:
        return None

    if isinstance(value, dict):
        return value

    # Streamlit may return AttrDict; try dict coercion safely.
    try:
        coerced = dict(value) if value is not None else None
    except Exception:
        coerced = None
    return coerced if isinstance(coerced, dict) else None


def resolve_first_existing_path(candidates: list[Path]) -> Path:
    for candidate in candidates:
        if candidate.exists():
            return candidate

    raise FileNotFoundError(
        "None of the expected files were found: "
        + ", ".join(str(path) for path in candidates)
    )


def find_column(df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
    """Return the first matching column name (case-insensitive, trimmed)."""
    normalized = {column.strip().lower(): column for column in df.columns}
    for candidate in candidates:
        column = normalized.get(candidate.strip().lower())
        if column:
            return column
    return None


def normalize_email(series: pd.Series) -> pd.Series:
    cleaned = series.fillna("").astype(str).str.strip().str.lower()
    cleaned = cleaned.replace({"": pd.NA, "nan": pd.NA, "none": pd.NA})
    return cleaned


def parse_mixed_datetime(series: pd.Series) -> pd.Series:
    """Parse date strings and Google/Excel serial date numbers in one pass."""
    parsed = pd.to_datetime(series, errors="coerce")
    numeric = pd.to_numeric(series, errors="coerce")
    numeric = numeric.replace([float("inf"), float("-inf")], float("nan"))

    # Google Sheets UNFORMATTED_VALUE returns dates as serial day numbers.
    serial_mask = numeric.between(20_000, 70_000, inclusive="both").fillna(False)
    if serial_mask.any():
        serial_values = numeric.loc[serial_mask].astype("float64")
        serial_dates = pd.to_datetime(
            serial_values,
            unit="D",
            origin="1899-12-30",
            errors="coerce",
        )
        parsed.loc[serial_mask] = serial_dates

    return parsed


def read_bool_env(name: str, default: bool = False) -> bool:
    raw = read_config(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def build_unique_headers(raw_headers: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    headers: list[str] = []
    for index, header in enumerate(raw_headers, start=1):
        base = str(header).strip() if header is not None else ""
        if not base:
            base = f"column_{index}"

        count = seen.get(base, 0) + 1
        seen[base] = count
        headers.append(base if count == 1 else f"{base}_{count}")
    return headers


def parse_sheet_values_to_dataframe(values: list[list[str]]) -> pd.DataFrame:
    if not values:
        raise ValueError("Google Sheets API returned no rows.")

    headers = build_unique_headers(values[0])
    width = len(headers)
    rows: list[list[str]] = []
    for row in values[1:]:
        normalized = list(row[:width]) + [""] * max(0, width - len(row))
        rows.append(normalized)

    return pd.DataFrame(rows, columns=headers)


def format_cache_ttl(seconds: int) -> str:
    if seconds % 86_400 == 0:
        days = seconds // 86_400
        return f"{days} day" + ("" if days == 1 else "s")
    if seconds % 3_600 == 0:
        hours = seconds // 3_600
        return f"{hours} hour" + ("" if hours == 1 else "s")
    if seconds % 60 == 0:
        minutes = seconds // 60
        return f"{minutes} minute" + ("" if minutes == 1 else "s")
    return f"{seconds} seconds"


def build_tab_a1_range(tab_name: str) -> str:
    escaped_tab_name = tab_name.strip().replace("'", "''")
    # Google Sheets max column in A1 notation is ZZZ.
    return f"'{escaped_tab_name}'!A:ZZZ"


def load_google_sheet_tab(sheet_id: str, tab_name: str) -> pd.DataFrame:
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError(
            "Google Sheets dependencies missing. Install `google-api-python-client` and `google-auth`."
        ) from exc

    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds_json = read_config("GOOGLE_SERVICE_ACCOUNT_JSON")
    creds_path = read_config("GOOGLE_APPLICATION_CREDENTIALS")
    creds_mapping = read_secret_mapping("gcp_service_account")

    credentials = None
    if creds_json:
        try:
            info = json.loads(creds_json)
        except json.JSONDecodeError as exc:
            raise RuntimeError("`GOOGLE_SERVICE_ACCOUNT_JSON` is not valid JSON.") from exc
        credentials = service_account.Credentials.from_service_account_info(info, scopes=scopes)
    elif creds_mapping:
        credentials = service_account.Credentials.from_service_account_info(
            creds_mapping,
            scopes=scopes,
        )
    elif creds_path:
        credentials_path = Path(creds_path)
        if not credentials_path.exists():
            raise RuntimeError(f"Credential file not found: {credentials_path}")
        credentials = service_account.Credentials.from_service_account_file(
            str(credentials_path),
            scopes=scopes,
        )
    else:
        raise RuntimeError(
            "Google credentials missing. Set `GOOGLE_APPLICATION_CREDENTIALS` or `GOOGLE_SERVICE_ACCOUNT_JSON`."
        )

    service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
    response = (
        service.spreadsheets()
        .values()
        .get(
            spreadsheetId=sheet_id,
            range=build_tab_a1_range(tab_name),
            valueRenderOption="UNFORMATTED_VALUE",
        )
        .execute()
    )
    values = response.get("values", [])
    return parse_sheet_values_to_dataframe(values)


def load_google_sheet_tab_with_fallback(
    sheet_id: str,
    primary_tab_name: str,
    alternate_tab_names: list[str],
) -> tuple[pd.DataFrame, str]:
    candidates: list[str] = [primary_tab_name] + alternate_tab_names
    seen: set[str] = set()
    errors: list[tuple[str, str]] = []

    for candidate in candidates:
        tab_name = str(candidate).strip()
        if not tab_name or tab_name in seen:
            continue
        seen.add(tab_name)
        try:
            df = load_google_sheet_tab(sheet_id=sheet_id, tab_name=tab_name)
            return df, tab_name
        except Exception as exc:
            errors.append((tab_name, f"{type(exc).__name__}: {exc}"))

    tried = ", ".join([f"'{name}'" for name in seen])
    last_error = errors[-1][1] if errors else "Unknown error."
    raise RuntimeError(f"Could not load any tab from candidates [{tried}]. Last error: {last_error}")


@st.cache_data(show_spinner=False)
def load_csvs(base_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    volunteer_path = resolve_first_existing_path(
        [
            DATA_DIR / VOLUNTEER_FILE,
            base_dir / LEGACY_VOLUNTEER_FILE,
        ]
    )
    event_path = resolve_first_existing_path(
        [
            DATA_DIR / EVENT_FILE,
            base_dir / LEGACY_EVENT_FILE,
        ]
    )

    volunteers = pd.read_csv(volunteer_path)
    events = pd.read_csv(event_path)
    return volunteers, events


@st.cache_data(show_spinner=False, ttl=GOOGLE_SHEETS_CACHE_TTL_SECONDS)
def load_google_input_data(
    sheet_id: str,
    volunteer_tab: str,
    event_tab: str,
) -> tuple[pd.DataFrame, pd.DataFrame, str, str]:
    volunteers, volunteer_tab_used = load_google_sheet_tab_with_fallback(
        sheet_id=sheet_id,
        primary_tab_name=volunteer_tab,
        alternate_tab_names=["Form Responses 1", "Volunteer list", "Volunteer List"],
    )
    events, event_tab_used = load_google_sheet_tab_with_fallback(
        sheet_id=sheet_id,
        primary_tab_name=event_tab,
        alternate_tab_names=[
            "Eventbrite: Meet-ups participants",
            "Eventbrite_ Meet-ups participants",
            "Eventbrite meet up participants",
            "Eventbrite meet-up participants",
            "Eventbrite meetup participants",
        ],
    )
    return volunteers, events, volunteer_tab_used, event_tab_used


def summarize_fallback_reason(reason: Optional[str]) -> tuple[str, str, str]:
    base_note = "Using local CSV fallback data."
    if not reason:
        return base_note, "", ""

    normalized = reason.lower()
    if "google credentials missing" in normalized:
        return (
            "Using local CSV fallback data because Google Sheets credentials are not configured for this runtime.",
            "Set Streamlit app secrets (`gcp_service_account` or `GOOGLE_SERVICE_ACCOUNT_JSON`) to enable live updates.",
            reason,
        )
    if "403" in normalized or "permission" in normalized:
        return (
            "Using local CSV fallback data because the Google service account cannot access the source sheet.",
            "Share the sheet with the service-account email as Viewer and confirm the spreadsheet ID is correct.",
            reason,
        )
    if "400" in normalized or "unable to parse range" in normalized:
        return (
            "Using local CSV fallback data because one or more tab names could not be read from Google Sheets.",
            "Verify `GOOGLE_SHEETS_VOLUNTEER_TAB` and `GOOGLE_SHEETS_EVENT_TAB` values in env/secrets.",
            reason,
        )

    return (
        "Using local CSV fallback data because Google Sheets API load failed.",
        "Review the technical diagnostic details below and update Streamlit secrets as needed.",
        reason,
    )


def load_input_data(base_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, str]]:
    load_local_env_files(base_dir)
    use_google_sheets = read_bool_env("USE_GOOGLE_SHEETS", default=True)
    sheet_id = read_config("GOOGLE_SHEETS_ID", DEFAULT_GOOGLE_SHEETS_ID)
    volunteer_tab = read_config("GOOGLE_SHEETS_VOLUNTEER_TAB", DEFAULT_VOLUNTEER_TAB)
    event_tab = read_config("GOOGLE_SHEETS_EVENT_TAB", DEFAULT_EVENT_TAB)

    fallback_reason: Optional[str] = None
    if use_google_sheets:
        try:
            volunteers, events, volunteer_tab_used, event_tab_used = load_google_input_data(
                sheet_id=sheet_id,
                volunteer_tab=volunteer_tab,
                event_tab=event_tab,
            )
            return (
                volunteers,
                events,
                {
                    "source": "Google Sheets API",
                    "note": (
                        f"Using live Google Sheets data (cache refresh every {format_cache_ttl(GOOGLE_SHEETS_CACHE_TTL_SECONDS)}). "
                        f"Tabs in use: volunteer='{volunteer_tab_used}', events='{event_tab_used}'."
                    ),
                    "hint": "",
                    "detail": "",
                },
            )
        except Exception as exc:
            fallback_reason = f"{type(exc).__name__}: {exc}"

    volunteers_csv, events_csv = load_csvs(base_dir)
    message, hint, detail = summarize_fallback_reason(fallback_reason)

    return (
        volunteers_csv,
        events_csv,
        {
            "source": "Local CSV fallback",
            "note": message,
            "hint": hint,
            "detail": detail,
        },
    )


def prepare_volunteer_data(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Create a canonical volunteer table with resilient column mapping."""
    cleaned = df.copy()
    cleaned.columns = [col.strip() for col in cleaned.columns]

    registration_col = find_column(cleaned, ["Timestamp", "Registration date", "Registration Date"])
    email_col = find_column(cleaned, ["Primary Email", "Volunteer email", "Email"])

    if registration_col is None or email_col is None:
        raise ValueError("Volunteer file is missing required registration or email columns.")

    domain_col = find_column(cleaned, ["Domain of Expertise", "Domain of Expertise ", "Domain"])
    nonprofit_interest_col = find_column(
        cleaned,
        [
            "Non-Profit Domain you're interested in",
            "Nonprofit domain you're interested in",
            "Non-Profit Domain",
            "Nonprofit Domain",
        ],
    )
    years_col = find_column(
        cleaned,
        ["Years of Professional Experience", "Years of experience", "Experience"],
    )
    current_role_col = find_column(cleaned, ["Current Job / Role", "Current Role", "Role"])
    board_interest_col = find_column(
        cleaned,
        [
            "Are you interested in being on the DSSG Associate Board?",
            "Are you interested in being on the DSSG Associate Board? ",
            "Associate Board Interest",
        ],
    )
    employer_col = find_column(cleaned, ["Employer", "Company", "Organization"])
    industry_col = find_column(
        cleaned,
        ["Industry", "Industry / Sector", "Industry / Organization", "Employer"],
    )
    tools_col = find_column(cleaned, ["Tools", "Tools Used", "Top tools", "Tech Stack"])

    cleaned["registration_date"] = parse_mixed_datetime(cleaned[registration_col])
    cleaned["volunteer_email"] = normalize_email(cleaned[email_col])

    cleaned["domain"] = (
        cleaned[domain_col].fillna("Unknown").astype(str).str.strip()
        if domain_col
        else "Unknown"
    )
    cleaned["nonprofit_interest"] = (
        cleaned[nonprofit_interest_col].fillna("Unknown").astype(str).str.strip()
        if nonprofit_interest_col
        else "Unknown"
    )
    cleaned["years_experience"] = (
        cleaned[years_col].fillna("Unknown").astype(str).str.strip()
        if years_col
        else "Unknown"
    )
    cleaned["industry"] = (
        cleaned[industry_col].fillna("Unknown").astype(str).str.strip()
        if industry_col
        else "Unknown"
    )
    cleaned["current_role"] = (
        cleaned[current_role_col].fillna("Unknown").astype(str).str.strip()
        if current_role_col
        else "Unknown"
    )
    cleaned["employer"] = (
        cleaned[employer_col].fillna("Unknown").astype(str).str.strip()
        if employer_col
        else "Unknown"
    )
    cleaned["associate_board_interest"] = (
        cleaned[board_interest_col].fillna("Unknown").astype(str).str.strip()
        if board_interest_col
        else "Unknown"
    )

    # Some exports do not include a dedicated tools field; we gracefully fall back.
    if tools_col:
        cleaned["tools"] = cleaned[tools_col].fillna("Unknown").astype(str).str.strip()
        tools_source = tools_col
        tools_fallback_used = False
    else:
        cleaned["tools"] = cleaned["domain"]
        tools_source = "Domain of Expertise (fallback)"
        tools_fallback_used = True

    cleaned = cleaned.dropna(subset=["volunteer_email"]).sort_values("registration_date")
    cleaned = cleaned.drop_duplicates(subset=["volunteer_email"], keep="first")

    metadata = {
        "industry_source": industry_col if industry_col else "Unavailable",
        "tools_source": tools_source,
        "industry_fallback_used": industry_col == "Employer",
        "tools_fallback_used": tools_fallback_used,
    }
    return cleaned, metadata


def prepare_event_data(df: pd.DataFrame) -> pd.DataFrame:
    """Clean Eventbrite exports, remove totals row, and derive analysis columns."""
    cleaned = df.copy()
    cleaned.columns = [col.strip() for col in cleaned.columns]

    event_name_col = find_column(cleaned, ["Event name", "Event Name"])
    event_date_col = find_column(cleaned, ["Event start date", "Event date", "Start date"])
    email_col = find_column(cleaned, ["Buyer email", "Attendee email", "Email"])
    ticket_qty_col = find_column(cleaned, ["Ticket quantity", "Ticket Quantity", "Quantity"])
    order_id_col = find_column(cleaned, ["Order ID", "Order Id"])

    if event_name_col is None or event_date_col is None or ticket_qty_col is None:
        raise ValueError("Event file is missing required event name/date/ticket quantity columns.")

    if order_id_col:
        cleaned = cleaned[cleaned[order_id_col].astype(str).str.upper() != "TOTALS"]

    cleaned["event_name"] = cleaned[event_name_col].fillna("Unknown Event").astype(str).str.strip()
    cleaned["event_date"] = parse_mixed_datetime(cleaned[event_date_col])
    cleaned["participant_email"] = (
        normalize_email(cleaned[email_col]) if email_col else pd.Series(pd.NA, index=cleaned.index)
    )

    cleaned["participant_count"] = pd.to_numeric(cleaned[ticket_qty_col], errors="coerce").fillna(1)
    cleaned["participant_count"] = cleaned["participant_count"].clip(lower=1).astype(int)

    cleaned["event_type"] = cleaned["event_name"].str.contains("hackathon", case=False, na=False).map(
        {True: "hackathon", False: "meetup"}
    )

    cleaned["event_month"] = cleaned["event_date"].dt.to_period("M").dt.to_timestamp()
    cleaned["event_key"] = (
        cleaned["event_name"]
        + " | "
        + cleaned["event_date"].dt.strftime("%Y-%m-%d").fillna("Unknown Date")
    )

    cleaned = cleaned[cleaned["event_name"].notna()]
    return cleaned


def compute_overview_metrics(
    volunteers: pd.DataFrame,
    events: pd.DataFrame,
    active_days: int = ACTIVE_WINDOW_DAYS,
) -> dict[str, float]:
    activation = compute_activation_metrics(volunteers, events, active_days=active_days)
    repeat = compute_repeat_attendance_metrics(events)
    concentration = compute_participation_concentration(events, top_n=2)
    hackathon_events = events[events["event_type"] == "hackathon"]
    hackathon_participants = int(hackathon_events["participant_count"].sum())
    hackathon_hours = hackathon_participants * HACKATHON_HOURS_PER_PERSON
    dollar_impact = hackathon_hours * HACKATHON_HOURLY_RATE
    total_participants = int(events["participant_count"].sum())
    meetup_participants = int(events.loc[events["event_type"] == "meetup", "participant_count"].sum())
    hackathon_share = (
        (hackathon_participants / total_participants) if total_participants > 0 else 0.0
    )
    meetup_share = (meetup_participants / total_participants) if total_participants > 0 else 0.0

    return {
        "total_registered_volunteers": int(activation["total_registered_volunteers"]),
        "active_volunteers": int(activation["active_volunteers"]),
        "activation_rate": float(activation["activation_rate"]),
        "unique_event_attendees": int(activation["unique_event_attendees"]),
        "total_unique_emails": int(activation["total_unique_emails"]),
        "registered_to_attendee_overlap": int(activation["registered_to_attendee_overlap"]),
        "total_events": int(events["event_key"].nunique()),
        "total_event_registrations": int(total_participants),
        "total_hackathons": int(hackathon_events["event_key"].nunique()),
        "repeat_attendees": int(repeat["repeat_attendees"]),
        "repeat_attendee_rate": float(repeat["repeat_attendee_rate"]),
        "top_2_concentration_pct": float(concentration["concentration_pct"]),
        "top_2_registrations": int(concentration["top_n_registrations"]),
        "hackathon_hours": int(hackathon_hours),
        "dollar_impact": int(dollar_impact),
        "meetup_share": float(meetup_share),
        "hackathon_share": float(hackathon_share),
    }


def compute_activation_metrics(
    volunteers: pd.DataFrame,
    events: pd.DataFrame,
    active_days: int = ACTIVE_WINDOW_DAYS,
) -> dict[str, float]:
    today = pd.Timestamp.today().normalize()
    registered_emails = set(volunteers["volunteer_email"].dropna())
    attendee_emails = set(events["participant_email"].dropna())
    overlap = registered_emails.intersection(attendee_emails)
    unique_email_union = registered_emails.union(attendee_emails)

    active_window_events = events[
        events["event_date"].notna() & (events["event_date"] >= today - pd.Timedelta(days=active_days))
    ]
    active_window_emails = set(active_window_events["participant_email"].dropna())
    active_registered = registered_emails.intersection(active_window_emails)

    total_registered = len(registered_emails)
    activation_rate = (len(active_registered) / total_registered) if total_registered > 0 else 0.0

    return {
        "total_registered_volunteers": float(total_registered),
        "unique_event_attendees": float(len(attendee_emails)),
        "total_unique_emails": float(len(unique_email_union)),
        "registered_to_attendee_overlap": float(len(overlap)),
        "active_volunteers": float(len(active_registered)),
        "activation_rate": float(activation_rate),
    }


def compute_repeat_attendance_metrics(events: pd.DataFrame) -> dict[str, float]:
    attendee_events = (
        events.dropna(subset=["participant_email", "event_key"])
        .loc[:, ["participant_email", "event_key"]]
        .drop_duplicates()
    )

    if attendee_events.empty:
        return {
            "unique_attendees": 0.0,
            "repeat_attendees": 0.0,
            "repeat_attendee_rate": 0.0,
        }

    events_per_attendee = attendee_events.groupby("participant_email")["event_key"].nunique()
    unique_attendees = int(events_per_attendee.shape[0])
    repeat_attendees = int((events_per_attendee >= 2).sum())
    repeat_rate = (repeat_attendees / unique_attendees) if unique_attendees > 0 else 0.0

    return {
        "unique_attendees": float(unique_attendees),
        "repeat_attendees": float(repeat_attendees),
        "repeat_attendee_rate": float(repeat_rate),
    }


def compute_monthly_first_vs_repeat(events: pd.DataFrame) -> pd.DataFrame:
    attendee_events = (
        events.dropna(subset=["participant_email", "event_date", "event_key"])
        .loc[:, ["participant_email", "event_date", "event_key"]]
        .drop_duplicates()
        .sort_values("event_date")
    )
    if attendee_events.empty:
        return pd.DataFrame(columns=["event_month", "first_time_attendees", "repeat_attendees"])

    attendee_events["attendance_rank"] = attendee_events.groupby("participant_email").cumcount()
    attendee_events["attendance_type"] = attendee_events["attendance_rank"].eq(0).map(
        {True: "first_time_attendees", False: "repeat_attendees"}
    )
    attendee_events["event_month"] = attendee_events["event_date"].dt.to_period("M").dt.to_timestamp()

    monthly = (
        attendee_events.groupby(["event_month", "attendance_type"], as_index=False)["participant_email"]
        .nunique()
        .rename(columns={"participant_email": "attendees"})
    )
    pivot = monthly.pivot(
        index="event_month", columns="attendance_type", values="attendees"
    ).fillna(0)
    for col in ["first_time_attendees", "repeat_attendees"]:
        if col not in pivot.columns:
            pivot[col] = 0
    pivot = pivot.reset_index().sort_values("event_month")
    pivot["first_time_attendees"] = pivot["first_time_attendees"].astype(int)
    pivot["repeat_attendees"] = pivot["repeat_attendees"].astype(int)
    return pivot[["event_month", "first_time_attendees", "repeat_attendees"]]


def compute_participation_concentration(events: pd.DataFrame, top_n: int = 2) -> dict[str, float]:
    per_event = compute_event_participants(events)
    if per_event.empty:
        return {"top_n_events": float(top_n), "top_n_registrations": 0.0, "concentration_pct": 0.0}

    total_registrations = int(per_event["participants"].sum())
    top_n_registrations = int(
        per_event.sort_values("participants", ascending=False).head(top_n)["participants"].sum()
    )
    concentration_pct = (
        (top_n_registrations / total_registrations) if total_registrations > 0 else 0.0
    )
    return {
        "top_n_events": float(top_n),
        "top_n_registrations": float(top_n_registrations),
        "concentration_pct": float(concentration_pct),
    }


def compute_nonprofit_interest_distribution(
    volunteers: pd.DataFrame, top_n: int = 10
) -> pd.DataFrame:
    return split_multiselect_counts(volunteers["nonprofit_interest"], top_n=top_n)


def compute_data_quality_metrics(volunteers: pd.DataFrame, events: pd.DataFrame) -> dict[str, float]:
    role_unknown = volunteers["current_role"].fillna("").astype(str).str.strip().str.lower()
    employer_unknown = volunteers["employer"].fillna("").astype(str).str.strip().str.lower()
    invalid_tokens = {"", "nan", "none", "na", "n/a", "null", "unknown"}

    missing_role_pct = float(role_unknown.isin(invalid_tokens).mean()) if len(volunteers) else 0.0
    missing_employer_pct = (
        float(employer_unknown.isin(invalid_tokens).mean()) if len(volunteers) else 0.0
    )
    missing_participant_email_pct = (
        float(events["participant_email"].isna().mean()) if len(events) else 0.0
    )

    return {
        "missing_current_role_pct": missing_role_pct,
        "missing_employer_pct": missing_employer_pct,
        "missing_participant_email_pct": missing_participant_email_pct,
    }


def compute_monthly_registration_trends(volunteers: pd.DataFrame) -> pd.DataFrame:
    growth = volunteers.dropna(subset=["registration_date"]).copy()
    growth["registration_month"] = growth["registration_date"].dt.to_period("M").dt.to_timestamp()

    monthly = (
        growth.groupby("registration_month", as_index=False)["volunteer_email"]
        .nunique()
        .rename(columns={"volunteer_email": "new_registrations"})
        .sort_values("registration_month")
    )

    monthly["cumulative_volunteers"] = monthly["new_registrations"].cumsum()
    previous_new = monthly["new_registrations"].shift(1)
    monthly["mom_growth_pct"] = (
        (monthly["new_registrations"] - previous_new) / previous_new * 100
    ).where(previous_new > 0)
    return monthly


def compute_registered_base_mom_snapshot(growth: pd.DataFrame) -> dict[str, Optional[str]]:
    if growth.empty:
        return {"delta_text": None}

    sorted_growth = growth.sort_values("registration_month").reset_index(drop=True)
    if len(sorted_growth) < 2:
        return {"delta_text": None}

    latest = sorted_growth.iloc[-1]
    previous = sorted_growth.iloc[-2]
    prev_cumulative = float(previous["cumulative_volunteers"])
    if prev_cumulative <= 0:
        return {"delta_text": None}

    latest_cumulative = float(latest["cumulative_volunteers"])
    mom_pct = (latest_cumulative - prev_cumulative) / prev_cumulative * 100
    return {"delta_text": f"{mom_pct:+.1f}% MoM"}


def compute_monthly_participant_trends(events: pd.DataFrame) -> pd.DataFrame:
    monthly = (
        events.dropna(subset=["event_month"])
        .groupby(["event_month", "event_type"], as_index=False)["participant_count"]
        .sum()
        .rename(columns={"participant_count": "participants"})
        .sort_values("event_month")
    )

    if monthly.empty:
        return monthly

    pivot = monthly.pivot(index="event_month", columns="event_type", values="participants").fillna(0)
    for required_col in ["meetup", "hackathon"]:
        if required_col not in pivot.columns:
            pivot[required_col] = 0

    pivot = pivot.reset_index().sort_values("event_month")
    pivot["total_participants"] = pivot["meetup"] + pivot["hackathon"]
    return pivot[["event_month", "meetup", "hackathon", "total_participants"]]


def compute_event_participants(events: pd.DataFrame) -> pd.DataFrame:
    per_event = (
        events.dropna(subset=["event_date"])
        .groupby(["event_key", "event_name", "event_date", "event_type"], as_index=False)["participant_count"]
        .sum()
        .rename(columns={"participant_count": "participants"})
        .sort_values("event_date")
    )
    return per_event


def compute_type_breakdown(events: pd.DataFrame) -> pd.DataFrame:
    breakdown = (
        events.groupby("event_type", as_index=False)["participant_count"]
        .sum()
        .rename(columns={"participant_count": "participants"})
        .sort_values("participants", ascending=False)
    )
    return breakdown


def compute_hackathon_impact(events: pd.DataFrame) -> pd.DataFrame:
    per_event = compute_event_participants(events)
    hackathon = per_event[per_event["event_type"] == "hackathon"].copy()
    hackathon["hackathon_hours"] = hackathon["participants"] * HACKATHON_HOURS_PER_PERSON
    hackathon["dollar_impact"] = hackathon["hackathon_hours"] * HACKATHON_HOURLY_RATE
    return hackathon


def split_multiselect_counts(series: pd.Series, top_n: Optional[int] = None) -> pd.DataFrame:
    tokens = (
        series.fillna("Unknown")
        .astype(str)
        .str.split(",")
        .explode()
        .str.strip()
        .replace({"": "Unknown", "nan": "Unknown"})
    )

    counts = tokens.value_counts().reset_index()
    counts.columns = ["category", "count"]

    if top_n is not None:
        counts = counts.head(top_n)
    return counts


def single_value_counts(series: pd.Series, top_n: Optional[int] = None) -> pd.DataFrame:
    cleaned = series.fillna("").astype(str).str.strip()
    invalid = cleaned.str.lower().isin({"", "nan", "none", "na", "n/a", "null", "unknown"})
    cleaned = cleaned.where(~invalid, "Unknown")

    counts = cleaned.value_counts().reset_index()
    counts.columns = ["category", "count"]

    if top_n is not None:
        counts = counts.head(top_n)
    return counts


def compute_background_views(volunteers: pd.DataFrame) -> dict[str, pd.DataFrame]:
    domain = split_multiselect_counts(volunteers["domain"], top_n=12)
    nonprofit_interest = compute_nonprofit_interest_distribution(volunteers, top_n=10)

    years = volunteers["years_experience"].fillna("Unknown").astype(str).str.strip()
    ordered_years = ["0-1 year", "2-5 years", "5-8 years", "8+ years", "Unknown"]
    years = pd.Categorical(years, categories=ordered_years, ordered=True)
    years_dist = pd.Series(years).value_counts(dropna=False).sort_index().reset_index()
    years_dist.columns = ["category", "count"]
    years_dist = years_dist[years_dist["count"] > 0]

    employer = single_value_counts(volunteers["employer"], top_n=10)
    current_role = single_value_counts(
        volunteers["current_role"].map(normalize_current_role_category),
        top_n=10,
    )

    return {
        "domain": domain,
        "years": years_dist,
        "employer": employer,
        "current_role": current_role,
        "nonprofit_interest": nonprofit_interest,
    }


def normalize_current_role_category(value: Any) -> str:
    """Standardize role labels for cleaner grouping and case-insensitive matching."""
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "na", "n/a", "null", "unknown"}:
        return "Unknown"

    normalized = re.sub(r"[^a-z0-9\s/&+-]", " ", text.lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    has_ai_word = bool(re.search(r"\bai\b", normalized))
    has_it_word = bool(re.search(r"\bit\b", normalized))

    if any(token in normalized for token in ["student", "phd", "graduate", "undergrad", "candidate"]):
        return "Student"
    if any(token in normalized for token in ["founder", "co-founder", "founding", "entrepreneur"]):
        return "Founder"
    if "data engineer" in normalized:
        return "Data Engineer"
    if any(token in normalized for token in ["data scientist", "data science", "statistician", "data strategy"]):
        return "Data Science"
    if any(token in normalized for token in ["data analyst", "analyst", "business analyst", "analytics"]):
        return "Analyst"
    if "data" in normalized:
        return "Data Science"
    if any(
        token in normalized
        for token in [
            "machine learning engineer",
            "ml engineer",
            "machine learning scientist",
            "ml scientist",
            "ai engineer",
            "ai scientist",
            "applied scientist",
            "mlops",
            "ai solutions engineer",
        ]
    ) or has_ai_word:
        return "Machine Learning"
    if any(
        token in normalized
        for token in [
            "software",
            "software engineer",
            "software developer",
            "developer",
            "web dev",
            "web developer",
            "full stack",
            "frontend",
            "backend",
            "swe",
        ]
    ) or has_it_word:
        return "Software"
    if any(token in normalized for token in ["recent grad", "recent college grad", "unemployed", "job seeking", "fellow", "trainee"]):
        return "Early Career / Job Seeking"
    if any(token in normalized for token in ["product manager", "pm ", " product ", "product owner"]):
        return "Product"
    if any(token in normalized for token in ["research", "research assistant", "scientist"]):
        return "Research"
    if any(token in normalized for token in ["design", "designer", "ux", "ui"]):
        return "Design"
    if any(token in normalized for token in ["lecturer", "professor", "teacher", "instructor"]):
        return "Education"
    if "consultant" in normalized:
        return "Consultant"
    if any(token in normalized for token in ["director", "manager", "lead", "head", "chief", "vp", "president"]):
        return "Leadership / Management"
    if any(token in normalized for token in ["assistant", "operations", "admin"]):
        return "Operations / Administration"
    if "engineer" in normalized:
        return "Engineering (Other)"

    return "Other"


def compute_section_one_context(volunteers: pd.DataFrame, events: pd.DataFrame) -> dict[str, int]:
    registered_emails = set(volunteers["volunteer_email"].dropna())
    event_attendee_emails = set(events["participant_email"].dropna())
    matched_registered_attendees = len(registered_emails.intersection(event_attendee_emails))
    external_attendees = max(0, len(event_attendee_emails) - matched_registered_attendees)
    return {
        "unique_event_attendees": int(len(event_attendee_emails)),
        "matched_registered_attendees": int(matched_registered_attendees),
        "external_attendees": int(external_attendees),
    }


def build_executive_insights(kpis: dict[str, float]) -> list[str]:
    activation_rate = float(kpis.get("activation_rate", 0.0))
    repeat_rate = float(kpis.get("repeat_attendee_rate", 0.0))
    meetup_share = float(kpis.get("meetup_share", 0.0))
    hackathon_share = float(kpis.get("hackathon_share", 0.0))
    top_2_concentration_pct = float(kpis.get("top_2_concentration_pct", 0.0))

    return [
        (
            f"Activation: {format_percent(activation_rate)} of registered volunteers are active in the trailing "
            f"{ACTIVE_WINDOW_DAYS} days ({format_int(kpis.get('active_volunteers', 0))} of "
            f"{format_int(kpis.get('total_registered_volunteers', 0))})."
        ),
        (
            f"Repeat participation (retention proxy): {format_percent(repeat_rate)} of unique attendees returned for 2+ events "
            f"({format_int(kpis.get('repeat_attendees', 0))} of {format_int(kpis.get('unique_event_attendees', 0))})."
        ),
        (
            f"Participation mix: Meetups contributed {format_percent(meetup_share)} of registrations and hackathons "
            f"{format_percent(hackathon_share)}; top 2 events account for "
            f"{format_percent(top_2_concentration_pct)} of all event registrations."
        ),
    ]


def format_int(value: float) -> str:
    return f"{int(value):,}"


def format_percent(value: float, decimals: int = 1) -> str:
    return f"{value * 100:.{decimals}f}%"


def format_currency(value: float) -> str:
    return f"${int(value):,}"


def format_event_label(event_type: str, event_date: pd.Timestamp) -> str:
    event_prefix = "Hackathon" if event_type == "hackathon" else "Meetup"
    if pd.isna(event_date):
        return f"{event_prefix} (Unknown date)"
    return f"{event_prefix} ({event_date.strftime('%Y-%m-%d')})"


def build_chart_theme(
    fig,
    show_legend: bool = False,
    reserve_legend_space: bool = False,
):
    layout_config = {
        "margin": dict(
            l=20,
            r=20,
            t=115 if (show_legend or reserve_legend_space) else 70,
            b=20,
        ),
        "legend_title_text": "",
        "showlegend": show_legend,
        "template": "plotly_white",
        "title": dict(x=0, xanchor="left", font=dict(size=18, color=BRAND_BLUE)),
        "font": dict(color="#243447"),
        "paper_bgcolor": "white",
        "plot_bgcolor": "white",
    }

    if show_legend:
        layout_config["legend"] = dict(
            orientation="h",
            x=0.99,
            y=1.10,
            xanchor="right",
            yanchor="bottom",
            bgcolor="rgba(255,255,255,0.85)",
            bordercolor="#D9E1EA",
            borderwidth=1,
        )

    fig.update_layout(**layout_config)
    fig.update_xaxes(title_font=dict(color="#44546A"), tickfont=dict(color="#5F6C80"))
    fig.update_yaxes(title_font=dict(color="#44546A"), tickfont=dict(color="#5F6C80"))
    return fig


def hide_colorbar_legend(fig):
    fig.update_layout(coloraxis_showscale=False)
    fig.update_traces(marker_showscale=False)
    return fig


def render_dashboard() -> None:
    base_dir = REPO_ROOT
    load_local_env_files(base_dir)

    logo_candidates = [ASSETS_DIR / LOGO_FILE, base_dir / LEGACY_LOGO_FILE]
    logo_path = next((path for path in logo_candidates if path.exists()), None)

    st.set_page_config(
        page_title="DSSG NYC Volunteer Dashboard",
        page_icon=str(logo_path) if logo_path else "📊",
        layout="wide",
    )
    if logo_path:
        logo_b64 = base64.b64encode(logo_path.read_bytes()).decode("utf-8")
        st.markdown(
            f"""
            <div style="display:flex; align-items:center; gap:14px; margin-bottom:4px;">
                <img src="data:image/png;base64,{logo_b64}" style="height:48px; width:auto;" />
                <h1 style="margin:0; font-size:48px; line-height:1; color:inherit;">
                    DSSG NYC Volunteer Dashboard
                </h1>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.title("DSSG NYC Volunteer Dashboard")

    st.caption(
        "Internal dashboard for volunteer growth, activation, retention, and estimated social impact."
    )
    st.caption(
        "Data model: volunteer registrations come from the website Google Form tab; event participation comes from the Eventbrite participants tab (meetups + hackathons)."
    )

    volunteers_raw, events_raw, source_info = load_input_data(base_dir)
    volunteers, _ = prepare_volunteer_data(volunteers_raw)
    events = prepare_event_data(events_raw)

    source_link = f"[Open source sheet]({SOURCE_SHEET_URL})"
    if source_info["source"] == "Google Sheets API":
        st.caption(f"Data source: {source_info['source']} | {source_info['note']} {source_link}")
    else:
        st.info(f"Data source: {source_info['source']} | {source_info['note']} {source_link}")
        if source_info.get("hint"):
            st.caption(source_info["hint"])
        if source_info.get("detail"):
            with st.expander("Data source diagnostics", expanded=False):
                st.code(source_info["detail"])

    last_refresh = pd.Timestamp.now().strftime("%Y-%m-%d %I:%M %p")
    st.caption(f"Dashboard rendered: {last_refresh}.")

    overview = compute_overview_metrics(volunteers, events, active_days=ACTIVE_WINDOW_DAYS)
    section_one_context = compute_section_one_context(volunteers, events)
    concentration = compute_participation_concentration(events, top_n=2)
    data_quality = compute_data_quality_metrics(volunteers, events)
    growth = compute_monthly_registration_trends(volunteers)
    registered_base_snapshot = compute_registered_base_mom_snapshot(growth)
    monthly_participants = compute_monthly_participant_trends(events)
    monthly_first_vs_repeat = compute_monthly_first_vs_repeat(events)
    per_event = compute_event_participants(events)
    type_breakdown = compute_type_breakdown(events)
    hackathon_impact = compute_hackathon_impact(events)
    background = compute_background_views(volunteers)
    executive_insights = build_executive_insights(overview)

    st.divider()
    st.header("Executive Snapshot")
    st.write("Executive readout on activation, repeat participation, concentration, and impact.")
    for insight in executive_insights:
        st.markdown(f"- {insight}")

    exec_row1 = st.columns(4)
    exec_row1[0].metric(
        "Registered Volunteers",
        format_int(overview["total_registered_volunteers"]),
        delta=registered_base_snapshot["delta_text"],
        delta_color="normal",
    )
    exec_row1[1].metric(
        f"Active ({ACTIVE_WINDOW_DAYS}D)",
        format_int(overview["active_volunteers"]),
    )
    exec_row1[2].metric("Active Rate", format_percent(overview["activation_rate"]))
    exec_row1[3].metric("Total Events", format_int(overview["total_events"]))

    exec_row2 = st.columns(4)
    exec_row2[0].metric(
        "Event Registrations",
        format_int(overview["total_event_registrations"]),
    )
    exec_row2[1].metric(
        "Unique Attendees",
        format_int(overview["unique_event_attendees"]),
    )
    exec_row2[2].metric(
        "Repeat Participation",
        format_percent(overview["repeat_attendee_rate"]),
    )
    exec_row2[3].metric(
        "Top 2 Event Share",
        format_percent(overview["top_2_concentration_pct"]),
    )

    exec_row3 = st.columns(2)
    exec_row3[0].metric("Hackathons", format_int(overview["total_hackathons"]))
    exec_row3[1].metric("Dollar Impact (Est.)", format_currency(overview["dollar_impact"]))

    st.divider()
    st.header("Section 1: Overview KPIs")
    st.write("KPIs are grouped by reach, conversion, program scale, and impact.")

    st.markdown("**Reach**")
    reach_cols = st.columns(3)
    reach_cols[0].metric("Registered Volunteers", format_int(overview["total_registered_volunteers"]))
    reach_cols[1].metric("Unique Event Attendees", format_int(overview["unique_event_attendees"]))
    reach_cols[2].metric("Total Unique Emails", format_int(overview["total_unique_emails"]))

    st.markdown("**Conversion**")
    conversion_cols = st.columns(2)
    conversion_cols[0].metric(
        f"Active Volunteers ({ACTIVE_WINDOW_DAYS}D)",
        format_int(overview["active_volunteers"]),
    )
    conversion_cols[1].metric("Activation Rate", format_percent(overview["activation_rate"]))

    st.markdown("**Program Scale**")
    scale_cols = st.columns(3)
    scale_cols[0].metric("Events", format_int(overview["total_events"]))
    scale_cols[1].metric(
        "Event Registrations",
        format_int(overview["total_event_registrations"]),
    )
    scale_cols[2].metric("Hackathons", format_int(overview["total_hackathons"]))

    st.markdown("**Impact**")
    impact_kpi_cols = st.columns(2)
    impact_kpi_cols[0].metric(
        "Hackathon Hours (Est.)",
        format_int(overview["hackathon_hours"]),
    )
    impact_kpi_cols[1].metric("Dollar Impact (Est.)", format_currency(overview["dollar_impact"]))

    with st.expander("How to Read These KPIs", expanded=False):
        st.markdown(
            f"""
            - **Total Registered Volunteers:** Unique emails from volunteer form submissions.
            - **Active Volunteers ({ACTIVE_WINDOW_DAYS} Days):** Registered volunteers whose email appears in event participation records within the last {ACTIVE_WINDOW_DAYS} days.
            - **Activation Rate:** Active volunteers divided by total registered volunteers.
            - **Total Event Registrations (Non-Deduplicated):** Sum of Eventbrite `Ticket quantity` across all events (repeat attendance is counted).
            - **Unique Event Attendees:** Distinct attendee emails in event records.
            - **Total Unique Emails:** Deduplicated union of registered volunteer emails and event attendee emails.
            - **Repeat Participation Rate:** Share of unique attendee emails with attendance at 2 or more distinct events. This is a retention proxy, not longitudinal membership retention.
            - **Method Notes:** Hackathon hours = participants × {HACKATHON_HOURS_PER_PERSON}; dollar impact = hours × ${HACKATHON_HOURLY_RATE}/hour.
            - **Current Overlap Context:** {format_int(section_one_context['matched_registered_attendees'])} registered volunteers attended at least one event; {format_int(section_one_context['external_attendees'])} attendee emails are not in the volunteer registration sheet.
            """
        )

    with st.expander("Data and Interpretation Limits", expanded=False):
        st.markdown(
            f"""
            - **Email Match Logic:** Cross-source matching is based on email only. If someone used different emails across form and Eventbrite, overlap and activation can be understated.
            - **Registration vs Check-In:** Event metrics are based on Eventbrite registrations/ticket quantity, not confirmed event check-ins.
            - **Active vs Registered with >=1 Event:** Because the current program history is under {ACTIVE_WINDOW_DAYS} days, these two metrics may currently match. They will diverge once data spans beyond {ACTIVE_WINDOW_DAYS} days.
            - **Repeat Participation Scope:** Repeat participation indicates repeated event registrations by attendee email; it is used here as a practical retention proxy.
            """
        )

    st.divider()
    st.header("Section 2: Volunteer Growth")
    st.write("Track volunteer pipeline health with monthly registrations, growth rate, and cumulative base size.")

    if growth.empty:
        st.info("No registration trend data is available after date parsing.")
    else:
        col1, col2 = st.columns(2)

        fig_new = make_subplots(specs=[[{"secondary_y": True}]])
        fig_new.add_trace(
            go.Bar(
                x=growth["registration_month"],
                y=growth["new_registrations"],
                name="New registrations",
                marker_color=BRAND_BLUE,
            ),
            secondary_y=False,
        )
        fig_new.add_trace(
            go.Scatter(
                x=growth["registration_month"],
                y=growth["mom_growth_pct"],
                name="MoM growth",
                mode="lines+markers",
                line=dict(color=BRAND_ORANGE, width=2),
                marker=dict(size=7),
                hovertemplate="MoM growth: %{y:.1f}%<extra></extra>",
            ),
            secondary_y=True,
        )
        fig_new.update_layout(
            title="Monthly Registrations + MoM Change",
            hovermode="x unified",
            showlegend=False,
        )
        fig_new.update_xaxes(title_text="")
        fig_new.update_yaxes(title_text="New volunteers", secondary_y=False)
        fig_new.update_yaxes(
            title_text="MoM growth (%)",
            secondary_y=True,
            tickformat=".0f",
            ticksuffix="%",
        )
        fig_new = build_chart_theme(fig_new, show_legend=False)
        fig_new.update_yaxes(
            title_font=dict(color=BRAND_BLUE),
            tickfont=dict(color=BRAND_BLUE),
            secondary_y=False,
        )
        fig_new.update_yaxes(
            title_font=dict(color=BRAND_ORANGE),
            tickfont=dict(color=BRAND_ORANGE),
            secondary_y=True,
        )
        col1.plotly_chart(fig_new, use_container_width=True)

        fig_cumulative = px.area(
            growth,
            x="registration_month",
            y="cumulative_volunteers",
            title="Cumulative Registered Volunteers",
            labels={
                "registration_month": "Month",
                "cumulative_volunteers": "Cumulative Volunteers",
            },
        )
        fig_cumulative.update_traces(
            line=dict(color=BRAND_BLUE, width=3),
            fillcolor="rgba(10,68,126,0.20)",
        )
        fig_cumulative.update_xaxes(title_text="")
        fig_cumulative.update_yaxes(tickformat=".0f")
        col2.plotly_chart(
            build_chart_theme(fig_cumulative, reserve_legend_space=True),
            use_container_width=True,
        )

    st.divider()
    st.header("Section 3: Event Participation")
    st.write("Assess participation volume, event-type mix, and repeat participation.")

    concentration_cols = st.columns(2)
    concentration_cols[0].metric(
        "Top 2 Event Share of Registrations",
        format_percent(concentration["concentration_pct"]),
    )
    concentration_cols[1].metric(
        "Registrations from Top 2 Events",
        format_int(concentration["top_n_registrations"]),
    )

    if monthly_participants.empty:
        st.info("No event participation trend is available after date parsing.")
    else:
        fig_monthly = go.Figure()
        fig_monthly.add_trace(
            go.Bar(
                x=monthly_participants["event_month"],
                y=monthly_participants["meetup"],
                name="Meetup registrations",
                marker_color=BRAND_BLUE,
            )
        )
        fig_monthly.add_trace(
            go.Bar(
                x=monthly_participants["event_month"],
                y=monthly_participants["hackathon"],
                name="Hackathon registrations",
                marker_color=BRAND_ORANGE,
            )
        )
        fig_monthly.update_layout(
            barmode="stack",
            hovermode="x unified",
            title="Monthly Registrations by Event Type",
        )
        fig_monthly.add_trace(
            go.Scatter(
                x=monthly_participants["event_month"],
                y=monthly_participants["total_participants"],
                mode="text",
                text=monthly_participants["total_participants"].astype(int).astype(str),
                textposition="top center",
                showlegend=False,
                hoverinfo="skip",
                cliponaxis=False,
                textfont=dict(color="#243447", size=11),
            )
        )
        if monthly_participants["total_participants"].max() > 0:
            fig_monthly.update_yaxes(
                range=[0, monthly_participants["total_participants"].max() * 1.15]
            )
        fig_monthly.update_xaxes(title_text="")
        fig_monthly.update_yaxes(title_text="Registrations")
        st.plotly_chart(build_chart_theme(fig_monthly, show_legend=True), use_container_width=True)

    col3, col4 = st.columns(2)

    if per_event.empty:
        col3.info("No event-level participant view is available.")
    else:
        chart_data = per_event.copy().sort_values("event_date")
        chart_data["event_display_name"] = chart_data.apply(
            lambda row: row["event_name"] if row["event_type"] == "hackathon" else "Meetup",
            axis=1,
        )
        chart_data["bar_text"] = chart_data.apply(
            lambda row: row["event_name"] if row["event_type"] == "hackathon" else "",
            axis=1,
        )
        fig_per_event = px.bar(
            chart_data,
            x="event_date",
            y="participants",
            color="event_type",
            color_discrete_map={"meetup": BRAND_BLUE, "hackathon": BRAND_ORANGE},
            title="Registrations by Event Date",
            labels={
                "event_date": "Event date",
                "participants": "Registrations",
                "event_type": "Event type",
            },
            custom_data=["event_name", "event_display_name"],
            text="bar_text",
        )
        fig_per_event.update_traces(
            textposition="outside",
            cliponaxis=False,
            hovertemplate=(
                "Date: %{x|%Y-%m-%d}<br>"
                "Registrations: %{y}<br>"
                "Event: %{customdata[0]}<br>"
                "Type: %{customdata[1]}<extra></extra>"
            ),
        )
        col3.plotly_chart(build_chart_theme(fig_per_event, show_legend=True), use_container_width=True)

    if type_breakdown.empty:
        col4.info("No meetup vs hackathon breakdown is available.")
    else:
        fig_type = px.pie(
            type_breakdown,
            values="participants",
            names="event_type",
            color="event_type",
            color_discrete_map={"meetup": BRAND_BLUE, "hackathon": BRAND_ORANGE},
            title="Registration Mix by Event Type",
            hole=0.45,
        )
        fig_type.update_traces(textposition="inside", textinfo="percent+label")
        col4.plotly_chart(build_chart_theme(fig_type, show_legend=True), use_container_width=True)

    if monthly_first_vs_repeat.empty:
        st.info("No repeat attendance trend is available.")
    else:
        fig_repeat = go.Figure()
        fig_repeat.add_trace(
            go.Bar(
                x=monthly_first_vs_repeat["event_month"],
                y=monthly_first_vs_repeat["first_time_attendees"],
                name="First-time attendees",
                marker_color=BRAND_BLUE,
            )
        )
        fig_repeat.add_trace(
            go.Bar(
                x=monthly_first_vs_repeat["event_month"],
                y=monthly_first_vs_repeat["repeat_attendees"],
                name="Repeat attendees",
                marker_color=BRAND_ORANGE,
            )
        )
        fig_repeat.update_layout(
            barmode="stack",
            hovermode="x unified",
            title="Monthly Attendee Mix: First-Time vs Repeat",
        )
        fig_repeat.update_xaxes(title_text="")
        fig_repeat.update_yaxes(title_text="Unique attendees")
        st.plotly_chart(build_chart_theme(fig_repeat, show_legend=True), use_container_width=True)

    st.divider()
    st.header("Section 4: Impact")
    st.write(
        f"Impact estimates from hackathon participation. Assumptions: hours = participants × {HACKATHON_HOURS_PER_PERSON}; dollar impact = hours × ${HACKATHON_HOURLY_RATE}."
    )

    impact_col1, impact_col2, impact_col3 = st.columns(3)
    impact_col1.metric("Total Hackathon Hours", format_int(overview["hackathon_hours"]))
    impact_col2.metric("Estimated Dollar Impact", format_currency(overview["dollar_impact"]))
    impact_col3.metric(
        "Avg. Hackathon Hours per Event",
        format_int(
            0
            if overview["total_hackathons"] == 0
            else overview["hackathon_hours"] / overview["total_hackathons"]
        ),
    )

    if hackathon_impact.empty:
        st.info("No hackathon events found in the current dataset.")
    else:
        hackathon_chart = hackathon_impact.copy()
        hackathon_chart["event_label"] = hackathon_chart.apply(
            lambda row: format_event_label(row["event_type"], row["event_date"]),
            axis=1,
        )
        fig_hours = px.bar(
            hackathon_chart,
            x="event_label",
            y="hackathon_hours",
            color="hackathon_hours",
            color_continuous_scale=BRAND_ORANGE_SCALE,
            title="Hackathon Volunteer Hours by Event",
            labels={
                "event_label": "Hackathon event",
                "hackathon_hours": "Volunteer hours",
            },
            text="hackathon_hours",
        )
        fig_hours.update_traces(textposition="outside")
        st.plotly_chart(build_chart_theme(hide_colorbar_legend(fig_hours)), use_container_width=True)

    st.divider()
    st.header("Section 5: Volunteer Composition")
    st.write("Profile volunteer skills and backgrounds to support staffing and outreach decisions.")

    bg1, bg2 = st.columns(2)

    domain_df = background["domain"]
    if domain_df.empty:
        bg1.info("No domain data found.")
    else:
        fig_domain = px.bar(
            domain_df,
            x="category",
            y="count",
            color="count",
            color_continuous_scale=BRAND_BLUE_SCALE,
            title="Volunteer Skill Areas (Domain Expertise)",
            labels={"category": "Domain", "count": "Volunteers"},
        )
        fig_domain.update_xaxes(tickangle=-30)
        bg1.plotly_chart(build_chart_theme(hide_colorbar_legend(fig_domain)), use_container_width=True)

    years_df = background["years"]
    if years_df.empty:
        bg2.info("No years-of-experience data found.")
    else:
        fig_years = px.bar(
            years_df,
            x="category",
            y="count",
            color="count",
            color_continuous_scale=BRAND_BLUE_SCALE,
            title="Professional Experience Distribution",
            labels={"category": "Years of Experience", "count": "Volunteers"},
        )
        bg2.plotly_chart(build_chart_theme(hide_colorbar_legend(fig_years)), use_container_width=True)

    bg3, bg4 = st.columns(2)

    employer_df = background["employer"]
    if employer_df.empty:
        bg3.info("No employer data found.")
    else:
        fig_employer = px.bar(
            employer_df.sort_values("count", ascending=True),
            x="count",
            y="category",
            orientation="h",
            color="count",
            color_continuous_scale=BRAND_BLUE_SCALE,
            title="Top Employers Represented",
            labels={"category": "Employer", "count": "Volunteers"},
        )
        bg3.plotly_chart(build_chart_theme(hide_colorbar_legend(fig_employer)), use_container_width=True)
        bg3.caption(
            f"Employer field missing/unknown in {format_percent(data_quality['missing_employer_pct'])} of volunteer records."
        )

    role_df = background["current_role"]
    if role_df.empty:
        bg4.info("No current role data found.")
    else:
        fig_roles = px.bar(
            role_df.sort_values("count", ascending=True),
            x="count",
            y="category",
            orientation="h",
            color="count",
            color_continuous_scale=BRAND_BLUE_SCALE,
            title="Current Role Distribution (Standardized)",
            labels={"category": "Current Role", "count": "Volunteers"},
        )
        bg4.plotly_chart(build_chart_theme(hide_colorbar_legend(fig_roles)), use_container_width=True)

    nonprofit_df = background["nonprofit_interest"]
    if nonprofit_df.empty:
        st.info("No nonprofit-interest data found.")
    else:
        fig_interest = px.bar(
            nonprofit_df,
            x="category",
            y="count",
            color="count",
            color_continuous_scale=BRAND_BLUE_SCALE,
            title="Top Nonprofit Interest Areas",
            labels={"category": "Nonprofit interest area", "count": "Volunteers"},
        )
        fig_interest.update_xaxes(tickangle=-30)
        st.plotly_chart(build_chart_theme(hide_colorbar_legend(fig_interest)), use_container_width=True)


if __name__ == "__main__":
    render_dashboard()
