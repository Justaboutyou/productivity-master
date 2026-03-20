"""
Step 1: 어제 날짜의 Notion 일지 페이지를 조회하고 page_id를 stdout으로 출력한다.

Exit codes:
  0 - 페이지 발견, page_id를 stdout에 출력
  1 - API 오류
  2 - 페이지 없음 (스킵 신호)
"""

from __future__ import annotations

import os
import sys
import json
from datetime import date, timedelta
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID")
NOTION_API_VERSION = "2022-06-28"


def get_yesterday_formats() -> list:
    yesterday = date.today() - timedelta(days=1)
    mm_dd = yesterday.strftime("%m/%d")          # 실제 형식: "03/19(木)"
    yyyy_mm_dd = yesterday.strftime("%Y-%m-%d")  # fallback
    yyyy_slash = yesterday.strftime("%Y/%m/%d")  # fallback
    return [mm_dd, yyyy_mm_dd, yyyy_slash]


def query_database(title_contains: str) -> Optional[dict]:
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_API_VERSION,
        "Content-Type": "application/json",
    }
    payload = {
        "filter": {
            "property": "title",
            "title": {"contains": title_contains},
        }
    }
    response = requests.post(url, headers=headers, json=payload, timeout=10)
    if response.status_code != 200:
        print(f"Notion API error {response.status_code}: {response.text}", file=sys.stderr)
        return None
    return response.json()


def main():
    if not NOTION_TOKEN or not NOTION_DATABASE_ID:
        print("Missing NOTION_TOKEN or NOTION_DATABASE_ID", file=sys.stderr)
        sys.exit(1)

    date_formats = get_yesterday_formats()

    for fmt in date_formats:
        result = query_database(fmt)
        if result is None:
            sys.exit(1)

        pages = result.get("results", [])
        if pages:
            page_id = pages[0]["id"]
            print(page_id)
            sys.exit(0)

    # 모든 날짜 포맷으로 검색해도 페이지 없음
    sys.exit(2)


if __name__ == "__main__":
    main()
