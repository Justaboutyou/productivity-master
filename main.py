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
    "todoist_completed": BASE_DIR / ".claude/skills/todoist-reader/scripts/fetch_todoist_completed.py",
    "gcal": BASE_DIR / ".claude/skills/gcal-reader/scripts/fetch_gcal_events.py",
    "notion_write": BASE_DIR / ".claude/skills/notion-writer/scripts/write_notion_morning.py",
    "notion_night": BASE_DIR / ".claude/skills/notion-writer/scripts/write_notion_night.py",
    "discord": BASE_DIR / ".claude/skills/discord-sender/scripts/send_discord_message.py",
}
TODOIST_RAW_PATH = BASE_DIR / "output" / "todoist_raw.json"
TODOIST_COMPLETED_PATH = BASE_DIR / "output" / "todoist_completed.json"
GCAL_RAW_PATH = BASE_DIR / "output" / "gcal_raw.json"
GCAL_TOMORROW_PATH = BASE_DIR / "output" / "gcal_tomorrow.json"
MERGED_PATH = BASE_DIR / "output" / "merged_context.json"
BRIEFING_PATH = BASE_DIR / "output" / "briefing_draft.md"
NIGHT_DRAFT_PATH = BASE_DIR / "output" / "night_draft.md"
RUN_LOG_PATH = BASE_DIR / "output" / "run_log.json"

LONG_DELAY_THRESHOLD_DAYS = 7

KST = timezone(timedelta(hours=9))
GEMINI_MODEL = "gemini-2.0-flash"

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


def make_log_entry(status: str, reason: str = "", mode: str = "morning", **kwargs) -> dict:
    entry = {
        "timestamp": datetime.now(KST).isoformat(),
        "mode": mode,
        "status": status,
        "reason": reason,
        "llm_model": GEMINI_MODEL,
    }
    entry.update({k: v for k, v in kwargs.items() if v is not None})
    return entry


# ---------------------------------------------------------------------------
# Step 1a — Todoist 태스크 수집
# ---------------------------------------------------------------------------

