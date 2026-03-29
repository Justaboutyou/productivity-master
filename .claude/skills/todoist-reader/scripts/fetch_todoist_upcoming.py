"""
Step 1c: Todoist 향후 14일 태스크 수집

오늘 이후 ~ +14일 이내 due date인 미완료 태스크를 수집한다.
generate_advice()에서 7일 이내 항목만 {upcoming_deadlines}에 사용된다.

Exit codes:
  0 - 성공 (빈 배열도 성공)
  1 - 오류 (API 실패, 인증 실패)
"""

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

TODOIST_API_KEY = os.environ.get("TODOIST_API_KEY")
OUTPUT_PATH = Path(__file__).parents[4] / "output" / "todoist_upcoming.json"

JST = timezone(timedelta(hours=9))
FETCH_DAYS = 14

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


def fetch_upcoming_tasks() -> list:
    today = datetime.now(JST).date()
    cutoff = today + timedelta(days=FETCH_DAYS)
    today_str = today.isoformat()
    cutoff_str = cutoff.isoformat()

    headers = {"Authorization": f"Bearer {TODOIST_API_KEY}"}
    project_map = fetch_projects(headers)

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
        if task.get("checked"):
            continue

        due = task.get("due") or {}
        due_str = due.get("date", "")
        if not due_str:
            continue

        due_date = due_str[:10]

        # 오늘 초과 ~ +14일 이내만 포함
        if due_date <= today_str or due_date > cutoff_str:
            continue

        due_time = due_str[11:16] if "T" in due_str else ""

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

    result.sort(key=lambda t: (t["due_date"], t["priority"]))
    return result


def main():
    if not TODOIST_API_KEY:
        print("Missing TODOIST_API_KEY", file=sys.stderr)
        sys.exit(1)

    try:
        tasks = fetch_upcoming_tasks()
    except requests.RequestException as e:
        print(f"Todoist API error: {e}", file=sys.stderr)
        sys.exit(1)

    today = datetime.now(JST).date().isoformat()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps({"date": today, "tasks": tasks}, ensure_ascii=False, indent=2))
    print(f"Fetched {len(tasks)} upcoming tasks (next {FETCH_DAYS} days)")
    sys.exit(0)


if __name__ == "__main__":
    main()
