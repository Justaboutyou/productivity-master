# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## 절대 규칙 (Absolute Rules)

**이 규칙을 위반하면 안 된다.**

### Karpathy Guidelines

**1. 코딩 전에 생각하라**
- 가정을 명시적으로 밝혀라. 불확실하면 물어라.
- 해석이 여러 개면 제시하고 고르게 해라. 혼자 침묵 속에 결정하지 마라.
- 더 단순한 방법이 있으면 말해라. 필요하면 반박해라.
- 혼란스러운 게 있으면 멈춰라. 뭐가 혼란스러운지 명시하고 물어라.

**2. 단순함 우선**
- 요청받은 것만 만들어라. 추측성 기능 금지.
- 단일 사용 코드에 추상화 금지.
- 요청하지 않은 유연성·설정 가능성 금지.
- 불가능한 시나리오에 대한 에러 핸들링 금지.
- 200줄로 쓴 게 50줄로 가능하면 다시 써라.

**3. 외과적 변경**
- 반드시 필요한 것만 건드려라. 인접 코드·주석·포맷 개선 금지.
- 멀쩡한 코드 리팩토링 금지. 기존 스타일에 맞춰라.
- 내 변경으로 생긴 고아(미사용 import/변수/함수)는 제거. 기존 dead code는 언급만 하고 건드리지 마라.
- 변경된 모든 줄은 사용자 요청으로 추적 가능해야 한다.

**4. 목표 기반 실행**
- 작업을 검증 가능한 목표로 변환해라.
  - "버그 수정" → "버그를 재현하는 테스트 작성 → 통과시키기"
  - "기능 추가" → "실패하는 테스트 작성 → 통과시키기"
- 여러 단계 작업은 계획을 먼저 명시해라: `[단계] → 검증: [확인 방법]`

### 프로젝트 금지 사항
- `output/` 파일을 직접 수동 편집하지 마라 — 스크립트/에이전트가 생성하는 산출물이다.
- `run_log.json`을 덮어쓰지 마라 — append-only 이력 파일이다.
- GitHub Actions secrets를 코드에 하드코딩하지 마라.

---

## 아키텍처 (Architecture)

### 기술 스택
- Runtime: Python 3.11
- Scheduler: GitHub Actions cron (`.github/workflows/daily_agent.yml`)
- Todoist API: REST v2 (`TODOIST_API_KEY`)
- Notion API: REST (`NOTION_TOKEN`, `NOTION_DATABASE_ID`)
- Google Calendar API: REST (`GCAL_CLIENT_ID`, `GCAL_CLIENT_SECRET`, `GCAL_TOKEN_JSON` — OAuth2, token.json base64 인코딩)
- LLM: Gemini `gemini-2.0-flash` (`GEMINI_API_KEY`) — Free tier (1,500회/일 무료), 매일 2회 실행으로 Rate limit 무관
- Discord: Incoming Webhook (`DISCORD_WEBHOOK_URL`)

