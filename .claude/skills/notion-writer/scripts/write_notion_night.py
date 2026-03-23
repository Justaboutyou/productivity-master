"""
Step N5: Notion에 AI 저녁 제언 섹션 추가

🌙 Night 헤딩 직전에 "🤖 AI 저녁 제언" 섹션을 삽입.
Night 섹션 내용(사용자 작성 감사/성찰)은 절대 건드리지 않음.
재실행 시에는 구분선 + "🤖 AI 저녁 제언 (재생성)" 으로 append.

Exit codes:
  0 - 성공
  1 - 오류 (페이지 없음 포함)
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID")
NIGHT_DRAFT_PATH = Path(__file__).parents[4] / "output" / "night_draft.md"

NOTION_VERSION = "2022-06-28"
WEEKDAYS_JA = ["月", "火", "水", "木", "金", "土", "日"]
JST = timezone(timedelta(hours=9))


# ---------------------------------------------------------------------------
# Notion API 헬퍼
# ---------------------------------------------------------------------------

def notion_headers() -> dict:
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def notion_get(path: str) -> dict:
    resp = requests.get(f"https://api.notion.com/v1/{path}", headers=notion_headers(), timeout=10)
    resp.raise_for_status()
    return resp.json()


def notion_post(path: str, body: dict) -> dict:
    resp = requests.post(f"https://api.notion.com/v1/{path}", headers=notion_headers(), json=body, timeout=10)
    resp.raise_for_status()
    return resp.json()


def notion_patch(path: str, body: dict) -> dict:
    resp = requests.patch(f"https://api.notion.com/v1/{path}", headers=notion_headers(), json=body, timeout=10)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# 블록 빌더
# ---------------------------------------------------------------------------

def para(text: str) -> dict:
    return {"object": "block", "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": text}}]}}


def heading3(text: str) -> dict:
    return {"object": "block", "type": "heading_3",
            "heading_3": {"rich_text": [{"type": "text", "text": {"content": text}}]}}


def divider() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def text_to_blocks(text: str) -> list[dict]:
    return [para(line) if line.strip() else para(" ") for line in text.split("\n")]


# ---------------------------------------------------------------------------
# 페이지 조회
# ---------------------------------------------------------------------------

def today_title() -> str:
    dt = datetime.now(JST).date()
    return f"{dt.month:02d}/{dt.day:02d}({WEEKDAYS_JA[dt.weekday()]})"


def find_today_page() -> Optional[str]:
    data = notion_post(
        f"databases/{NOTION_DATABASE_ID}/query",
        {"filter": {"property": "Day", "title": {"equals": today_title()}}, "page_size": 1},
    )
    results = data.get("results", [])
    return results[0]["id"] if results else None


def get_page_blocks(page_id: str) -> list:
    blocks = []
    url = f"blocks/{page_id}/children?page_size=100"
    while True:
        data = notion_get(url)
        blocks.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        url = f"blocks/{page_id}/children?page_size=100&start_cursor={data['next_cursor']}"
    return blocks


def get_plain_text(block: dict) -> str:
    btype = block.get("type", "")
    return "".join(rt.get("plain_text", "") for rt in block.get(btype, {}).get("rich_text", []))


# ---------------------------------------------------------------------------
# AI 저녁 제언 섹션 삽입
# ---------------------------------------------------------------------------

def write_night_ai_section(page_id: str, night_text: str) -> str:
    """🌙 Night 헤딩 직전에 AI 저녁 제언 삽입. 기존 섹션 있으면 그 뒤에 append."""
    blocks = get_page_blocks(page_id)

    night_heading_id: Optional[str] = None
    ai_section_last_id: Optional[str] = None
    in_ai_section = False
    last_block_before_night_id: Optional[str] = None

    for block in blocks:
        text = get_plain_text(block)
        btype = block.get("type", "")

        if btype == "heading_2" and "Night" in text:
            night_heading_id = block["id"]
            break

        if btype == "heading_3" and "AI 저녁 제언" in text:
            in_ai_section = True
            ai_section_last_id = block["id"]
            last_block_before_night_id = block["id"]
            continue

        last_block_before_night_id = block["id"]
        if in_ai_section:
            ai_section_last_id = block["id"]

    new_blocks = [divider(), heading3("🤖 AI 저녁 제언")] + text_to_blocks(night_text)

    if ai_section_last_id:
        # 기존 AI 제언 섹션 있음 → 재생성으로 append
        notion_patch(
            f"blocks/{page_id}/children",
            {
                "children": [divider(), heading3("🤖 AI 저녁 제언 (재생성)")] + text_to_blocks(night_text),
                "after": ai_section_last_id,
            },
        )
        return "appended"
    elif last_block_before_night_id:
        # Night 헤딩 전 마지막 블록 뒤에 삽입 → Night 헤딩 앞에 자연스럽게 위치
        notion_patch(
            f"blocks/{page_id}/children",
            {"children": new_blocks, "after": last_block_before_night_id},
        )
        return "success"
    else:
        # Morning 내용 없는 경우 → 페이지 끝에 append
        notion_patch(f"blocks/{page_id}/children", {"children": new_blocks})
        return "success"


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def main():
    if not NOTION_TOKEN or not NOTION_DATABASE_ID:
        print("Missing NOTION_TOKEN or NOTION_DATABASE_ID", file=sys.stderr)
        sys.exit(1)
    if not NIGHT_DRAFT_PATH.exists():
        print(f"Night draft not found: {NIGHT_DRAFT_PATH}", file=sys.stderr)
        sys.exit(1)

    night_text = NIGHT_DRAFT_PATH.read_text()

    try:
        page_id = find_today_page()
        if page_id is None:
            print(f"오늘 Notion 페이지 없음: {today_title()} (skip)", file=sys.stderr)
            sys.exit(1)
        result = write_night_ai_section(page_id, night_text)
        print(f"Updated Notion Night AI section ({result}): {today_title()}")
    except Exception as e:
        print(f"Notion API error: {e}", file=sys.stderr)
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
