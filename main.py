"""
Todoist + GCal → Notion Morning + Discord 모닝 브리핑 에이전트 오케스트레이터

실행 순서:
  Step 1a — Todoist 오늘 태스크 수집    (fetch_todoist_tasks.py)
  Step 1b — GCal 오늘 일정 수집         (fetch_gcal_events.py)
  Step 2  — 2소스 병합                  (merged_context.json)
  Step 3  — 규칙 기반 브리핑 포맷 생성
  Step 4  — LLM 한 줄 코멘트 생성      (Gemini)
  Step 5  — Notion Morning 섹션 채우기  (write_notion_morning.py)
  Step 6  — Discord 발송                (send_discord_message.py)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from google import genai

load_dotenv()

# --- 경로 설정 ---
BASE_DIR = Path(__file__).parent
SCRIPTS = {
    "todoist": BASE_DIR / ".claude/skills/todoist-reader/scripts/fetch_todoist_tasks.py",
    "gcal": BASE_DIR / ".claude/skills/gcal-reader/scripts/fetch_gcal_events.py",
    "notion_write": BASE_DIR / ".claude/skills/notion-writer/scripts/write_notion_morning.py",
    "discord": BASE_DIR / ".claude/skills/discord-sender/scripts/send_discord_message.py",
}
TODOIST_RAW_PATH = BASE_DIR / "output" / "todoist_raw.json"
GCAL_RAW_PATH = BASE_DIR / "output" / "gcal_raw.json"
MERGED_PATH = BASE_DIR / "output" / "merged_context.json"
BRIEFING_PATH = BASE_DIR / "output" / "briefing_draft.md"
RUN_LOG_PATH = BASE_DIR / "output" / "run_log.json"

KST = timezone(timedelta(hours=9))
GEMINI_MODEL = "gemini-2.5-flash"

PERSONAL_KEYWORDS = ["심리상담", "병원", "운동", "자세교정", "가족", "약속"]
WORK_KEYWORDS = ["미팅", "스탠드업", "리뷰", "발표", "보고"]


# ---------------------------------------------------------------------------
# 로그
# ---------------------------------------------------------------------------

def append_run_log(entry: dict):
    RUN_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logs = []
    if RUN_LOG_PATH.exists():
        try:
            data = json.loads(RUN_LOG_PATH.read_text())
            logs = data if isinstance(data, list) else [data]
        except json.JSONDecodeError:
            pass
    logs.append(entry)
    RUN_LOG_PATH.write_text(json.dumps(logs, ensure_ascii=False, indent=2))


def make_log_entry(status: str, reason: str = "", **kwargs) -> dict:
    entry = {
        "timestamp": datetime.now(KST).isoformat(),
        "status": status,
        "reason": reason,
        "llm_model": GEMINI_MODEL,
    }
    entry.update(kwargs)
    return entry


# ---------------------------------------------------------------------------
# Step 1a — Todoist 태스크 수집
# ---------------------------------------------------------------------------

def run_step1a() -> bool:
    print("[Step 1a] Todoist 태스크 수집 중...")
    result = subprocess.run(
        [sys.executable, str(SCRIPTS["todoist"])],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print(f"[Step 1a] {result.stdout.strip()}")
        return True
    print(f"[Step 1a] 실패 (skip): {result.stderr.strip()}", file=sys.stderr)
    return False


# ---------------------------------------------------------------------------
# Step 1b — GCal 일정 수집
# ---------------------------------------------------------------------------

def run_step1b() -> bool:
    print("[Step 1b] GCal 일정 수집 중...")
    result = subprocess.run(
        [sys.executable, str(SCRIPTS["gcal"])],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print(f"[Step 1b] {result.stdout.strip()}")
        return True
    print(f"[Step 1b] 실패 (skip): {result.stderr.strip()}", file=sys.stderr)
    return False


# ---------------------------------------------------------------------------
# Step 2 — 2소스 병합
# ---------------------------------------------------------------------------

def run_step2(today: str) -> dict:
    todoist_data: dict = {}
    gcal_data: dict = {}

    if TODOIST_RAW_PATH.exists():
        try:
            todoist_data = json.loads(TODOIST_RAW_PATH.read_text())
        except json.JSONDecodeError:
            pass

    if GCAL_RAW_PATH.exists():
        try:
            gcal_data = json.loads(GCAL_RAW_PATH.read_text())
        except json.JSONDecodeError:
            pass

    merged = {
        "date": today,
        "todoist": todoist_data.get("tasks", []),
        "gcal_events": gcal_data.get("events", []),
    }
    MERGED_PATH.parent.mkdir(parents=True, exist_ok=True)
    MERGED_PATH.write_text(json.dumps(merged, ensure_ascii=False, indent=2))

    todo_count = len(merged["todoist"])
    event_count = len(merged["gcal_events"])
    print(f"[Step 2] 병합 완료: Todoist {todo_count}개, GCal {event_count}개")
    return merged


# ---------------------------------------------------------------------------
# Step 3 — 규칙 기반 분류 + 포맷 빌더
# ---------------------------------------------------------------------------

def classify_gcal_event(event: dict) -> str:
    if event.get("colorId") == "4":
        return "personal"
    title = event.get("title", "")
    for kw in PERSONAL_KEYWORDS:
        if kw in title:
            return "personal"
    for kw in WORK_KEYWORDS:
        if kw in title:
            return "work"
    start_hour = int(event.get("start", "00:00").split(":")[0])
    return "work" if 9 <= start_hour < 18 else "personal"


def classify_todoist_task(task: dict) -> str:
    root = task.get("root_project_name", "")
    if root == "業務リスト":
        return "work"
    if root == "자기계발":
        return "personal"
    if root == "간단일 리스트":
        return "backlog"
    return "personal"  # 매핑 불명 → 개인 블록 fallback


def build_formatted_briefing(merged: dict, comment: str) -> str:
    dt = date.fromisoformat(merged["date"])
    weekdays_ko = ["월", "화", "수", "목", "금", "토", "일"]
    weekday = weekdays_ko[dt.weekday()]
    date_label = f"{dt.month:02d}/{dt.day:02d} {weekday}요일"
    is_weekday = dt.weekday() < 5

    work_events = sorted(
        [e for e in merged["gcal_events"] if classify_gcal_event(e) == "work"],
        key=lambda e: e["start"],
    )
    personal_events = sorted(
        [e for e in merged["gcal_events"] if classify_gcal_event(e) == "personal"],
        key=lambda e: e["start"],
    )
    work_tasks = [t for t in merged["todoist"] if classify_todoist_task(t) == "work"]
    personal_tasks = [t for t in merged["todoist"] if classify_todoist_task(t) == "personal"]
    backlog_tasks = [t for t in merged["todoist"] if classify_todoist_task(t) == "backlog"]

    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━",
        f"  브리핑 · {date_label}",
        "━━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]

    def render_block(label, events, tasks):
        block = [label]
        for e in events:
            block.append(f"  🗓 {e['start']}  {e['title']}")
        for t in tasks:
            star = "  ★" if t.get("priority") == 1 else ""
            block.append(f"  ⬜ {t['text']}{star}")
        return block

    if is_weekday and (work_events or work_tasks):
        work_start = work_events[0]["start"] if work_events else "09:00"
        work_end = work_events[-1]["end"] if work_events else "18:00"
        lines += render_block(f"💼 업무  ({work_start}~{work_end})", work_events, work_tasks)
        lines.append("")

    if personal_events or personal_tasks:
        personal_start = personal_events[0]["start"] if personal_events else ""
        label = f"🌙 개인  ({personal_start}~)" if personal_start else "🌙 개인"
        lines += render_block(label, personal_events, personal_tasks)
        lines.append("")

    if backlog_tasks:
        texts = " · ".join(t["text"] for t in backlog_tasks)
        lines += ["📦 백로그 → Todoist", f"  {texts}", ""]

    lines += [
        "━━━━━━━━━━━━━━━━━━━━━━━",
        f"  {comment}",
        "━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Step 4 — LLM 한 줄 코멘트 생성
# ---------------------------------------------------------------------------

def generate_comment(client: genai.Client, merged: dict) -> str:
    dt = date.fromisoformat(merged["date"])
    weekdays_ko = ["월", "화", "수", "목", "금", "토", "일"]
    weekday = weekdays_ko[dt.weekday()]
    tasks = [t for t in merged["todoist"] if t.get("root_project_name") != "간단일 리스트"]
    p1_count = sum(1 for t in tasks if t.get("priority") == 1)
    event_times = [e["start"] for e in merged["gcal_events"]]

    prompt = f"""오늘 브리핑 하단에 들어갈 한 줄 코멘트를 작성해줘.