### 폴더 구조
```
/
├── main.py                                          # 진입점 — 모닝/나이트 모드 오케스트레이터 (--mode morning|night)
├── requirements.txt
├── CLAUDE.md
├── .claude/skills/
│   ├── todoist-reader/
│   │   ├── SKILL.md
│   │   └── scripts/
│   │       ├── fetch_todoist_tasks.py               # Step 1a: Todoist 오늘 태스크 (id 포함)
│   │       └── fetch_todoist_completed.py           # Step N2: 아침 계획 vs active 비교로 완료 역산
│   ├── gcal-reader/
│   │   ├── SKILL.md
│   │   └── scripts/
│   │       └── fetch_gcal_events.py                 # Step 1b: Google Calendar 오늘 일정
│   ├── notion-writer/
│   │   ├── SKILL.md
│   │   └── scripts/
│   │       ├── write_notion_morning.py              # Step 5: Notion Morning 섹션 채우기
│   │       └── write_notion_night.py                # Step N5: Notion AI 저녁 제언 섹션 삽입
│   ├── briefing-generator/
│   │   ├── SKILL.md
│   │   └── references/message_format_guide.md       # Step 3, 4: LLM 프롬프트 지침
│   └── discord-sender/
│       ├── SKILL.md
│       └── scripts/send_discord_message.py          # Step 6/N6: Discord POST (--file 인자 지원)
├── output/
│   ├── todoist_raw.json         # Step 1a 산출물
│   ├── todoist_completed.json   # Step N2 산출물 (나이트 모드)
│   ├── gcal_raw.json            # Step 1b 산출물
│   ├── merged_context.json      # Step 2 산출물
│   ├── briefing_draft.md        # Step 3 산출물 (모닝 브리핑)
│   ├── night_draft.md           # Step N4 산출물 (나이트 결산)
│   └── run_log.json             # 실행 이력 (append-only, mode 필드 포함)
└── .github/workflows/daily_agent.yml
```

### 에이전트 구조

**단일 오케스트레이터** — `main.py --mode morning|night` 으로 모드를 분기한다. GitHub Actions가 UTC 시각으로 모드를 자동 판별해 전달한다.

#### 모닝 모드 (JST 07:30 목표, UTC 22:30 실행)

| 단계 | 처리 방식 | 스킬 |
|------|-----------|------|
| Step 1a — Todoist 오늘 태스크 수집 | Python 스크립트 | `todoist-reader` |
| Step 1b — Google Calendar 오늘 일정 수집 | Python 스크립트 | `gcal-reader` |
| Step 2 — 2소스 병합 | Python 스크립트 | (inline in main.py) |
| Step 3 — 규칙 기반 브리핑 포맷 빌드 | Python 스크립트 | (inline in main.py) |
| Step 4 — LLM ★ 판단 + 한 줄 코멘트 생성 | LLM (Gemini) | (inline in main.py) |
| Step 5 — Notion Morning 섹션 채우기 | Python 스크립트 | `notion-writer` |
| Step 6 — Discord 모닝 브리핑 발송 | Python 스크립트 | `discord-sender` |

#### 나이트 모드 (JST 20:30 목표, UTC 11:30 실행)

| 단계 | 처리 방식 | 스킬 |
|------|-----------|------|
| Step N1 — 아침 merged_context.json 로드 | 파일 읽기 | (재수집 없음, API 비용 0) |
| Step N2 — Todoist 완료 태스크 역산 | Python 스크립트 | `todoist-reader` |
| Step N3 — 미완료 / 장기 지연(7일+) 분류 | Python 스크립트 | (inline in main.py) |
| Step N4 — LLM 제언 + 코멘트 생성 | LLM (Gemini) | (inline in main.py) |
| Step N5 — Notion AI 저녁 제언 섹션 삽입 | Python 스크립트 | `notion-writer` |
| Step N6 — Discord 나이트 결산 발송 | Python 스크립트 | `discord-sender` |

### 단계 간 데이터 흐름

#### 모닝 모드
| 전달 | 방식 | 경로 |
|------|------|------|
| Step 1a → Step 2 | 파일 | `output/todoist_raw.json` |
| Step 1b → Step 2 | 파일 | `output/gcal_raw.json` |
| Step 2 → Step 3 | 파일 | `output/merged_context.json` |
| Step 3/4 → Step 5 | 파일 | `output/briefing_draft.md` |
| Step 5 → Step 6 | 파일 | `output/briefing_draft.md` (동일 파일) |

#### 나이트 모드
| 전달 | 방식 | 경로 |
|------|------|------|
| Step N1 (아침 계획 재사용) | 파일 | `output/merged_context.json` |
| Step N2 → Step N3 | 파일 | `output/todoist_completed.json` |
| Step N4 → Step N5 | 파일 | `output/night_draft.md` |
| Step N5 → Step N6 | 파일 | `output/night_draft.md` (동일 파일) |

