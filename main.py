"""
Notion → Slack 모닝 브리핑 에이전트 오케스트레이터

실행 순서:
  Step 1 — Notion 페이지 조회 (fetch_yesterday_page.py)
  Step 2 — 할일 블록 추출 (extract_todo_blocks.py)
  Step 3 — LLM 브리핑 생성 (Gemini)
  Step 4 — LLM 자기 검증 (Gemini)
  Step 5 — Slack 발송 (send_slack_message.py)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from google import genai

load_dotenv()

# --- 경로 설정 ---
BASE_DIR = Path(__file__).parent
SCRIPTS = {
    "fetch": BASE_DIR / ".claude/skills/notion-reader/scripts/fetch_yesterday_page.py",
    "extract": BASE_DIR / ".claude/skills/notion-reader/scripts/extract_todo_blocks.py",
    "send": BASE_DIR / ".claude/skills/slack-sender/scripts/send_slack_message.py",
}
TODO_RAW_PATH = BASE_DIR / "output" / "todo_raw.json"
BRIEFING_PATH = BASE_DIR / "output" / "briefing_draft.md"
RUN_LOG_PATH = BASE_DIR / "output" / "run_log.json"

KST = timezone(timedelta(hours=9))
MAX_LLM_RETRIES = 2
GEMINI_MODEL = "gemini-2.5-flash"


# ---------------------------------------------------------------------------
# 로그
# ---------------------------------------------------------------------------

def append_run_log(status: str, reason: str = "", todo_count: int = 0, retry_count: int = 0):
    RUN_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logs = []
    if RUN_LOG_PATH.exists():
        try:
            data = json.loads(RUN_LOG_PATH.read_text())
            logs = data if isinstance(data, list) else [data]
        except json.JSONDecodeError:
            pass
    logs.append({
        "timestamp": datetime.now(KST).isoformat(),
        "status": status,
        "reason": reason,
        "todo_count": todo_count,
        "retry_count": retry_count,
    })
    RUN_LOG_PATH.write_text(json.dumps(logs, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# Step 1 — Notion 페이지 조회
# ---------------------------------------------------------------------------

def run_step1() -> Optional[str]:
    """
    Returns:
        page_id if found, None if not found (exit 2).
    Raises SystemExit on API error (exit 1).
    """
    result = subprocess.run(
        [sys.executable, str(SCRIPTS["fetch"])],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    if result.returncode == 2:
        return None
    print(f"[Step 1] Error: {result.stderr}", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Step 2 — 할일 블록 추출
# ---------------------------------------------------------------------------

def run_step2(page_id: str, target_date: str):
    result = subprocess.run(
        [sys.executable, str(SCRIPTS["extract"]), page_id, target_date],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"[Step 2] Error: {result.stderr}", file=sys.stderr)
        sys.exit(1)


def load_todos() -> list:
    if not TODO_RAW_PATH.exists():
        return []
    data = json.loads(TODO_RAW_PATH.read_text())
    return data.get("todos", [])


# ---------------------------------------------------------------------------
# Step 3 — LLM 브리핑 생성
# ---------------------------------------------------------------------------

def build_briefing_prompt(todos: list, target_date: str) -> str:
    todos_text = json.dumps(todos, ensure_ascii=False, indent=2)
    dt = date.fromisoformat(target_date)
    weekdays_ko = ["월", "화", "수", "목", "금", "토", "일"]
    date_label = f"{dt.month:02d}/{dt.day:02d} {weekdays_ko[dt.weekday()]}"

    return f"""너는 아침 브리핑을 작성하는 어시스턴트야.

아래 할일 목록을 읽고 슬랙 브리핑 메시지를 작성해줘.

규칙:
- 헤더: 🌅 오늘의 할일 브리핑 ({date_label})
- "top_priorities" 섹션 항목은 📌 우선순위 높음 아래에 표시
- "brain_dump" 섹션 항목은 📋 일반 아래에 표시
- Slack mrkdwn 형식 사용
- 전체 500자 이내
- 마지막에 💬 동기부여 한 마디 포함
- 완료된 항목(checked: true)은 취소선(~텍스트~)으로 표시

할일 목록 (JSON):
{todos_text}

브리핑 메시지만 출력해줘. 다른 설명은 불필요."""


def generate_briefing(client: genai.Client, todos: list, target_date: str) -> str:
    prompt = build_briefing_prompt(todos, target_date)
    response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
    return response.text.strip()


# ---------------------------------------------------------------------------
# Step 4 — LLM 자기 검증
# ---------------------------------------------------------------------------

def build_verify_prompt(briefing: str, todos: list) -> str:
    todos_text = json.dumps(todos, ensure_ascii=False, indent=2)
    return f"""아래 브리핑이 모든 조건을 충족하는지 확인해줘.

