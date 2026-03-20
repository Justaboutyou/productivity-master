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
- Notion API: REST (`NOTION_TOKEN`, `NOTION_DATABASE_ID`)
- LLM: Gemini (`GEMINI_API_KEY`)
- Slack: Incoming Webhook (`SLACK_WEBHOOK_URL`)

### 폴더 구조
```
/
├── main.py                                    # 진입점 — 5단계 오케스트레이터
├── requirements.txt
├── CLAUDE.md
├── .claude/skills/
│   ├── notion-reader/
│   │   ├── SKILL.md
│   │   └── scripts/
│   │       ├── fetch_yesterday_page.py        # Step 1: Notion DB 쿼리
│   │       └── extract_todo_blocks.py         # Step 2: 할일 블록 추출
│   ├── briefing-generator/
│   │   ├── SKILL.md
│   │   └── references/message_format_guide.md # Step 3, 4: LLM 프롬프트 지침
│   └── slack-sender/
│       ├── SKILL.md
│       └── scripts/send_slack_message.py      # Step 5: Slack POST
├── output/
│   ├── todo_raw.json        # Step 2 산출물 (스크립트 생성)
│   ├── briefing_draft.md    # Step 3 산출물 (LLM 생성)
│   └── run_log.json         # 실행 이력 (append-only)
└── .github/workflows/daily_agent.yml
```

### 에이전트 구조

**단일 오케스트레이터** — `main.py`가 5단계를 순서대로 실행한다. 단계가 순차적이고 컨텍스트 전달량이 적어 서브에이전트 분리 불필요.

| 단계 | 처리 방식 | 스킬 |
|------|-----------|------|
| Step 1 — Notion 페이지 조회 | Python 스크립트 | `notion-reader` |
| Step 2 — 할일 블록 추출 | Python 스크립트 | `notion-reader` |
| Step 3 — LLM 브리핑 생성 | LLM 판단 | `briefing-generator` |
| Step 4 — LLM 자기 검증 | LLM 판단 | `briefing-generator` |
| Step 5 — Slack 발송 | Python 스크립트 | `slack-sender` |

### 단계 간 데이터 흐름

| 전달 | 방식 | 경로 |
|------|------|------|
| Step 2 → Step 3 | 파일 | `output/todo_raw.json` |
| Step 3 → Step 4 | 인라인 프롬프트 | (메시지가 짧으므로 인라인) |
| Step 4 → Step 5 | 파일 | `output/briefing_draft.md` |

---

## 도메인 컨텍스트 (Domain Context)

### 용어 정의

| 용어 | 정의 |
|------|------|
| **일지 페이지** | 날짜가 제목에 포함된 Notion 데이터베이스 항목 |
| **할일 블록** | Notion `to_do` 타입 블록 또는 지정 헤딩 하위 블록 |
| **브리핑 메시지** | LLM이 생성한 우선순위 정렬 + 코멘트 포함 Slack 메시지 (mrkdwn 형식, ≤500자) |

### 분기 처리

| 상황 | 처리 |
|------|------|
| Notion 페이지 없음 | skip + 로그 기록 후 종료 |
| 할일 블록 비어있음 | 미결 사항 — 빈 브리핑 발송 or 스킵 (구현 전 결정 필요) |
| LLM 검증 실패 | Step 3 재시도 최대 2회 → 초과 시 원본 할일 목록 그대로 발송 |
| Slack 발송 실패 | 자동 재시도 2회 → 실패 시 에러 로그 + 에스컬레이션 |

### 산출물 스키마

**`output/todo_raw.json`**
```json
{
  "date": "YYYY-MM-DD",
  "page_id": "xxxx-xxxx-xxxx",
  "todos": [
    { "text": "할일 내용", "checked": false }
  ]
}
```

**`output/run_log.json`** (실행마다 append)
```json
{
  "timestamp": "ISO8601+09:00",
  "status": "success | skipped | failed",
  "reason": "page_not_found | todo_empty | slack_error | ...",
  "todo_count": 5,
  "retry_count": 0
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
# Actions 탭 → "Daily Retrospective Agent" → Run workflow
```

로컬 실행 시 환경 변수 설정 (`.env` 또는 export):
```bash
export NOTION_TOKEN=...
export NOTION_DATABASE_ID=...
export GEMINI_API_KEY=...
export SLACK_WEBHOOK_URL=...
```

---

## 코딩 컨벤션 (Coding Conventions)

### 네이밍
- 파일명: `snake_case.py`
- 함수명: `동사_목적어` 형태 (예: `fetch_yesterday_page`, `extract_todo_blocks`, `send_slack_message`)
- 상수: `UPPER_SNAKE_CASE`

### 스크립트 패턴
- 각 스크립트는 단일 책임: 입력받아 처리하고 `output/` 에 결과 저장 또는 stdout 반환
- 스크립트 실패 시 종료 코드로 신호: `0` = 성공, `1` = 오류, `2` = 데이터 없음(스킵)
- API 호출은 재시도 로직 포함 (최대 횟수는 각 단계 스펙 참고)

### 커밋
- 형식: `type: 한국어 설명` (예: `feat: Notion 페이지 조회 스크립트 추가`)
- type: `feat` / `fix` / `refactor` / `chore` / `docs`

---

## 결정 사항 (Resolved Decisions)

| 항목 | 결정 |
|------|------|
| Notion 날짜 저장 방식 | 페이지 제목에 날짜 포함 (title contains 필터로 조회) |
| 할일 섹션 헤딩 | `"Top Priorities 3"` (→ `top_priorities`), `"Brain dump"` (→ `brain_dump`) |
| LLM | Gemini `gemini-2.5-flash` (`google-genai` SDK) |
| 빈 상태 처리 | 일지 없음 / 할일 없음 모두 빈 브리핑 메시지 Slack 발송 |
| Slack 발송 방식 | Incoming Webhook (`SLACK_WEBHOOK_URL`) |
| 실행 환경 | GitHub Actions cron (`.github/workflows/daily_agent.yml`) |