---

## 도메인 컨텍스트 (Domain Context)

### 용어 정의

| 용어 | 정의 |
|------|------|
| **Todoist 태스크** | 오늘 due date가 설정된 Todoist 항목. priority 1~4 포함 |
| **GCal 일정** | 오늘 날짜의 Google Calendar 이벤트. 시작·종료 시간 및 제목 포함 |
| **브리핑 메시지** | LLM이 2소스를 통합해 생성한 Discord 메시지 (2단 구조, Discord markdown, ≤500자) |
| **★ 태스크** | LLM이 오늘 집중해야 할 태스크에 부여하는 표시. p1 무조건, 오늘 due p2도 해당 |
| **Morning 섹션** | Notion 일지 페이지의 Top Priorities 3 + Brain Dump 영역 — LLM이 자동 채움 |
| **Night 섹션** | Notion 일지 페이지의 성찰과 감사 영역 — 사람이 직접 작성, 시스템이 절대 건드리지 않음 |
| **AI 저녁 제언 섹션** | Notion 일지 페이지의 Night 헤딩 직전에 자동 삽입 — 완료 요약 + 미완료 제언 + 장기 지연 제언 |

### 모닝 브리핑 포맷 원칙

Python 규칙 기반으로 섹션을 빌드하고, LLM은 ★ 판단 + 한 줄 코멘트만 담당한다:

```
──────────────────────────
브리핑 · MM/DD 요일
──────────────────────────

💼 일정 (업무)          ← 평일만, GCal 업무 이벤트
  HH:MM~HH:MM  이벤트명

🌙 일정 (개인)          ← GCal 개인 이벤트
  HH:MM~HH:MM  이벤트명

💼 업무                 ← root_project = 業務リスト
  태스크명  ★           ← p1 또는 오늘 due p2에 LLM이 ★ 부여

📚 자기계발             ← root_project = 자기계발
  태스크명

📦 백로그               ← root_project = 간단일 리스트 (항목 있을 때만)
  태스크A · 태스크B

──────────────────────────
"LLM 한 줄 코멘트 (30자 이내, 이모지 1개)"
──────────────────────────
```

**★ 판단 기준 (LLM)**:
- p1은 무조건 ★
- p2 중 due_date가 오늘인 경우 ★
- 업무/자기계발 각각 독립 판단

### 나이트 결산 포맷 원칙

```
──────────────────────────
결산 · MM/DD 요일
──────────────────────────

📊 완료 / 계획 (완료율%)
   완료: 태스크A, 태스크B 외 N건

⏳ 내일 이어서           ← 오늘 미완료 태스크 + LLM 제언
  • 태스크명 → 제언 (15자 이내)

🗂️ 오래 미뤄온 것 (7일+) ← due_date 7일 이상 경과 + LLM 제언
  • 태스크명 (N일째) → 제언

──────────────────────────
"LLM 한 줄 코멘트 (20자 이내, 이모지 1개)"
──────────────────────────
```

### Notion Write 원칙

| 상황 | 동작 |
|------|------|
| 오늘 페이지 없음 | 템플릿 구조로 신규 생성 (Morning + Night 섹션 포함) |
| Morning 비어있음 | 브리핑 전문(규칙 기반 포맷 + LLM ★/코멘트) 그대로 삽입 |
| Morning 내용 있음 | 구분선 + `🤖 LLM 제안` 헤딩 후 append |
| AI 저녁 제언 없음 | Night 헤딩 직전에 신규 삽입 |
| AI 저녁 제언 있음 | 구분선 + `🤖 AI 저녁 제언 (재생성)` 으로 append |
| Night 섹션 (감사/성찰) | **절대 건드리지 않음** |
| Notion Write 실패 | skip + 로그, Discord 발송은 계속 진행 |

### 분기 처리