조건:
1. 원본 할일 항목이 빠짐없이 포함되었는가
2. 전체 500자 이내인가 (현재 {len(briefing)}자)
3. Slack mrkdwn 형식을 준수하는가
4. 톤이 적절한가 (너무 딱딱하거나 너무 가볍지 않은가)

원본 할일:
{todos_text}

브리핑:
{briefing}

결과를 반드시 아래 JSON 형식으로만 반환해줘:
{{"pass": true, "issues": []}}
또는
{{"pass": false, "issues": ["이슈1", "이슈2"]}}"""


def verify_briefing(client: genai.Client, briefing: str, todos: list) -> dict:
    prompt = build_verify_prompt(briefing, todos)
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
# 빈 브리핑 발송
# ---------------------------------------------------------------------------

def send_empty_briefing(reason: str, target_date: str) -> bool:
    if reason == "no_page":
        message = f"오늘은 {target_date} 일지가 없습니다. 좋은 하루 되세요! 😊"
    else:
        message = "오늘은 등록된 할일이 없습니다. 자유로운 하루! 😌"

    BRIEFING_PATH.parent.mkdir(parents=True, exist_ok=True)
    BRIEFING_PATH.write_text(message)

    result = subprocess.run(
        [sys.executable, str(SCRIPTS["send"])],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def main():
    yesterday = date.today() - timedelta(days=1)
    target_date = yesterday.isoformat()

    todo_count = 0
    retry_count = 0

    # Step 1
    print("[Step 1] Notion 페이지 조회 중...")
    page_id = run_step1()

    if page_id is None:
        print(f"[Step 1] {target_date} 일지 없음 → 빈 브리핑 발송")
        success = send_empty_briefing("no_page", target_date)
        append_run_log(
            status="skipped" if success else "failed",
            reason="page_not_found",
        )
        return

    print(f"[Step 1] 페이지 발견: {page_id}")

    # Step 2
    print("[Step 2] 할일 블록 추출 중...")
    run_step2(page_id, target_date)
    todos = load_todos()
    todo_count = len(todos)
    print(f"[Step 2] {todo_count}개 할일 추출 완료")

    if not todos:
        print("[Step 2] 할일 없음 → 빈 브리핑 발송")
        success = send_empty_briefing("no_todos", target_date)
        append_run_log(
            status="skipped" if success else "failed",
            reason="todo_empty",
        )
        return

    # Step 3 & 4 — Gemini 브리핑 생성 + 검증
    gemini_api_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_api_key:
        print("Missing GEMINI_API_KEY", file=sys.stderr)
        sys.exit(1)

    client = genai.Client(api_key=gemini_api_key)

    briefing = ""
    for attempt in range(MAX_LLM_RETRIES + 1):
        print(f"[Step 3] 브리핑 생성 중... (시도 {attempt + 1}/{MAX_LLM_RETRIES + 1})")
        briefing = generate_briefing(client, todos, target_date)

        print("[Step 4] 브리핑 검증 중...")
        verify_result = verify_briefing(client, briefing, todos)

        if verify_result.get("pass"):
            retry_count = attempt
            print(f"[Step 4] 검증 통과")
            break

        print(f"[Step 4] 검증 실패: {verify_result.get('issues', [])}")
        if attempt == MAX_LLM_RETRIES:
            print("[Step 4] 최대 재시도 초과 → 원본 할일 목록 fallback")
            lines = [f"🌅 오늘의 할일 ({target_date})\n"]
            for todo in todos:
                prefix = "📌" if todo.get("section") == "top_priorities" else "📋"
                text = todo.get("text", "")
                if todo.get("checked"):
                    text = f"~{text}~"
                lines.append(f"{prefix} {text}")
            briefing = "\n".join(lines)
            retry_count = MAX_LLM_RETRIES

    # Step 3 결과 저장
    BRIEFING_PATH.parent.mkdir(parents=True, exist_ok=True)
    BRIEFING_PATH.write_text(briefing)
    print(f"[Step 3/4] 브리핑 저장: {BRIEFING_PATH}")

    # Step 5 — Slack 발송
    print("[Step 5] Slack 발송 중...")
    result = subprocess.run(
        [sys.executable, str(SCRIPTS["send"])],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        print("[Step 5] 발송 성공 ✓")
        append_run_log(
            status="success",
            todo_count=todo_count,
            retry_count=retry_count,
        )
    else:
        print(f"[Step 5] 발송 실패: {result.stderr}", file=sys.stderr)
        append_run_log(
            status="failed",
            reason="slack_error",
            todo_count=todo_count,
            retry_count=retry_count,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
