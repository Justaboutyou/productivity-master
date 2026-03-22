"""
Step 5: Notion Morning 섹션 채우기

Notion REST API를 직접 호출 (notion-client v3 호환성 문제 우회).
Night 섹션은 절대 건드리지 않음.

Exit codes:
  0 - 성공
  1 - 오류
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID")
BRIEFING_PATH = Path(__file__).parents[4] / "output" / "briefing_draft.md"

NOTION_VERSION = "2022-06-28"
# 기존 페이지 타이틀 포맷: MM/DD(曜日) — 일본식 요일
WEEKDAYS_JA = ["月", "火", "水", "木", "金", "土", "日"]


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
# 브리핑 파싱
# ---------------------------------------------------------------------------

def parse_briefing(text: str) -> tuple[list[str], list[str]]:
    top3, brain_dump = [], []
    section = None
    for line in text.split("\n"):
        line = line.strip()
        if "⭐ 오늘의 Top 3" in line:
            section = "top3"
        elif "📋 기타" in line:
            section = "brain_dump"
        elif "💬" in line or "🌅" in line:
            section = None
        elif line.startswith("•") and section == "top3":
            top3.append(line[1:].strip())
        elif line.startswith("•") and section == "brain_dump":
            brain_dump.append(line[1:].strip())
    return top3, brain_dump


# ---------------------------------------------------------------------------
# 블록 빌더
# ---------------------------------------------------------------------------

def para(text: str) -> dict:
    return {"object": "block", "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": text}}]}}


def heading2(text: str) -> dict:
    return {"object": "block", "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": text}}]}}


def heading3(text: str) -> dict:
    return {"object": "block", "type": "heading_3",
            "heading_3": {"rich_text": [{"type": "text", "text": {"content": text}}]}}


def divider() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def morning_content_blocks(top3: list[str], brain_dump: list[str]) -> list[dict]:
    blocks = [heading3("1️⃣ Top Priorities 3")]
    blocks += [para(item) for item in top3] if top3 else [para("(없음)")]
    blocks += [heading3("2️⃣ Brain Dump")]
    blocks += [para(item) for item in brain_dump] if brain_dump else [para("(없음)")]
    return blocks


# ---------------------------------------------------------------------------
# 페이지 조회 / 생성
# ---------------------------------------------------------------------------

def today_title() -> str:
    dt = date.today()
    return f"{dt.month:02d}/{dt.day:02d}({WEEKDAYS_JA[dt.weekday()]})"


def find_today_page() -> Optional[str]:
    data = notion_post(
        f"databases/{NOTION_DATABASE_ID}/query",
        {"filter": {"property": "Day", "title": {"equals": today_title()}}, "page_size": 1},
    )
    results = data.get("results", [])
    return results[0]["id"] if results else None


def create_today_page(top3: list[str], brain_dump: list[str]) -> str:
    children = (
        [heading2("☀️ Morning: 오늘 하루를 어떻게 보낼까요?")]
        + morning_content_blocks(top3, brain_dump)
        + [
            heading2("🌙 Night: 성찰과 감사 (오늘 하루는 어땠나요?)"),
            para("• 오늘 내가 잘한 것 1가지는?"),
            para("• 오늘 무엇을 더 잘할 수 있었을까? (Better Me)"),
        ]
    )
    data = notion_post(
        "pages",
        {
            "parent": {"database_id": NOTION_DATABASE_ID},
            "properties": {"Day": {"title": [{"text": {"content": today_title()}}]}},
            "children": children,
        },
    )
    return data["id"]


# ---------------------------------------------------------------------------
# Morning 섹션 채우기
# ---------------------------------------------------------------------------

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


def write_morning_section(page_id: str, top3: list[str], brain_dump: list[str]) -> str:
    blocks = get_page_blocks(page_id)

    morning_heading_id = None
    morning_content_ids = []
    in_morning = False

    for block in blocks:
        text = get_plain_text(block)
        btype = block.get("type", "")
        if btype == "heading_2" and "Morning" in text:
            morning_heading_id = block["id"]
            in_morning = True
            continue
        if in_morning:
            if btype == "heading_2" and "Night" in text:
                break
            morning_content_ids.append(block["id"])

    new_blocks = morning_content_blocks(top3, brain_dump)

    if morning_content_ids:
        # 내용 있음 → 구분선 + LLM 제안으로 append
        body = {"children": [divider(), heading3("🤖 LLM 제안")] + new_blocks,
                "after": morning_content_ids[-1]}
        notion_patch(f"blocks/{page_id}/children", body)
        return "appended"
    elif morning_heading_id:
        # 헤딩은 있지만 내용 비어있음
        notion_patch(f"blocks/{page_id}/children", {"children": new_blocks, "after": morning_heading_id})
        return "success"
    else:
        # Morning 헤딩 자체 없음 → 페이지 맨 앞에 추가
        notion_patch(f"blocks/{page_id}/children",
                     {"children": [heading2("☀️ Morning: 오늘 하루를 어떻게 보낼까요?")] + new_blocks})
        return "success"


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def main():
    if not NOTION_TOKEN or not NOTION_DATABASE_ID:
        print("Missing NOTION_TOKEN or NOTION_DATABASE_ID", file=sys.stderr)
        sys.exit(1)
    if not BRIEFING_PATH.exists():
        print(f"Briefing not found: {BRIEFING_PATH}", file=sys.stderr)
        sys.exit(1)

    top3, brain_dump = parse_briefing(BRIEFING_PATH.read_text())

    try:
        page_id = find_today_page()
        if page_id is None:
            create_today_page(top3, brain_dump)
            print(f"Created new Notion page: {today_title()}")
        else:
            result = write_morning_section(page_id, top3, brain_dump)
            print(f"Updated Notion page Morning section ({result}): {today_title()}")
    except Exception as e:
        print(f"Notion API error: {e}", file=sys.stderr)
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
