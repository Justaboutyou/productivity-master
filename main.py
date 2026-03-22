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
import re
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
# 시간 유틸
# ---------------------------------------------------------------------------

def time_to_minutes(t: str) -> int:
    """'HH:MM' → 분 단위 정수."""
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def format_gap(minutes: int) -> str:
    """분 단위 공백 → '···  (Xh Xm 공백)' 문자열."""
    if minutes < 60:
        return f"···  ({minutes}m 공백)"
    h = minutes // 60
    m = minutes % 60
    return f"···  ({h}h 공백)" if m == 0 else f"···  ({h}h {m}m 공백)"


def calculate_gap_slots(events: list) -> list:
    """이벤트 목록에서 30분 이상 공백 슬롯 목록 반환.
    반환: [{"start": "HH:MM", "end": "HH:MM", "minutes": int}, ...]
    """
    if not events:
        return []
    sorted_evts = sorted(events, key=lambda e: e["start"])
    gaps = []
    for i in range(1, len(sorted_evts)):
        prev_end = sorted_evts[i - 1]["end"]
        curr_start = sorted_evts[i]["start"]
        gap_min = time_to_minutes(curr_start) - time_to_minutes(prev_end)
        if gap_min >= 30:
            gaps.append({"start": prev_end, "end": curr_start, "minutes": gap_min})
    return gaps


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


def render_events_with_gaps(events: list) -> list[str]:
    """이벤트 목록을 'HH:MM - HH:MM  제목' 형식으로 렌더링. 30분 이상 공백은 ··· 줄 삽입."""
    lines = []
    prev_end = None
    for event in events:
        if prev_end is not None:
            gap = time_to_minutes(event["start"]) - time_to_minutes(prev_end)
            if gap >= 30:
                lines.append(f"  {format_gap(gap)}")
        lines.append(f"  {event['start']} - {event['end']}  {event['title']}")
        prev_end = event["end"]
    return lines


def build_formatted_briefing(merged: dict, starred: list[str], comment: str) -> str:
    dt = date.fromisoformat(merged["date"])
    weekdays_ko = ["월", "화", "수", "목", "금", "토", "일"]
    weekday = weekdays_ko[dt.weekday()]
    date_label = f"{dt.month:02d}/{dt.day:02d} {weekday}요일"
    is_weekday = dt.weekday() < 5
    starred_set = set(starred)

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

    SEP = "──────────────────────────"
    lines: list[str] = [SEP, f"브리핑 · {date_label}", SEP, ""]

    # ── 1. 일정 섹션 ──
    if is_weekday:
        if work_events:
            lines.append("💼 일정 (업무)")
            lines += render_events_with_gaps(work_events)
            lines.append("")
        if personal_events:
            lines.append("🌙 일정 (개인)")
            lines += render_events_with_gaps(personal_events)
            lines.append("")
    else:
        all_events = sorted(merged["gcal_events"], key=lambda e: e["start"])
        if all_events:
            lines.append("🌙 일정")
            lines += render_events_with_gaps(all_events)
            lines.append("")

    # ── 2. 업무 섹션 ──
    lines.append("💼 업무")
    if work_tasks:
        for t in work_tasks:
            star = "  ★" if t["text"] in starred_set else ""
            lines.append(f"  {t['text']}{star}")
    else:
        lines.append("  (없음)")
    lines.append("")

    # ── 3. 자기계발 섹션 ──
    lines.append("📚 자기계발")
    if personal_tasks:
        for t in personal_tasks:
            star = "  ★" if t["text"] in starred_set else ""
            lines.append(f"  {t['text']}{star}")
    else:
        lines.append("  (없음)")
    lines.append("")

    # ── 4. 백로그 섹션 ──
    if backlog_tasks:
        texts = " · ".join(t["text"] for t in backlog_tasks)
        lines += ["📦 백로그", f"  {texts}", ""]

    # ── 5. LLM 코멘트 ──
    lines += [SEP, f'"{comment}"', SEP]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Step 4 — LLM ★ 판단 + 한 줄 코멘트 생성 (단일 호출)
# ---------------------------------------------------------------------------

def generate_stars_and_comment(
    client: genai.Client, merged: dict, gap_slots: list
) -> tuple[list[str], str]:
    """LLM에게 ★ 태스크 목록과 한 줄 코멘트를 JSON으로 받아 반환.

    Returns:
        (starred_texts, comment)
        starred_texts: ★를 붙여야 하는 태스크 text 목록
        comment: 한 줄 코멘트 문자열
    """
    dt = date.fromisoformat(merged["date"])
    weekdays_ko = ["월", "화", "수", "목", "금", "토", "일"]
    weekday = weekdays_ko[dt.weekday()]
    today = merged["date"]

    work_tasks = [t for t in merged["todoist"] if classify_todoist_task(t) == "work"]
    personal_tasks = [t for t in merged["todoist"] if classify_todoist_task(t) == "personal"]

    def fmt_tasks(tasks: list) -> str:
        if not tasks:
            return "  (없음)"
        return "\n".join(
            f'  - "{t["text"]}" (p{t["priority"]}, due: {t.get("due_date", today)})'
            for t in tasks
        )

    gap_desc = (
        ", ".join(f"{g['start']}~{g['end']} ({g['minutes']}분)" for g in gap_slots)
        if gap_slots else "없음"
    )
    longest = max(gap_slots, key=lambda g: g["minutes"]) if gap_slots else None
    longest_desc = (
        f"{longest['start']}~{longest['end']} ({longest['minutes']}분)"
        if longest else "없음"
    )
    total_gap_min = sum(g["minutes"] for g in gap_slots)

    prompt = f"""오늘 브리핑용 ★ 판단과 한 줄 코멘트를 JSON으로 반환해줘.

오늘: {today} ({weekday}요일)
GCal 공백 슬롯: {gap_desc}
가장 긴 공백: {longest_desc}
총 공백 시간: {total_gap_min}분

[업무 태스크]
{fmt_tasks(work_tasks)}

[자기계발 태스크]
{fmt_tasks(personal_tasks)}

★ 판단 기준:
- p1은 무조건 ★
- p2 중 due date가 오늘({today})이면 ★
- 총 공백 시간이 120분 미만인 날은 전체 ★를 2개 이하로 제한
- 업무와 자기계발 각각 독립적으로 판단

한 줄 코멘트 규칙:
- 30자 이내, 한국어, 친근하고 실용적
- 이모지 1개 포함
- 가장 긴 공백 슬롯을 활용한 구체적 제안 포함

JSON만 출력 (다른 텍스트 없이):
{{"starred": ["태스크 텍스트1", "태스크 텍스트2"], "comment": "한 줄 코멘트"}}"""

    response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
    raw = response.text.strip()

    # JSON 추출 (마크다운 코드블록 대응)
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return [], raw  # fallback: 코멘트 전체를 텍스트로

    try:
        data = json.loads(match.group())
        return data.get("starred", []), data.get("comment", "")
    except json.JSONDecodeError:
        return [], raw


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
