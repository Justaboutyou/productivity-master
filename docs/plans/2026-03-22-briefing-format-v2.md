# Briefing Format V2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 브리핑 출력 포맷을 5섹션(일정/업무/자기계발/백로그/코멘트) 구조로 교체하고, LLM이 JSON으로 ★와 코멘트를 한 번에 반환하도록 한다.

**Architecture:** `fetch_todoist_tasks.py`에 `due_date` 필드를 추가하고, `main.py`의 Step 3/4 로직을 완전히 교체한다. GCal 공백 슬롯 계산 헬퍼를 추가하고, LLM 단일 호출로 ★ 목록 + 코멘트를 JSON으로 받아 코드가 포맷을 조립한다. `message_format_guide.md`도 새 포맷으로 업데이트한다.

**Tech Stack:** Python 3.11, google-genai (Gemini 2.5 Flash), 기존 분류 로직 유지

---

### Task 1: `fetch_todoist_tasks.py`에 `due_date` 필드 추가

**Files:**
- Modify: `.claude/skills/todoist-reader/scripts/fetch_todoist_tasks.py:108-114`

`due_date`는 이미 `due_date = due_str[:10]`로 계산되어 있으나 result 딕셔너리에 포함되지 않는다.

**Step 1: `due_date` 필드를 result 딕셔너리에 추가**

```python
result.append({
    "text": task.get("content", ""),
    "priority": priority,
    "due_date": due_date,      # ← 추가
    "due_time": due_time,
    "project_name": project_name,
    "root_project_name": root_project_name,
})
```

**Step 2: 수동 확인 (선택)**

로컬에서 `python fetch_todoist_tasks.py` 실행 후 `output/todoist_raw.json` 확인.
각 태스크에 `"due_date": "2026-03-22"` 필드가 있으면 성공.

**Step 3: Commit**

```bash
git add .claude/skills/todoist-reader/scripts/fetch_todoist_tasks.py
git commit -m "feat: todoist 태스크 스키마에 due_date 필드 추가"
```

---

### Task 2: `main.py` — 시간 유틸 + GCal 공백 슬롯 계산 추가

**Files:**
- Modify: `main.py` — 기존 상수 선언부 아래에 헬퍼 함수 추가

**Step 1: 기존 `classify_gcal_event()` 직전에 헬퍼 함수 3개 삽입**

```python
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
```

**Step 2: Commit**

```bash
git add main.py
git commit -m "feat: 시간 유틸 및 GCal 공백 슬롯 계산 헬퍼 추가"
```

---

### Task 3: `main.py` — `generate_stars_and_comment()` 작성 (LLM 단일 호출)

**Files:**
- Modify: `main.py` — 기존 `generate_comment()` 함수를 교체

기존 `generate_comment()` 함수 전체를 아래 `generate_stars_and_comment()`로 교체한다.

**Step 1: 기존 `generate_comment()` 삭제 후 아래 함수로 교체**

```python
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
    import re
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return [], raw  # fallback: 코멘트 전체를 텍스트로

    try:
        data = json.loads(match.group())
        return data.get("starred", []), data.get("comment", "")
    except json.JSONDecodeError:
        return [], raw
```

**Step 2: `main.py` 상단 import에 `re` 추가 확인**

`import re`가 없으면 `from __future__ import annotations` 아래 import 블록에 추가.
(현재 코드에는 없음 — 추가 필요)

**Step 3: Commit**

```bash
git add main.py
git commit -m "feat: LLM 단일 호출로 ★ 목록 + 코멘트 JSON 반환 함수 추가"
```

---

### Task 4: `main.py` — `build_formatted_briefing()` 완전 교체

**Files:**
- Modify: `main.py` — 기존 `build_formatted_briefing()` 전체 교체

기존 함수를 아래로 교체한다. `render_block()` 내부 헬퍼는 제거하고 새 헬퍼 `render_events_with_gaps()`를 포함한다.

**Step 1: 기존 `build_formatted_briefing()` 전체 삭제 후 아래로 교체**

```python
# ---------------------------------------------------------------------------
# Step 3 — 포맷 빌더
# ---------------------------------------------------------------------------

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
```

**Step 2: Commit**

```bash
git add main.py
git commit -m "feat: 브리핑 포맷 빌더를 5섹션 구조로 교체"
```

---

### Task 5: `main.py` — `main()` 함수 내 Step 3/4 호출부 수정

**Files:**
- Modify: `main.py:374-392` (Step 3/4 블록)

기존 호출:
```python
comment = generate_comment(client, merged)
briefing = build_formatted_briefing(merged, comment)
```

새 호출로 교체:
```python
# Step 4 — LLM ★ + 코멘트
all_events = merged["gcal_events"]
gap_slots = calculate_gap_slots(all_events)
print("[Step 4] LLM ★ 판단 + 코멘트 생성 중...")
starred, comment = generate_stars_and_comment(client, merged, gap_slots)
print(f"[Step 4] ★ 태스크: {starred}")
print(f"[Step 4] 코멘트: {comment}")

# Step 3 — 포맷 빌드
print("[Step 3] 규칙 기반 브리핑 포맷 빌드 중...")
briefing = build_formatted_briefing(merged, starred, comment)
```

