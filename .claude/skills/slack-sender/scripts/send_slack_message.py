"""
Step 5: output/briefing_draft.md를 읽어 Slack Webhook으로 발송한다.

Exit codes:
  0 - 발송 성공
  1 - 발송 실패 (2회 재시도 후)
"""

import os
import sys
import json
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta

import requests
from dotenv import load_dotenv

load_dotenv()

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")
BRIEFING_PATH = Path(__file__).parents[4] / "output" / "briefing_draft.md"
RUN_LOG_PATH = Path(__file__).parents[4] / "output" / "run_log.json"

MAX_RETRIES = 2


def append_run_log(entry: dict):
    RUN_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logs = []
    if RUN_LOG_PATH.exists():
        try:
            logs = json.loads(RUN_LOG_PATH.read_text())
            if not isinstance(logs, list):
                logs = [logs]
        except json.JSONDecodeError:
            logs = []
    logs.append(entry)
    RUN_LOG_PATH.write_text(json.dumps(logs, ensure_ascii=False, indent=2))


def send_message(text: str) -> bool:
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = requests.post(
                SLACK_WEBHOOK_URL,
                json={"text": text},
                timeout=10,
            )
            if response.status_code == 200:
                return True
            print(
                f"Slack returned {response.status_code} (attempt {attempt + 1}): {response.text}",
                file=sys.stderr,
            )
        except requests.RequestException as e:
            print(f"Request error (attempt {attempt + 1}): {e}", file=sys.stderr)

        if attempt < MAX_RETRIES:
            time.sleep(1)

    return False


def main():
    if not SLACK_WEBHOOK_URL:
        print("Missing SLACK_WEBHOOK_URL", file=sys.stderr)
        sys.exit(1)

    if not BRIEFING_PATH.exists():
        print(f"Briefing file not found: {BRIEFING_PATH}", file=sys.stderr)
        sys.exit(1)

    message = BRIEFING_PATH.read_text().strip()

    success = send_message(message)

    if not success:
        kst = timezone(timedelta(hours=9))
        append_run_log({
            "timestamp": datetime.now(kst).isoformat(),
            "status": "failed",
            "reason": "slack_error",
        })
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
