"""
Todoist + GCal → Notion Morning + Discord 모닝 브리핑 에이전트 오케스트레이터

실행 순서:
  Step 1a — Todoist 오늘 태스크 수집    (fetch_todoist_tasks.py)
  Step 1b — GCal 오늘 일정 수집         (fetch_gcal_events.py)
  Step 2  — 2소스 병합                  (merged_context.json)
  Step 3  — LLM 브리핑 생성             (Gemini)
  Step 4  — LLM 자기 검증               (Gemini)
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
MAX_LLM_RETRIES = 2
GEMINI_MODEL = "gemini-2.5-flash"


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
# Step 3 — LLM 브리핑 생성
# ---------------------------------------------------------------------------

def build_briefing_prompt(merged: dict) -> str:
    today_str = merged["date"]
    dt = date.fromisoformat(today_str)
    weekdays_ko = ["월", "화", "수", "목", "금", "토", "일"]
    date_label = f"{dt.month:02d}/{dt.day:02d} {weekdays_ko[dt.weekday()]}"
    context_json = json.dumps(merged, ensure_ascii=False, indent=2)

    return f"""너는 개인 생산성 모닝 브리핑 어시스턴트야.

아래 JSON 컨텍스트를 읽고 Discord 브리핑 메시지를 작성해줘.

**출력 형식 (정확히 따라야 함)**:
🌅 오늘의 브리핑 ({date_label})

⭐ 오늘의 Top 3
• [GCal 시간 컨텍스트 →] 태스크 (p우선순위)
• ...

📋 기타
• 태스크 (p우선순위)

💬 한 줄 동기부여 코멘트

**Top 3 선정 규칙**:
1. GCal 일정이 있는 시간대와 시간적으로 인접한 Todoist 태스크 우선
2. 동일 시간대에 여러 태스크가 있으면 p1 > p2 > p3 순
3. GCal 없으면 Todoist p1 → p2 → p3 순서로 선정

**기타 규칙**:
- 📋 기타 섹션은 Top 3에 포함되지 않은 나머지 Todoist 태스크 (없으면 섹션 생략)
- 전체 500자 이내
- Discord markdown 사용
- 한국어로 작성

컨텍스트 (JSON):
{context_json}

브리핑 메시지만 출력해줘. 다른 설명 불필요."""


def generate_briefing(client: genai.Client, merged: dict) -> str:
    prompt = build_briefing_prompt(merged)
    response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
    return response.text.strip()


# ---------------------------------------------------------------------------
# Step 4 — LLM 자기 검증
# ---------------------------------------------------------------------------

def build_verify_prompt(briefing: str, merged: dict) -> str:
    context_json = json.dumps(merged, ensure_ascii=False, indent=2)
    return f"""아래 브리핑이 조건을 충족하는지 확인해줘.

조건:
1. ⭐ 오늘의 Top 3 섹션이 존재하는가
2. 전체 {len(briefing)}자 — 500자 이내인가
3. 톤이 적절한가 (친근하고 간결한 한국어)

원본 컨텍스트:
{context_json}

브리핑:
{briefing}

결과를 반드시 아래 JSON 형식으로만 반환해줘:
{{"pass": true, "issues": []}}
또는
{{"pass": false, "issues": ["이슈1"]}}"""


def verify_briefing(client: genai.Client, briefing: str, merged: dict) -> dict:
    prompt = build_verify_prompt(briefing, merged)
    response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
    text = response.text.strip()

    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return {"pass": True, "issues": []}


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
    date_label = f"{dt.month:02d}/{dt.day:02d} {weekdays_ko[dt.weekday()]}"
    return f"🌅 오늘의 브리핑 ({date_label})\n\n오늘은 등록된 태스크와 일정이 없습니다. 자유로운 하루! 😌"


# ---------------------------------------------------------------------------
# Top 3 추출 (로그용)
# ---------------------------------------------------------------------------

def extract_top3(briefing: str) -> list[str]:
    top3 = []
    in_top3 = False
    for line in briefing.split("\n"):
        if "⭐ 오늘의 Top 3" in line:
            in_top3 = True
            continue
        if in_top3 and line.strip().startswith("•"):
            top3.append(line.strip()[1:].strip())
        elif in_top3 and line.strip() and not line.strip().startswith("•"):
            break
    return top3


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def main():
    today = date.today().isoformat()
    sources_collected = []
    sources_skipped = []
    retry_count = 0
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
            top3_items=[],
            retry_count=0,
        ))
        if not success:
            sys.exit(1)
        return

    # Step 3 & 4 — LLM
    gemini_api_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_api_key:
        print("Missing GEMINI_API_KEY", file=sys.stderr)
        sys.exit(1)

    client = genai.Client(api_key=gemini_api_key)
    briefing = ""

    for attempt in range(MAX_LLM_RETRIES + 1):
        print(f"[Step 3] 브리핑 생성 중... (시도 {attempt + 1}/{MAX_LLM_RETRIES + 1})")
        briefing = generate_briefing(client, merged)

        print("[Step 4] 검증 중...")
        verify_result = verify_briefing(client, briefing, merged)

        if verify_result.get("pass"):
            retry_count = attempt
            print("[Step 4] 검증 통과 ✓")
            break

        print(f"[Step 4] 검증 실패: {verify_result.get('issues', [])}")
        if attempt == MAX_LLM_RETRIES:
            print("[Step 4] 최대 재시도 초과 → merged_context.json 원문 발송")
            briefing = f"🌅 오늘의 브리핑 ({today})\n\n{json.dumps(merged, ensure_ascii=False, indent=2)}"
            retry_count = MAX_LLM_RETRIES

    # 브리핑 저장
    BRIEFING_PATH.parent.mkdir(parents=True, exist_ok=True)
    BRIEFING_PATH.write_text(briefing)
    print("[Step 3/4] 브리핑 저장 완료")

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
        top3_items=extract_top3(briefing),
        retry_count=retry_count,
    ))

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