또한 `make_empty_briefing()` 내 구분선도 `━━━` → `──────────────────────────` 로 교체.

```python
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
```

**Step 2: Commit**

```bash
git add main.py
git commit -m "feat: main() Step 3/4 호출부 및 빈 브리핑 포맷 업데이트"
```

---

### Task 6: `message_format_guide.md` 업데이트

**Files:**
- Modify: `.claude/skills/briefing-generator/references/message_format_guide.md`

기존 파일 전체를 새 포맷 스펙으로 교체.

**Step 1: 파일 전체 교체**

```markdown
# Discord 브리핑 메시지 형식 가이드 (V2)

## 전체 섹션 순서 (고정)

1. 일정 (GCal)
2. 업무 (Todoist: 業務リスト)
3. 자기계발 (Todoist: 자기계발)
4. 백로그 (Todoist: 간단일 리스트)
5. LLM 한 줄 코멘트

---

## 구분선

`──────────────────────────` (헤더 위아래, 코멘트 위아래)

---

## 1. 일정 섹션

평일(월~금):
- `💼 일정 (업무)` → classify_gcal_event == "work" 인 이벤트
- `🌙 일정 (개인)` → classify_gcal_event == "personal" 인 이벤트

주말(토~일):
- `🌙 일정` → 전체 GCal 이벤트 (업무 블록 생략)

이벤트가 없는 블록은 생략.

### GCal 분류 로직 (우선순위 순)
1. `colorId == "4"` → personal
2. 제목 개인 키워드: `심리상담`, `병원`, `운동`, `자세교정`, `가족`, `약속` → personal
3. 제목 업무 키워드: `미팅`, `스탠드업`, `리뷰`, `발표`, `보고` → work
4. 시간대 폴백: 09:00~17:59 → work, 그 외 → personal

### 이벤트 표기
- 각 이벤트: `  HH:MM - HH:MM  제목`
- 이벤트 사이 공백 ≥ 30분: `  ···  (Xh Xm 공백)` 줄 삽입

---

## 2. 업무 섹션

```
💼 업무
  태스크 텍스트  ★
  태스크 텍스트
```

- Todoist 프로젝트 `業務リスト` (하위 프로젝트 포함), due date ≤ 오늘
- 태스크 없으면 `  (없음)` 표시
- ★: LLM이 JSON으로 반환한 starred 목록에 포함된 태스크

---

## 3. 자기계발 섹션

```
📚 자기계발
  태스크 텍스트  ★
```

- Todoist 프로젝트 `자기계발` (하위 프로젝트 포함), due date ≤ 오늘
- 태스크 없으면 `  (없음)` 표시

---

## 4. 백로그 섹션

```
📦 백로그
  태스크1 · 태스크2 · 태스크3
```

- Todoist 프로젝트 `간단일 리스트`, due date ≤ 오늘
- 항목 없으면 섹션 자체 생략

---

## 5. LLM 코멘트

```
──────────────────────────
"한 줄 코멘트 내용 💪"
──────────────────────────
```

- 30자 이내, 한국어, 친근하고 실용적
- 이모지 1개 포함
- 가장 긴 GCal 공백 슬롯을 활용한 구체적 제안

---

## LLM ★ 판단 기준 (시스템 프롬프트)

LLM은 `{"starred": [...], "comment": "..."}` JSON을 반환.

판단 기준:
- p1은 무조건 ★
- p2 중 due date가 오늘이면 ★
- 총 공백 시간이 120분 미만인 날은 전체 ★를 2개 이하로 제한
- 업무와 자기계발 각각 독립적으로 판단

---

## 전체 출력 예시 (주말)

```
──────────────────────────
브리핑 · 03/22 일요일
──────────────────────────

🌙 일정
  08:00 - 09:00  산책, 편의점
  ···  (10h 공백)
  19:00 - 20:00  심리상담 (안미순 교수님)
  21:15 - 22:00  자세교정

💼 업무
  (없음)

📚 자기계발
  AI LLM 부트캠프 강의 수강  ★
  주간 회고 작성하기  ★
  클로드 코드 시리즈
  조코딩 바이브코딩 강의
  에이전틱 AI 발전시키기
  클로드 원격 접속
  Agents

📦 백로그
  주연 코트 찾기 · 가계부 기록 · 스미토모 계좌 수정

──────────────────────────
"19:00 전까지 통으로 비어 있어요. 강의 + 회고, 오늘 안에 충분히 됩니다 💪"
──────────────────────────
```

## 전체 출력 예시 (평일)

```
──────────────────────────
브리핑 · 03/24 월요일
──────────────────────────

💼 일정 (업무)
  10:00 - 11:00  팀 스탠드업
  ···  (3h 공백)
  14:00 - 15:00  제품 리뷰

