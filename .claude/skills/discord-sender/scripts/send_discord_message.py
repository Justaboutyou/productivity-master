"""
Step 6: output/briefing_draft.md를 읽어 Discord Webhook으로 발송한다.

Exit codes:
  0 - 발송 성공
  1 - 발송 실패 (2회 재시도 후)
"""

import argparse
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
DEFAULT_BRIEFING_PATH = Path(__file__).parents[4] / "output" / "briefing_draft.md"

MAX_RETRIES = 2


def send_message(text: str) -> bool:
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = requests.post(
                DISCORD_WEBHOOK_URL,
                json={"content": text},
                timeout=10,
            )
            if response.status_code in (200, 204):
                return True
            print(
                f"Discord returned {response.status_code} (attempt {attempt + 1}): {response.text}",
                file=sys.stderr,
            )
        except requests.RequestException as e:
            print(f"Request error (attempt {attempt + 1}): {e}", file=sys.stderr)

        if attempt < MAX_RETRIES:
            time.sleep(1)

    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=Path, default=DEFAULT_BRIEFING_PATH,
                        help="발송할 메시지 파일 경로 (기본: output/briefing_draft.md)")
    args = parser.parse_args()

    if not DISCORD_WEBHOOK_URL:
        print("Missing DISCORD_WEBHOOK_URL", file=sys.stderr)
        sys.exit(1)

    if not args.file.exists():
        print(f"Briefing file not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    message = args.file.read_text().strip()
    success = send_message(message)

    if not success:
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