| 상황 | 처리 |
|------|------|
| Todoist API 실패 | skip + 로그 기록, GCal만으로 계속 진행 |
| GCal API 실패 | skip + 로그 기록, Todoist만으로 계속 진행 |
| 2소스 모두 비어있음 | 빈 브리핑 메시지 Discord 발송 |
| LLM 검증 실패 | Step 3 재시도 최대 2회 → 초과 시 `merged_context.json` 원문 그대로 발송 |
| Notion Write 실패 | skip + 로그, Discord 발송은 계속 진행 |
| Discord 발송 실패 | 자동 재시도 2회 → 실패 시 에러 로그 + 에스컬레이션 |

### 산출물 스키마

**`output/todoist_raw.json`** (Step 1a — 모닝)
```json
{
  "date": "YYYY-MM-DD",
  "tasks": [
    { "id": "12345678", "text": "할일 내용", "priority": 1, "due_date": "YYYY-MM-DD", "due_time": "09:00", "project_name": "프로젝트", "root_project_name": "業務リスト" }
  ]
}
```

**`output/todoist_completed.json`** (Step N2 — 나이트, 아침 계획 중 완료된 것)
```json
{
  "date": "YYYY-MM-DD",
  "tasks": [
    { "id": "12345678", "text": "완료된 할일", "priority": 1, "due_date": "YYYY-MM-DD", "due_time": "", "project_name": "프로젝트", "root_project_name": "業務リスト" }
  ]
}
```

**`output/gcal_raw.json`** (Step 1b — 모닝)
```json
{
  "date": "YYYY-MM-DD",
  "events": [
    { "title": "이벤트 제목", "start": "10:00", "end": "11:00" }
  ]
}
```

**`output/merged_context.json`** (Step 2 병합 산출물 — 나이트 모드에서 재사용)
```json
{
  "date": "YYYY-MM-DD",
  "todoist": [
    { "id": "12345678", "text": "할일 내용", "priority": 1, "due_date": "YYYY-MM-DD", "due_time": "09:00", "root_project_name": "業務リスト" }
  ],
  "gcal_events": [
    { "title": "이벤트 제목", "start": "10:00", "end": "11:00" }
  ]
}
```

**`output/run_log.json`** (실행마다 append — 패턴 분석용)
```json
{
  "timestamp": "ISO8601+09:00",
  "mode": "morning | night",
  "status": "success | skipped | failed",
  "reason": "all_sources_empty | discord_error | notion_write_error | ...",
  "llm_model": "gemini-2.0-flash",

  // 모닝 모드 전용 필드
  "sources_collected": ["todoist", "gcal"],
  "sources_skipped": [],
  "todo_count": 5,
  "event_count": 2,
  "starred_items": ["태스크 A"],
  "notion_write_status": "success | skipped | appended",

  // 나이트 모드 전용 필드
  "completed_count": 8,
  "incomplete_count": 4,
  "long_delayed_count": 2,
  "comment": "LLM 코멘트"
}
```

---

## 빌드/테스트 (Build & Run)

```bash
# 의존성 설치
pip install -r requirements.txt

# 모닝 모드 수동 실행
python main.py --mode morning

# 나이트 모드 수동 실행 (아침 실행 후 merged_context.json 있어야 함)
python main.py --mode night

# GitHub Actions 수동 트리거 (Determine Mode 스텝이 현재 UTC 시각으로 모드 자동 판별)
# Actions 탭 → "Daily Briefing Agent" → Run workflow
```

로컬 실행 시 환경 변수 설정 (`.env` 또는 export):
```bash
export TODOIST_API_KEY=...
export NOTION_TOKEN=...
export NOTION_DATABASE_ID=...
export GCAL_CLIENT_ID=...
export GCAL_CLIENT_SECRET=...
export GCAL_TOKEN_JSON=...         # base64 인코딩된 token.json (gcal_auth.py로 생성)
export GEMINI_API_KEY=...
export DISCORD_WEBHOOK_URL=...
```