컨텍스트:
- 오늘: {weekday}요일
- GCal 일정: {len(event_times)}개 {event_times}
- p1 태스크: {p1_count}개
- 전체 태스크: {len(tasks)}개

규칙:
- 한 줄, 30자 이내
- 한국어, 친근하고 실용적
- 이모지 1개 포함
- 매번 다른 표현

한 줄 코멘트만 출력해줘."""
    response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
    return response.text.strip()


# ---------------------------------------------------------------------------
# Step 5 — Notion Write
# ---------------------------------------------------------------------------

def run_step5() -> str:
    """'success', 'appended', 'skipped' 중 하나 반환."""
    print("[Step 5] Notion Morning 섹션 채우기 중...")
    result = subprocess.run(
        [sys.executable, str(SCRIPTS["notion_write"])],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        output = result.stdout.strip()
        print(f"[Step 5] {output}")
        return "appended" if "appended" in output else "success"
    print(f"[Step 5] 실패 (skip): {result.stderr.strip()}", file=sys.stderr)
    return "skipped"


# ---------------------------------------------------------------------------
# Step 6 — Discord 발송
# ---------------------------------------------------------------------------

def run_step6() -> bool:
    print("[Step 6] Discord 발송 중...")
    result = subprocess.run(
        [sys.executable, str(SCRIPTS["discord"])],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print("[Step 6] 발송 성공 ✓")
        return True
    print(f"[Step 6] 발송 실패: {result.stderr.strip()}", file=sys.stderr)
    return False


# ---------------------------------------------------------------------------
# 빈 브리핑 생성
# ---------------------------------------------------------------------------

def make_empty_briefing(today: str) -> str:
    dt = date.fromisoformat(today)
    weekdays_ko = ["월", "화", "수", "목", "금", "토", "일"]
    weekday = weekdays_ko[dt.weekday()]
    date_label = f"{dt.month:02d}/{dt.day:02d} {weekday}요일"
    return "\n".join([
        "━━━━━━━━━━━━━━━━━━━━━━━",
        f"  브리핑 · {date_label}",
        "━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "오늘은 등록된 태스크와 일정이 없습니다.",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━",
        "  자유로운 하루! 😌",
        "━━━━━━━━━━━━━━━━━━━━━━━",
    ])


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def main():
    today = date.today().isoformat()
    sources_collected = []
    sources_skipped = []
    notion_write_status = "skipped"

    # Step 1a — Todoist
    if run_step1a():
        sources_collected.append("todoist")
    else:
        sources_skipped.append("todoist")

    # Step 1b — GCal
    if run_step1b():
        sources_collected.append("gcal")
    else:
        sources_skipped.append("gcal")

    # Step 2 — 병합
    merged = run_step2(today)
    todo_count = len(merged["todoist"])
    event_count = len(merged["gcal_events"])

    # 2소스 모두 비어있음 → 빈 브리핑
    if todo_count == 0 and event_count == 0:
        print("[Step 2] 2소스 모두 비어있음 → 빈 브리핑 발송")
        BRIEFING_PATH.parent.mkdir(parents=True, exist_ok=True)
        BRIEFING_PATH.write_text(make_empty_briefing(today))
        notion_write_status = run_step5()
        success = run_step6()
        append_run_log(make_log_entry(
            status="skipped" if success else "failed",
            reason="all_sources_empty",
            sources_collected=sources_collected,
            sources_skipped=sources_skipped,
            todo_count=0,
            event_count=0,
            notion_write_status=notion_write_status,
            comment="",
        ))
        if not success:
            sys.exit(1)
        return

    # Step 3/4 — 규칙 기반 포맷 + LLM 코멘트
    gemini_api_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_api_key:
        print("Missing GEMINI_API_KEY", file=sys.stderr)
        sys.exit(1)

    client = genai.Client(api_key=gemini_api_key)

    print("[Step 4] LLM 코멘트 생성 중...")
    comment = generate_comment(client, merged)
    print(f"[Step 4] 코멘트: {comment}")

    print("[Step 3] 규칙 기반 브리핑 포맷 빌드 중...")
    briefing = build_formatted_briefing(merged, comment)

    # 브리핑 저장
    BRIEFING_PATH.parent.mkdir(parents=True, exist_ok=True)
    BRIEFING_PATH.write_text(briefing)
    print("[Step 3] 브리핑 저장 완료")

    # Step 5 — Notion Write
    notion_write_status = run_step5()

    # Step 6 — Discord
    success = run_step6()

    append_run_log(make_log_entry(
        status="success" if success else "failed",
        reason="" if success else "discord_error",
        sources_collected=sources_collected,
        sources_skipped=sources_skipped,
        todo_count=todo_count,
        event_count=event_count,
        notion_write_status=notion_write_status,
        comment=comment,
    ))

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
