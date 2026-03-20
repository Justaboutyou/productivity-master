"""
Step 2: Notion 페이지에서 할일 블록을 추출하여 output/todo_raw.json에 저장한다.

Usage: python extract_todo_blocks.py <page_id> <date>

실제 페이지 구조:
  column_list > column > heading_3 "1️⃣ Top 3 ..." → to_do 블록들
  column_list > column > heading_3 "2️⃣ Brain Dump ..." → to_do 블록들

Exit codes:
  0 - 성공 (todos가 비어있어도 정상)
  1 - API 오류
"""

from __future__ import annotations

import os
import sys
import json
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
NOTION_API_VERSION = "2022-06-28"

# 헤딩 텍스트의 부분 문자열로 섹션 판별 (대소문자 무시)
HEADING_KEYWORDS = {
    "top 3": "top_priorities",
    "brain dump": "brain_dump",
}

OUTPUT_PATH = Path(__file__).parents[4] / "output" / "todo_raw.json"


def get_block_text(block: dict) -> str:
    block_type = block.get("type", "")
    rich_text = block.get(block_type, {}).get("rich_text", [])
    return "".join(rt.get("plain_text", "") for rt in rich_text)


def detect_section(text: str) -> Optional[str]:
    """헤딩 텍스트에서 섹션 레이블을 반환한다. 매칭 없으면 None."""
    lower = text.lower()
    for keyword, section in HEADING_KEYWORDS.items():
        if keyword in lower:
            return section
    return None


def fetch_children(block_id: str) -> Optional[list]:
    url = f"https://api.notion.com/v1/blocks/{block_id}/children"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_API_VERSION,
    }
    all_blocks = []
    cursor = None

    while True:
        params = {}
        if cursor:
            params["start_cursor"] = cursor

        response = requests.get(url, headers=headers, params=params, timeout=10)
        if response.status_code != 200:
            print(f"Notion API error {response.status_code}: {response.text}", file=sys.stderr)
            return None

        data = response.json()
        all_blocks.extend(data.get("results", []))

        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    return all_blocks


def collect_todos(block_id: str) -> Optional[list]:
    """블록 트리를 재귀 탐색하여 할일 블록을 수집한다."""
    blocks = fetch_children(block_id)
    if blocks is None:
        return None

    todos = []
    current_section = None

    for block in blocks:
        block_type = block.get("type", "")

        # 컨테이너 블록은 재귀 탐색 (섹션 컨텍스트 유지 안 함)
        if block_type in ("column_list", "column"):
            if block.get("has_children"):
                sub = collect_todos(block["id"])
                if sub is None:
                    return None
                todos.extend(sub)
            continue

        # 헤딩: 섹션 전환
        if block_type in ("heading_1", "heading_2", "heading_3"):
            text = get_block_text(block)
            section = detect_section(text)
            if section is not None:
                current_section = section
            else:
                # 관련 없는 헤딩 → 섹션 초기화
                current_section = None
            continue

        # 대상 섹션 내 to_do 수집
        if block_type == "to_do" and current_section is not None:
            text = get_block_text(block)
            if text.strip():  # 빈 placeholder는 제외
                checked = block.get("to_do", {}).get("checked", False)
                todos.append({
                    "text": text,
                    "checked": checked,
                    "section": current_section,
                })

    return todos


def main():
    if len(sys.argv) < 3:
        print("Usage: extract_todo_blocks.py <page_id> <date>", file=sys.stderr)
        sys.exit(1)

    if not NOTION_TOKEN:
        print("Missing NOTION_TOKEN", file=sys.stderr)
        sys.exit(1)

    page_id = sys.argv[1]
    target_date = sys.argv[2]

    todos = collect_todos(page_id)
    if todos is None:
        sys.exit(1)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "date": target_date,
        "page_id": page_id,
        "todos": todos,
    }
    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2))

    print(f"Extracted {len(todos)} todos to {OUTPUT_PATH}")
    sys.exit(0)


if __name__ == "__main__":
    main()