🌙 일정 (개인)
  19:00 - 20:00  심리상담

💼 업무
  전략 자료 준비  ★
  월간 보고서 초안

📚 자기계발
  (없음)

📦 백로그
  개발 환경 업데이트 · 문서 정리

──────────────────────────
"14:00~17:00 사이 전략 자료에 집중할 찬스예요 🔥"
──────────────────────────
```
```

**Step 2: Commit**

```bash
git add .claude/skills/briefing-generator/references/message_format_guide.md
git commit -m "docs: message_format_guide를 V2 포맷으로 업데이트"
```

---

### Task 7: `briefing-generator/SKILL.md` 업데이트

**Files:**
- Modify: `.claude/skills/briefing-generator/SKILL.md`

**Step 1: SKILL.md 전체 교체**

```markdown
# briefing-generator 스킬 (V2)

## 역할
규칙 기반 포맷 빌더 + Gemini LLM 단일 호출로 ★ 판단 + 코멘트를 생성하고,
5섹션 구조 Discord 브리핑을 조립한다.

## Step 3 — 규칙 기반 포맷 빌드

**입력**: `output/merged_context.json`
**참조**: `references/message_format_guide.md`

포맷 구조:
1. 일정 (GCal — 업무/개인 분리 또는 통합)
2. 업무 (Todoist: 業務リスト)
3. 자기계발 (Todoist: 자기계발)
4. 백로그 (Todoist: 간단일 리스트)
5. LLM 코멘트

## Step 4 — LLM ★ 판단 + 코멘트 (단일 호출)

**모델**: `gemini-2.5-flash`
**반환 형식**:
```json
{"starred": ["태스크 텍스트1", ...], "comment": "한 줄 코멘트"}
```

★ 판단 기준:
- p1 무조건 ★
- p2 중 due date = 오늘이면 ★
- 총 공백 < 120분이면 전체 ★ 2개 이하
- 업무/자기계발 각각 독립 판단

코멘트: 30자 이내, 한국어, 이모지 1개, 가장 긴 공백 슬롯 활용

## 검증 (자기 검증 제거)

V2에서는 별도 자기 검증 단계 없음.
LLM JSON 파싱 실패 시: starred=[], comment=raw_text로 폴백.
```

**Step 2: Commit**

```bash
git add .claude/skills/briefing-generator/SKILL.md
git commit -m "docs: briefing-generator SKILL.md를 V2 구조로 업데이트"
```

---

### Task 8: 통합 확인

**Step 1: dry-run (로컬, GEMINI_API_KEY 없이)**

`merged_context.json`을 수동으로 작성해 `build_formatted_briefing()` 출력 확인:

```python
# test_format.py (임시)
import json, sys
sys.path.insert(0, ".")
from main import build_formatted_briefing

merged = {
    "date": "2026-03-22",
    "todoist": [
        {"text": "AI LLM 부트캠프 강의 수강", "priority": 2, "due_date": "2026-03-22", "due_time": "", "root_project_name": "자기계발", "project_name": "자기계발"},
        {"text": "주간 회고 작성하기", "priority": 2, "due_date": "2026-03-22", "due_time": "", "root_project_name": "자기계발", "project_name": "자기계발"},
        {"text": "주연 코트 찾기", "priority": 4, "due_date": "2026-03-22", "due_time": "", "root_project_name": "간단일 리스트", "project_name": "간단일 리스트"},
    ],
    "gcal_events": [
        {"title": "산책, 편의점", "start": "08:00", "end": "09:00", "colorId": ""},
        {"title": "심리상담 (안미순 교수님)", "start": "19:00", "end": "20:00", "colorId": "4"},
        {"title": "자세교정", "start": "21:15", "end": "22:00", "colorId": "4"},
    ],
}

starred = ["AI LLM 부트캠프 강의 수강", "주간 회고 작성하기"]
comment = "19:00 전까지 통으로 비어 있어요. 강의 + 회고, 오늘 안에 충분히 됩니다 💪"
print(build_formatted_briefing(merged, starred, comment))
```

실행: `python test_format.py`

기대 출력:
```
──────────────────────────
브리핑 · 03/22 일요일
──────────────────────────

🌙 일정
  08:00 - 09:00  산책, 편의점
  ···  (10h 공백)
  19:00 - 20:00  심리상담 (안미순 교수님)
  ···  (1h 15m 공백)    ← 75분
  21:15 - 22:00  자세교정

💼 업무
  (없음)

📚 자기계발
  AI LLM 부트캠프 강의 수강  ★
  주간 회고 작성하기  ★

📦 백로그
  주연 코트 찾기

──────────────────────────
"19:00 전까지 통으로 비어 있어요. 강의 + 회고, 오늘 안에 충분히 됩니다 💪"
──────────────────────────
```

**Step 2: test_format.py 삭제**

```bash
rm test_format.py
```

**Step 3: Final commit**

```bash
git add docs/plans/2026-03-22-briefing-format-v2.md
git commit -m "docs: briefing format V2 구현 플랜 저장"
```
