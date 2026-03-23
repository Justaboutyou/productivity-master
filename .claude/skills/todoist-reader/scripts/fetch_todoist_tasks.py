"""
Step 1a: Todoist 오늘 태스크 수집

Exit codes:
  0 - 성공 (빈 배열도 성공)
  1 - 오류 (API 실패, 인증 실패)
"""

import json
import os
import sys
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

TODOIST_API_KEY = os.environ.get("TODOIST_API_KEY")
OUTPUT_PATH = Path(__file__).parents[4] / "output" / "todoist_raw.json"

JST = timezone(timedelta(hours=9))

# Todoist API priority: 4=p1(urgent), 3=p2, 2=p3, 1=p4(normal)
PRIORITY_MAP = {4: 1, 3: 2, 2: 3, 1: 4}


def fetch_projects(headers: dict) -> dict:
    resp = requests.get("https://api.todoist.com/api/v1/projects", headers=headers, timeout=10)
    resp.raise_for_status()
    return {p["id"]: p for p in resp.json().get("results", [])}


def get_root_project_name(project_id: str, project_map: dict) -> str:
    visited = set()
    while project_id and project_id not in visited:
        visited.add(project_id)
        proj = project_map.get(project_id, {})
        parent_id = proj.get("parent_id")
        if not parent_id:
            return proj.get("name", "")
        project_id = parent_id
    return ""


def fetch_todoist_tasks() -> list:
    today = datetime.now(JST).date().isoformat()
    headers = {"Authorization": f"Bearer {TODOIST_API_KEY}"}

    project_map = fetch_projects(headers)

    # 새 API v1: pagination은 next_cursor로 처리
    all_tasks = []
    cursor = None

    while True:
        params = {"limit": 200}
        if cursor:
            params["cursor"] = cursor

        resp = requests.get(
            "https://api.todoist.com/api/v1/tasks",
            headers=headers,
            params=params,
            timeout=10,
        )
        resp.raise_for_status()

        data = resp.json()
        all_tasks.extend(data.get("results", []))

        cursor = data.get("next_cursor")
        if not cursor:
            break

    result = []
    for task in all_tasks:
        # 완료된 태스크 제외
        if task.get("checked"):
            continue

        due = task.get("due") or {}
        due_str = due.get("date", "")

        if not due_str:
            continue

        # due_str 예: "2026-03-22" 또는 "2026-03-22T20:00:00"
        due_date = due_str[:10]

        # 오늘 이전 또는 오늘인 태스크만 포함 (overdue 포함)
        if due_date > today:
            continue

        due_time = ""
        if "T" in due_str:
            # due.timezone이 None이면 사용자 로컬 시간으로 간주
            due_time = due_str[11:16]  # HH:MM

        raw_priority = task.get("priority", 1)
        priority = PRIORITY_MAP.get(raw_priority, raw_priority)

        project_id = task.get("project_id", "")
        project_name = project_map.get(project_id, {}).get("name", "") if project_id else ""
        root_project_name = get_root_project_name(project_id, project_map) if project_id else ""

        result.append({
            "id": task.get("id", ""),
            "text": task.get("content", ""),
            "priority": priority,
            "due_date": due_date,
            "due_time": due_time,
            "project_name": project_name,
            "root_project_name": root_project_name,
        })

    return result


def main():
    if not TODOIST_API_KEY:
        print("Missing TODOIST_API_KEY", file=sys.stderr)
        sys.exit(1)

    try:
        tasks = fetch_todoist_tasks()
    except requests.RequestException as e:
        print(f"Todoist API error: {e}", file=sys.stderr)
        sys.exit(1)

    today = datetime.now(JST).date().isoformat()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps({"date": today, "tasks": tasks}, ensure_ascii=False, indent=2))
    print(f"Fetched {len(tasks)} tasks")
    sys.exit(0)


if __name__ == "__main__":
    main()
