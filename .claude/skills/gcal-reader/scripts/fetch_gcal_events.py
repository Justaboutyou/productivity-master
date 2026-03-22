"""
Step 1b: Google Calendar 오늘 일정 수집

인증 방식: OAuth2 (GCAL_CLIENT_ID + GCAL_CLIENT_SECRET + GCAL_TOKEN_JSON)
- GCAL_TOKEN_JSON: token.json의 base64 인코딩 값 (gcal_auth.py로 생성)

Exit codes:
  0 - 성공 (빈 배열도 성공)
  1 - 오류 (인증 실패, API 실패)
"""

import base64
import json
import os
import sys
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

load_dotenv()

GCAL_CLIENT_ID = os.environ.get("GCAL_CLIENT_ID")
GCAL_CLIENT_SECRET = os.environ.get("GCAL_CLIENT_SECRET")
GCAL_TOKEN_JSON = os.environ.get("GCAL_TOKEN_JSON")
OUTPUT_PATH = Path(__file__).parents[4] / "output" / "gcal_raw.json"

JST = timezone(timedelta(hours=9))
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


def load_credentials() -> Credentials:
    token_json = base64.b64decode(GCAL_TOKEN_JSON).decode("utf-8")
    token_data = json.loads(token_json)

    creds = Credentials(
        token=token_data.get("token"),
        refresh_token=token_data.get("refresh_token"),
        token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=GCAL_CLIENT_ID,
        client_secret=GCAL_CLIENT_SECRET,
        scopes=SCOPES,
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

    return creds


def fetch_gcal_events() -> list:
    creds = load_credentials()
    service = build("calendar", "v3", credentials=creds)

    today = date.today()
    time_min = datetime(today.year, today.month, today.day, 0, 0, 0, tzinfo=JST).isoformat()
    time_max = datetime(today.year, today.month, today.day, 23, 59, 59, tzinfo=JST).isoformat()

    events_result = service.events().list(
        calendarId="primary",
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    result = []
    for event in events_result.get("items", []):
        start = event.get("start", {})
        end = event.get("end", {})

        start_str = start.get("dateTime", start.get("date", ""))
        end_str = end.get("dateTime", end.get("date", ""))

        if "T" in start_str:
            start_time = datetime.fromisoformat(start_str).astimezone(JST).strftime("%H:%M")
        else:
            start_time = "00:00"  # 종일 이벤트

        if "T" in end_str:
            end_time = datetime.fromisoformat(end_str).astimezone(JST).strftime("%H:%M")
        else:
            end_time = "23:59"  # 종일 이벤트

        result.append({
            "title": event.get("summary", ""),
            "start": start_time,
            "end": end_time,
            "colorId": event.get("colorId", ""),
        })

    return result


def main():
    if not GCAL_CLIENT_ID or not GCAL_CLIENT_SECRET or not GCAL_TOKEN_JSON:
        missing = [k for k, v in {
            "GCAL_CLIENT_ID": GCAL_CLIENT_ID,
            "GCAL_CLIENT_SECRET": GCAL_CLIENT_SECRET,
            "GCAL_TOKEN_JSON": GCAL_TOKEN_JSON,
        }.items() if not v]
        print(f"Missing env vars: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    try:
        events = fetch_gcal_events()
    except Exception as e:
        print(f"GCal API error: {e}", file=sys.stderr)
        sys.exit(1)

    today = date.today().isoformat()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps({"date": today, "events": events}, ensure_ascii=False, indent=2))
    print(f"Fetched {len(events)} events")
    sys.exit(0)


if __name__ == "__main__":
    main()
