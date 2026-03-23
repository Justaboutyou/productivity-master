"""
Step N2: 오늘 완료된 Todoist 태스크 추출

아침에 수집한 todoist_raw.json(계획)과 현재 active 태스크를 비교해
완료된 항목을 역산한다. 별도 completed API 불필요.

Exit codes:
  0 - 성공 (빈 배열도 성공)
  1 - 오류
  2 - 아침 데이터 없음 또는 id 필드 없음 (skip)
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

TODOIST_API_KEY = os.environ.get("TODOIST_API_KEY")
MORNING_PATH = Path(__file__).parents[4] / "output" / "todoist_raw.json"
OUTPUT_PATH = Path(__file__).parents[4] / "output" / "todoist_completed.json"

JST = timezone(timedelta(hours=9))


def fetch_active_task_ids(headers: dict) -> set:
    """현재 active(미완료) 태스크 ID 집합 반환."""
    active_ids = set()
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
        for task in data.get("results", []):
            if not task.get("checked"):
                active_ids.add(task["id"])
        cursor = data.get("next_cursor")
        if not cursor:
            break
    return active_ids


def main():
    if not TODOIST_API_KEY:
        print("Missing TODOIST_API_KEY", file=sys.stderr)
        sys.exit(1)

    if not MORNING_PATH.exists():
        print("아침 todoist_raw.json 없음 (skip)", file=sys.stderr)
        sys.exit(2)

    morning_data = json.loads(MORNING_PATH.read_text())
    morning_tasks = morning_data.get("tasks", [])

    tasks_with_id = [t for t in morning_tasks if t.get("id")]
    if not tasks_with_id:
        print("아침 태스크에 id 필드 없음 (skip)", file=sys.stderr)
        sys.exit(2)

    headers = {"Authorization": f"Bearer {TODOIST_API_KEY}"}
    try:
        active_ids = fetch_active_task_ids(headers)
    except requests.RequestException as e:
        print(f"Todoist API error: {e}", file=sys.stderr)
        sys.exit(1)

    # 아침 계획 중 현재 active에 없는 것 = 완료된 것
    completed = [t for t in tasks_with_id if t["id"] not in active_ids]

    today = datetime.now(JST).date().isoformat()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps({"date": today, "tasks": completed}, ensure_ascii=False, indent=2)
    )
    print(f"Completed {len(completed)}/{len(tasks_with_id)} tasks today")
    sys.exit(0)


if __name__ == "__main__":
    main()
