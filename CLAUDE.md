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
- LLM: Gemini `gemini-2.5-flash` (`GEMINI_API_KEY`) — Free tier, 매일 1회 실행으로 Rate limit 무관
- Discord: Incoming Webhook (`DISCORD_WEBHOOK_URL`)

### 폴더 구조
```
/
├── main.py                                          # 진입점 — 6단계 오케스트레이터
├── requirements.txt
├── CLAUDE.md
├── .claude/skills/
│   ├── todoist-reader/
│   │   ├── SKILL.md
│   │   └── scripts/
│   │       └── fetch_todoist_tasks.py               # Step 1a: Todoist 오늘 태스크
│   ├── gcal-reader/
│   │   ├── SKILL.md
│   │   └── scripts/
│   │       └── fetch_gcal_events.py                 # Step 1b: Google Calendar 오늘 일정
│   ├── notion-writer/                               # Step 5: Notion Morning 섹션 채우기
│   │   ├── SKILL.md
│   │   └── scripts/
│   │       └── write_notion_morning.py
│   ├── briefing-generator/
│   │   ├── SKILL.md
│   │   └── references/message_format_guide.md       # Step 3, 4: LLM 프롬프트 지침
│   └── discord-sender/
│       ├── SKILL.md
│       └── scripts/send_discord_message.py          # Step 6: Discord POST
├── output/
│   ├── todoist_raw.json         # Step 1a 산출물
│   ├── gcal_raw.json            # Step 1b 산출물
│   ├── merged_context.json      # Step 2 산출물
│   ├── briefing_draft.md        # Step 3 산출물
│   └── run_log.json             # 실행 이력 (append-only)
└── .github/workflows/daily_agent.yml
```

### 에이전트 구조

**단일 오케스트레이터** — `main.py`가 6단계를 순서대로 실행한다. Step 1의 2개 수집 스크립트는 독립적이므로 병렬 실행 가능하나, 초기 구현은 순차로 한다.

| 단계 | 처리 방식 | 스킬 |
|------|-----------|------|
| Step 1a — Todoist 태스크 수집 | Python 스크립트 | `todoist-reader` |
| Step 1b — Google Calendar 오늘 일정 수집 | Python 스크립트 | `gcal-reader` |
| Step 2 — 2소스 병합 | Python 스크립트 | (inline in main.py) |
| Step 3 — LLM 브리핑 생성 | LLM 판단 | `briefing-generator` |
| Step 4 — LLM 자기 검증 | LLM 판단 | `briefing-generator` |
| Step 5 — Notion Write | Python 스크립트 | `notion-writer` |
| Step 6 — Discord 발송 | Python 스크립트 | `discord-sender` |

### 단계 간 데이터 흐름

| 전달 | 방식 | 경로 |
|------|------|------|
| Step 1a → Step 2 | 파일 | `output/todoist_raw.json` |
| Step 1b → Step 2 | 파일 | `output/gcal_raw.json` |
| Step 2 → Step 3 | 파일 | `output/merged_context.json` |
| Step 3 → Step 4 | 인라인 프롬프트 | (메시지가 짧으므로 인라인) |
| Step 4 → Step 5 | 파일 | `output/briefing_draft.md` |
| Step 5 → Step 6 | 파일 | `output/briefing_draft.md` (동일 파일) |

---

## 도메인 컨텍스트 (Domain Context)

### 용어 정의

| 용어 | 정의 |
|------|------|
| **Todoist 태스크** | 오늘 due date가 설정된 Todoist 항목. priority 1~4 포함 |
| **GCal 일정** | 오늘 날짜의 Google Calendar 이벤트. 시작·종료 시간 및 제목 포함 |
| **브리핑 메시지** | LLM이 2소스를 통합해 생성한 Discord 메시지 (2단 구조, Discord markdown, ≤500자) |
| **Top 3** | LLM이 Todoist + GCal 기반으로 도출한 오늘의 집중 태스크 3개 (GCal 시간 인접성 기준) |
| **Morning 섹션** | Notion 일지 페이지의 Top Priorities 3 + Brain Dump 영역 — LLM이 자동 채움 |
| **Night 섹션** | Notion 일지 페이지의 성찰과 감사 영역 — 사람이 직접 작성, 시스템이 절대 건드리지 않음 |

### 브리핑 메시지 포맷 원칙

LLM은 `merged_context.json`을 입력받아 **2단 구조**로 브리핑을 생성한다:

```
🌅 오늘의 브리핑 (MM/DD 요일)

⭐ 오늘의 Top 3
• GCal 일정 컨텍스트 → 태스크 (Todoist p1)
• ...

📋 기타
• Top 3에 포함되지 않은 나머지 Todoist 태스크

💬 한 줄 코멘트
```

**Top 3 도출 기준 (LLM 판단)**:
1. GCal 일정이 있는 시간대와 **시간적으로 인접한** Todoist 태스크를 우선 배치
2. 동일 시간대에 여러 태스크가 있으면 Todoist 우선순위(p1 > p2 > ...) 적용
3. GCal 일정이 없는 경우 Todoist p1 → p2 → p3 순서로 Top 3 선정

**기타 원칙**:
- 기타 섹션은 항목이 있을 때만 표시
- **분량**: 500자 이하, Discord markdown 사용

### Notion Write 원칙

| 상황 | 동작 |
|------|------|
| 오늘 페이지 없음 | 템플릿 구조로 신규 생성 (Morning + Night 섹션 포함) |
| Morning 비어있음 | Top Priorities = LLM Top 3, Brain Dump = 나머지 Todoist |
| Morning 내용 있음 | 구분선 + `🤖 LLM 제안` 헤딩 후 append |
| Night 섹션 | **절대 건드리지 않음** |
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

**`output/todoist_raw.json`**
```json
{
  "date": "YYYY-MM-DD",
  "tasks": [
    { "text": "할일 내용", "priority": 1, "due_time": "09:00" }
  ]
}
```

**`output/gcal_raw.json`**
```json
{
  "date": "YYYY-MM-DD",
  "events": [
    { "title": "이벤트 제목", "start": "10:00", "end": "11:00" }
  ]
}
```

**`output/merged_context.json`** (Step 2 병합 산출물)
```json
{
  "date": "YYYY-MM-DD",
  "todoist": [
    { "text": "할일 내용", "priority": 1, "due_time": "09:00" }
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
  "status": "success | skipped | failed",
  "reason": "all_sources_empty | llm_retry_exceeded | discord_error | notion_write_error | ...",
  "sources_collected": ["todoist", "gcal"],
  "sources_skipped": [],
  "todo_count": 5,
  "event_count": 2,
  "notion_write_status": "success | skipped | appended",
  "top3_items": ["태스크 A", "태스크 B", "태스크 C"],
  "retry_count": 0,
  "llm_model": "gemini-2.5-flash"
}
```

---

## 빌드/테스트 (Build & Run)

```bash
# 의존성 설치
pip install -r requirements.txt

# 에이전트 수동 실행
python main.py

# GitHub Actions 수동 트리거
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
| Notion 쓰기 범위 | Morning 섹션만 (Top Priorities 3 + Brain Dump). Night 섹션 절대 건드리지 않음 |
| Notion 쓰기 방식 | 텍스트 블록 (to_do 체크박스 아님) — 기록/참조 목적 |
| Notion Morning 내용 있을 때 | append — 구분선 + `🤖 LLM 제안` 헤딩으로 구분 |
| 이월 개념 | 제거 — Todoist가 이미 미완료 태스크 이월 관리 |
| Todoist 수집 범위 | 오늘 due date인 태스크 전체 (완료 제외) |
| GCal 인증 방식 | OAuth2 — `GCAL_CLIENT_ID` + `GCAL_CLIENT_SECRET` + `GCAL_TOKEN_JSON` (token.json base64) |
| GCal 수집 범위 | 오늘 00:00~23:59 JST 이벤트 전체 |
| LLM | Gemini `gemini-2.5-flash` (`google-genai` SDK) — Free tier |
| Top 3 도출 | LLM이 GCal 시간 인접성 기준으로 Todoist 태스크에서 자동 선정 |
| 브리핑 메시지 구조 | ⭐ Top 3 → 📋 기타 2단 구조 |
| 빈 상태 처리 | 2소스 모두 비어있어도 빈 브리핑 메시지 Discord 발송 |
| 소스 부분 실패 처리 | 개별 소스 실패는 skip 처리, 나머지 소스로 브리핑 생성 |
| 발송 채널 | Discord Incoming Webhook (`DISCORD_WEBHOOK_URL`) — 개인 서버 |
| 실행 환경 | GitHub Actions cron — `0 23 * * *` UTC (= 08:00 JST) |
| 저장소 이름 | `daily-productivity-master` |