def run_step1a() -> tuple[bool, str]:
    print("[Step 1a] Todoist 태스크 수집 중...")
    result = subprocess.run(
        [sys.executable, str(SCRIPTS["todoist"])],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print(f"[Step 1a] {result.stdout.strip()}")
        return True, ""
    err = result.stderr.strip()
    print(f"[Step 1a] 실패 (skip): {err}", file=sys.stderr)
    return False, err


# ---------------------------------------------------------------------------
# Step 1b — GCal 일정 수집
# ---------------------------------------------------------------------------

def run_step1b() -> tuple[bool, str]:
    print("[Step 1b] GCal 일정 수집 중...")
    result = subprocess.run(
        [sys.executable, str(SCRIPTS["gcal"])],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print(f"[Step 1b] {result.stdout.strip()}")
        return True, ""
    err = result.stderr.strip()
    print(f"[Step 1b] 실패 (skip): {err}", file=sys.stderr)
    return False, err


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
    if event.get("colorId") == "4":  # Flamingo = 업무 캘린더
        return "work"
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


def render_events(events: list) -> list[str]:
    return [f"  {e['start']}~{e['end']}  {e['title']}" for e in events]


def build_formatted_briefing(
    merged: dict,
    starred: list[str],
    advice: dict,
    tomorrow_events: list,
) -> str:
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
            lines += render_events(work_events)
            lines.append("")
        if personal_events:
            lines.append("🌙 일정 (개인)")
            lines += render_events(personal_events)
            lines.append("")
    else:
        all_events = sorted(merged["gcal_events"], key=lambda e: e["start"])
        if all_events:
            lines.append("🌙 일정")
            lines += render_events(all_events)
            lines.append("")

    # ── 2. 업무 섹션 (태스크 없으면 섹션 숨김) ──
    if work_tasks:
        lines.append("💼 업무")
        for t in work_tasks:
            star = "  ★" if t["text"] in starred_set else ""
            lines.append(f"  {t['text']}{star}")
        lines.append("")

    # ── 3. 자기계발 섹션 (태스크 없으면 섹션 숨김) ──
    if personal_tasks:
        lines.append("📚 자기계발")
        for t in personal_tasks:
            star = "  ★" if t["text"] in starred_set else ""
            lines.append(f"  {t['text']}{star}")
        lines.append("")

    # ── 4. 백로그 섹션 ──
    if backlog_tasks:
        texts = " · ".join(t["text"] for t in backlog_tasks)
        lines += ["📦 백로그", f"  {texts}", ""]

    # ── 5. 내일 미리보기 ──
    if tomorrow_events:
        tomorrow_summary = "  " + "  /  ".join(
            f"{e['start']} {e['title']}" for e in tomorrow_events[:3]
        )
    else:
        tomorrow_summary = "  일정 없음"
    lines += [f"👀 내일: {tomorrow_summary.strip()}", ""]

    # ── 6. 친한 코치 스타일 제안 섹션 ──
    top3 = advice.get("top3", [])
    let_go = advice.get("let_go", "")
    goal = advice.get("goal", "")

    if top3 or let_go:
        lines.append(SEP)
        if top3:
            lines.append("🎯 오늘 집중할 것 Top 3")
            lines.append("")
            for i, item in enumerate(top3[:3], 1):
                lines.append(f"{i}. {item}")
            lines.append("")
        if let_go:
            lines.append(f"💆 오늘 안 해도 되는 것")
            lines.append(f"{let_go}")
            lines.append("")

    if goal:
        lines += [SEP, f"오늘 목표: {goal}", SEP]
    else:
        lines.append(SEP)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Step 4 — LLM 모닝 어드바이스 생성 (친한 코치 스타일)
# ---------------------------------------------------------------------------

def generate_morning_advice(
    client: genai.Client, merged: dict
) -> dict:
    """LLM에게 Top3 집중/내려놓을 것/오늘 목표를 JSON으로 받아 반환.

    Returns:
        {"top3": [...], "let_go": "...", "goal": "..."}
    """
    dt = date.fromisoformat(merged["date"])
    weekdays_ko = ["월", "화", "수", "목", "금", "토", "일"]
    weekday = weekdays_ko[dt.weekday()]

    tasks_text = "\n".join(
        f'  - "{t["text"]}" (p{t["priority"]}, {t.get("root_project_name", "")})' for t in merged["todoist"]
    ) or "  (없음)"
    events_text = "\n".join(
        f'  - {e["start"]}~{e["end"]} {e["title"]}' for e in merged["gcal_events"]
    ) or "  (없음)"

    prompt = f"""오늘 모닝 브리핑에 넣을 제안을 JSON으로 반환해줘.

오늘: {merged["date"]} ({weekday}요일)

[오늘 태스크]
{tasks_text}

[오늘 일정]
{events_text}

역할: 나를 잘 아는 친한 코치. 딱딱한 보고서 말투 금지. 자연스럽고 따뜻하게.

규칙:
- top3: 오늘 집중할 것 3가지. 각 항목은 "태스크명 — 한 줄 이유" 형태 (이유는 친한 코치가 말하듯 30자 이내, 격식체 금지)
- let_go: 오늘 안 해도 되는 것 한 문장 (왜 내려놔도 되는지 포함, 40자 이내)
- goal: 오늘 목표 한 줄 리마인더 (20자 이내, 이모지 1개)

JSON만 출력 (다른 텍스트 없이):
{{"top3": ["항목1", "항목2", "항목3"], "let_go": "내려놓을 것 설명", "goal": "목표 한 줄 🎯"}}"""

    try:
        response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        raw = response.text.strip()
    except Exception as e:
        print(f"[Step 4] LLM API 오류 (fallback): {e}", file=sys.stderr)
        return {"top3": [], "let_go": "", "goal": ""}

    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return {"top3": [], "let_go": "", "goal": raw}

    try:
        data = json.loads(match.group())
        return {
            "top3": data.get("top3", []),
            "let_go": data.get("let_go", ""),
            "goal": data.get("goal", ""),
        }
    except json.JSONDecodeError:
        return {"top3": [], "let_go": "", "goal": ""}


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
    SEP = "──────────────────────────"
    return "\n".join([
        SEP,
        f"브리핑 · {date_label}",
        SEP,
        "",
        "💼 업무",
        "  (없음)",
        "",
        "📚 자기계발",
        "  (없음)",
        "",
        SEP,
        '"오늘은 등록된 태스크와 일정이 없습니다. 자유로운 하루! 😌"',
        SEP,
    ])


# ---------------------------------------------------------------------------
# Night Mode — Step N2: 완료 태스크 수집
# ---------------------------------------------------------------------------

def run_step_n2() -> tuple[bool, str]:
    print("[Night N2] Todoist 완료 태스크 수집 중...")
    result = subprocess.run(
        [sys.executable, str(SCRIPTS["todoist_completed"])],
        capture_output=True,
        text=True,
    )
    if result.returncode in (0, 2):  # 2 = skip (아침 데이터 없음)
        print(f"[Night N2] {result.stdout.strip() or result.stderr.strip()}")
        return result.returncode == 0, ""
    err = result.stderr.strip()
    print(f"[Night N2] 실패 (skip): {err}", file=sys.stderr)
    return False, err


# ---------------------------------------------------------------------------
# Night Mode — Step N4: LLM 제언 생성
# ---------------------------------------------------------------------------

def generate_night_advice(
    client: genai.Client,
    incomplete: list,
    long_delayed: list,
    done: int,
    total: int,
    gcal_events: list,
) -> tuple[str, list, str]:
    """LLM에게 내일 focus 태스크 1개 + 장기지연 제언 + 오늘의 발견 코멘트를 JSON으로 받아 반환.

    Returns:
        (focus_task, delayed_advice, comment)
        focus_task:     "태스크명 — 이유" 형태의 한 줄 문자열
        delayed_advice: [{"task": str, "days": int, "advice": str}, ...]
        comment:        오늘 완료/GCal에서 발견한 구체적인 한 줄
    """
    def fmt_tasks(tasks: list) -> str:
        if not tasks:
            return "  (없음)"
        return "\n".join(f'  - "{t["text"]}" (p{t["priority"]})' for t in tasks)

    def fmt_delayed(tasks: list) -> str:
        if not tasks:
            return "  (없음)"
        return "\n".join(
            f'  - "{t["text"]}" ({t["overdue_days"]}일 경과, p{t["priority"]})' for t in tasks
        )

    def fmt_events(events: list) -> str:
        if not events:
            return "  (없음)"
        return "\n".join(f'  - {e["start"]}~{e["end"]} {e["title"]}' for e in events)

    prompt = f"""오늘 하루 결산 제언을 JSON으로 반환해줘.

완료: {done}/{total}개

[오늘 일정 (GCal)]
{fmt_events(gcal_events)}

[오늘 미완료 태스크]
{fmt_tasks(incomplete)}

[7일 이상 미뤄온 태스크]
{fmt_delayed(long_delayed)}

제언 기준:
- focus_task: 미완료 중 내일 딱 하나만 고른다면 어떤 것인지. "태스크명 — 이유" 형태, 이유는 30자 이내. 미완료가 없으면 빈 문자열.
- delayed_advice: 7일+ 미룬 항목별로 삭제/재지정/쪼개기 중 하나 제언 (15자 이내).
- comment: 오늘 완료 태스크 또는 GCal 일정에서 구체적으로 잘한 것 하나를 발견해서 언급. "수고했어" 같은 기계적인 말 금지. 완료가 전혀 없으면 일정 기반으로. 30자 이내, 이모지 1개.

JSON만 출력 (다른 텍스트 없이):
{{"focus_task": "태스크명 — 이유", "delayed_advice": [{{"task": "태스크명", "days": 숫자, "advice": "제언"}}], "comment": "오늘의 발견 한 줄"}}"""

    try:
        response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        raw = response.text.strip()
    except Exception as e:
        print(f"[Night N4] LLM API 오류 (fallback): {e}", file=sys.stderr)
        return "", [], ""

    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return "", [], raw

    try:
        data = json.loads(match.group())
        return (
            data.get("focus_task", ""),
            data.get("delayed_advice", []),
            data.get("comment", ""),
        )
    except json.JSONDecodeError:
        return "", [], raw


# ---------------------------------------------------------------------------
# Night Mode — 나이트 브리핑 포맷 빌드
# ---------------------------------------------------------------------------

def build_night_briefing(
    merged: dict,
    completed: list,
    incomplete: list,
    focus_task: str,
    long_delayed: list,
    delayed_advice: list,
    comment: str,
    gcal_events: list,
) -> str:
    dt = date.fromisoformat(merged["date"])
    weekdays_ko = ["월", "화", "수", "목", "금", "토", "일"]
    weekday = weekdays_ko[dt.weekday()]
    date_label = f"{dt.month:02d}/{dt.day:02d} {weekday}요일"

    SEP = "──────────────────────────"
    lines: list[str] = [SEP, f"결산 · {date_label}", SEP, ""]

    # ── GCal 일정 ──
    if gcal_events:
        lines.append("📅 오늘 보낸 시간")
        for e in sorted(gcal_events, key=lambda x: x["start"]):
            lines.append(f"  {e['start']}~{e['end']}  {e['title']}")
        lines.append("")

    # ── 카테고리별 완료 태스크 ──
    morning_tasks = merged.get("todoist", [])
    completed_ids = {t["id"] for t in completed if t.get("id")}

    for label, emoji, cat in [
        ("업무", "💼", "work"),
        ("자기계발", "📚", "personal"),
        ("백로그", "📦", "backlog"),
    ]:
        cat_total = [t for t in morning_tasks if classify_todoist_task(t) == cat]
        cat_done = [t for t in cat_total if t.get("id") in completed_ids]
        if not cat_total:
            continue
        lines.append(f"{emoji} {label} ({len(cat_done)} / {len(cat_total)})")
        if cat_done:
            for t in cat_done:
                lines.append(f"  ✓ {t['text']}")
        else:
            lines.append("  (없음)")
        lines.append("")

    # ── 내일 하나만 ──
    if focus_task:
        lines += ["🎯 내일 하나만 고른다면", f"  • {focus_task}", ""]

    # ── 장기 지연 제언 ──
    if delayed_advice:
        lines.append("🗂️ 오래 미뤄온 것 (7일+)")
        advice_map = {a["task"]: (a["advice"], a.get("days", 0)) for a in delayed_advice}
        for t in long_delayed:
            adv, days = advice_map.get(t["text"], ("재검토 필요", t["overdue_days"]))
            lines.append(f"  • {t['text']} ({days}일째) → {adv}")
        lines.append("")

    # ── LLM 코멘트 ──
    if comment:
        lines += [SEP, f'"{comment}"', SEP]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Night Mode — Step N5: Notion 저녁 제언 섹션
# ---------------------------------------------------------------------------

def run_step_n5() -> str:
    print("[Night N5] Notion AI 저녁 제언 섹션 채우기 중...")
    result = subprocess.run(
        [sys.executable, str(SCRIPTS["notion_night"])],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print(f"[Night N5] {result.stdout.strip()}")
        return "appended" if "appended" in result.stdout else "success"
    print(f"[Night N5] 실패 (skip): {result.stderr.strip()}", file=sys.stderr)
    return "skipped"


# ---------------------------------------------------------------------------
# Night Mode — Step N6: Discord 발송
# ---------------------------------------------------------------------------

def run_step_n6() -> bool:
    print("[Night N6] Discord 나이트 발송 중...")
    result = subprocess.run(
        [sys.executable, str(SCRIPTS["discord"]), "--file", str(NIGHT_DRAFT_PATH)],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print("[Night N6] 발송 성공 ✓")
        return True
    print(f"[Night N6] 발송 실패: {result.stderr.strip()}", file=sys.stderr)
    return False


# ---------------------------------------------------------------------------
# Night Mode — 오케스트레이터
# ---------------------------------------------------------------------------

def run_night_mode():
    today = datetime.now(KST).date().isoformat()
    today_dt = datetime.now(KST).date()
    notion_write_status = "skipped"

    print(f"[Night] 나이트 라운드 시작: {today}")

    # Step N1 — 아침 merged_context 로드 (재수집 없음)
    print("[Night N1] 아침 merged_context.json 로드 중...")
    if not MERGED_PATH.exists():
        print("[Night N1] 아침 캐시 없음 — Todoist 재수집으로 폴백")
        ok, _ = run_step1a()
        run_step2(today)
        if not MERGED_PATH.exists():
            print("[Night N1] 재수집도 실패 — 빈 결산 발송")
            NIGHT_DRAFT_PATH.parent.mkdir(parents=True, exist_ok=True)
            NIGHT_DRAFT_PATH.write_text("오늘 아침 데이터가 없어 결산을 생성할 수 없습니다.")
            run_step_n6()
            return

    merged = json.loads(MERGED_PATH.read_text())
    morning_tasks = merged.get("todoist", [])
    print(f"[Night N1] 아침 계획: {len(morning_tasks)}개 태스크")

    # Step N2 — 완료 태스크 수집
    run_step_n2()
    completed: list = []
    if TODOIST_COMPLETED_PATH.exists():
        try:
            completed = json.loads(TODOIST_COMPLETED_PATH.read_text()).get("tasks", [])
        except json.JSONDecodeError:
            pass

    # Step N3 — Python pre-compute
    completed_ids = {t["id"] for t in completed if t.get("id")}
    incomplete = [t for t in morning_tasks if t.get("id") and t["id"] not in completed_ids]

    long_delayed = []
    for t in morning_tasks:
        due = t.get("due_date", "")
        if not due:
            continue
        try:
            overdue_days = (today_dt - date.fromisoformat(due)).days
        except ValueError:
            continue
        if overdue_days >= LONG_DELAY_THRESHOLD_DAYS:
            long_delayed.append({**t, "overdue_days": overdue_days})

    print(f"[Night N3] 미완료: {len(incomplete)}개 / 장기 지연: {len(long_delayed)}개")

    # Step N4 — LLM 제언 생성
    gemini_api_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_api_key:
        print("Missing GEMINI_API_KEY", file=sys.stderr)
        sys.exit(1)

    client = genai.Client(api_key=gemini_api_key)
    print("[Night N4] LLM 제언 생성 중...")
    gcal_events = merged.get("gcal_events", [])
    focus_task, delayed_advice, comment = generate_night_advice(
        client, incomplete, long_delayed, len(completed), len(morning_tasks), gcal_events
    )
    print(f"[Night N4] 코멘트: {comment}")

    # 나이트 브리핑 저장
    night_briefing = build_night_briefing(
        merged, completed, incomplete,
        focus_task, long_delayed, delayed_advice, comment, gcal_events
    )
    NIGHT_DRAFT_PATH.parent.mkdir(parents=True, exist_ok=True)
    NIGHT_DRAFT_PATH.write_text(night_briefing)
    print("[Night N4] 나이트 브리핑 저장 완료")

    # Step N5 — Notion 저녁 제언
    notion_write_status = run_step_n5()

    # Step N6 — Discord
    success = run_step_n6()

    append_run_log(make_log_entry(
        status="success" if success else "failed",
        reason="" if success else "discord_error",
        mode="night",
        todo_count=len(morning_tasks),
        completed_count=len(completed),
        incomplete_count=len(incomplete),
        long_delayed_count=len(long_delayed),
        notion_write_status=notion_write_status,
        comment=comment,
    ))

    if not success:
        sys.exit(1)


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def main():
    if "--mode" in sys.argv:
        idx = sys.argv.index("--mode")
        if idx + 1 < len(sys.argv) and sys.argv[idx + 1] == "night":
            run_night_mode()
            return

    today = datetime.now(KST).date().isoformat()
    sources_collected = []
    sources_skipped = []
    skip_errors: dict[str, str] = {}
    notion_write_status = "skipped"

    # Step 1a — Todoist
    ok, err = run_step1a()
    if ok:
        sources_collected.append("todoist")
    else:
        sources_skipped.append("todoist")
        if err:
            skip_errors["todoist"] = err

    # Step 1b — GCal (오늘)
    ok, err = run_step1b()
    if ok:
        sources_collected.append("gcal")
    else:
        sources_skipped.append("gcal")
        if err:
            skip_errors["gcal"] = err

    # Step 1c — GCal (내일, 미리보기용 — 실패해도 계속 진행)
    print("[Step 1c] GCal 내일 일정 수집 중...")
    result = subprocess.run(
        [sys.executable, str(SCRIPTS["gcal"]), "--tomorrow"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print(f"[Step 1c] {result.stdout.strip()}")
    else:
        print(f"[Step 1c] 실패 (skip): {result.stderr.strip()}", file=sys.stderr)

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
            skip_errors=skip_errors or None,
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

    # Step 4 — LLM 어드바이스 생성 + p1 ★ 코드 보장
    print("[Step 4] LLM 어드바이스 생성 중...")
    advice = generate_morning_advice(client, merged)

    # p1은 코드 레벨에서 무조건 ★ 보장
    starred = [t["text"] for t in merged["todoist"] if t.get("priority") == 1]

    print(f"[Step 4] ★ 태스크: {starred}")
    print(f"[Step 4] 오늘 목표: {advice.get('goal', '')}")

    # 내일 이벤트 로드
    tomorrow_events: list = []
    if GCAL_TOMORROW_PATH.exists():
        try:
            tomorrow_events = json.loads(GCAL_TOMORROW_PATH.read_text()).get("events", [])
        except json.JSONDecodeError:
            pass

    # Step 3 — 포맷 빌드
    print("[Step 3] 규칙 기반 브리핑 포맷 빌드 중...")
    briefing = build_formatted_briefing(merged, starred, advice, tomorrow_events)

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
        skip_errors=skip_errors or None,
        todo_count=todo_count,
        event_count=event_count,
        notion_write_status=notion_write_status,
        starred_items=starred,
        comment=advice.get("goal", ""),
    ))

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