---

## 코딩 컨벤션 (Coding Conventions)

### 네이밍
- 파일명: `snake_case.py`
- 함수명: `동사_목적어` 형태 (예: `fetch_todoist_tasks`, `fetch_gcal_events`, `write_notion_morning`)
- 상수: `UPPER_SNAKE_CASE`

### 스크립트 패턴
- 각 스크립트는 단일 책임: 입력받아 처리하고 `output/` 에 결과 저장 또는 stdout 반환
- 스크립트 실패 시 종료 코드로 신호: `0` = 성공, `1` = 오류, `2` = 데이터 없음(스킵)
- API 호출은 재시도 로직 포함 (최대 횟수는 각 단계 스펙 참고)
- 소스별 실패는 전체 실행을 중단시키지 않는다 — 로그 후 계속 진행

### 커밋
- 형식: `type: 한국어 설명` (예: `feat: Notion Morning 섹션 자동 채우기 스크립트 추가`)
- type: `feat` / `fix` / `refactor` / `chore` / `docs`

---

## 결정 사항 (Resolved Decisions)

| 항목 | 결정 |
|------|------|
| Notion 역할 | 출력 대상 — Morning 섹션 자동 채움 (이월 소스 역할 제거) |
| Notion 쓰기 범위 | Morning 섹션 (모닝 모드) + AI 저녁 제언 섹션 (나이트 모드). Night 감사/성찰 섹션 절대 건드리지 않음 |
| Notion 쓰기 방식 | 텍스트 블록 (to_do 체크박스 아님) — 기록/참조 목적 |
| Notion Morning 내용 있을 때 | append — 구분선 + `🤖 LLM 제안` 헤딩으로 구분 |
| 이월 개념 | 제거 — Todoist가 이미 미완료 태스크 이월 관리 |
| Todoist 수집 범위 | 오늘 due date인 태스크 전체 (완료 제외) |
| GCal 인증 방식 | OAuth2 — `GCAL_CLIENT_ID` + `GCAL_CLIENT_SECRET` + `GCAL_TOKEN_JSON` (token.json base64) |
| GCal 수집 범위 | 오늘 00:00~23:59 JST 이벤트 전체 |
| LLM | Gemini `gemini-2.0-flash` (`google-genai` SDK) — Free tier (1,500회/일 무료) |
| 브리핑 메시지 구조 | 규칙 기반 (💼 업무 / 📚 자기계발 / 📦 백로그) + LLM ★ 판단 + 한 줄 코멘트 |
| 빈 상태 처리 | 2소스 모두 비어있어도 빈 브리핑 메시지 Discord 발송 |
| 소스 부분 실패 처리 | 개별 소스 실패는 skip 처리, 나머지 소스로 브리핑 생성 |
| 발송 채널 | Discord Incoming Webhook (`DISCORD_WEBHOOK_URL`) — 개인 서버 |
| 실행 환경 | GitHub Actions cron 2회 — `30 22 * * *` UTC (= JST 07:30 모닝), `30 11 * * *` UTC (= JST 20:30 나이트) |
| 모드 판별 | UTC 시각이 22 이상이면 morning, 그 외 night (Determine Mode 스텝) |
| 날짜 기준 | 모든 `date.today()` → `datetime.now(JST).date()` — UTC 기준 날짜 버그 방지 |
| 완료 태스크 수집 | 별도 API 불필요 — 아침 todoist_raw.json과 현재 active 태스크 ID 비교로 역산 |
| 장기 지연 기준 | due_date가 오늘 기준 7일 이상 경과한 태스크 (`LONG_DELAY_THRESHOLD_DAYS = 7`) |
| pip 캐시 | `actions/cache@v4` — requirements.txt 해시 기반, 반복 실행 시 설치 시간 단축 |
| 저장소 이름 | `daily-productivity-master` |
