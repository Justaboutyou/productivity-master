# 에이전트 시스템 설계서
## 개인 생산성 모닝 브리핑 자동화

**버전**: v3.0
**작성일**: 2026-03-22
**용도**: Claude Code 구현 참조용 계획서
**이전 버전**: v2.0 — Notion 이월 소스 포함, 3소스 병합, Discord 발송

---

## 변경 이력

| 버전 | 주요 변경 |
|------|-----------|
| v1.0 | Notion 단일 소스, Slack 발송, 5단계 워크플로우 |
| v2.0 | Todoist + Notion(이월) + GCal 3소스, Discord 발송 |
| v3.0 | Notion → 출력 대상으로 역할 역전, Morning 섹션 자동 채움, 이월 개념 제거 |

---

## 1. 작업 컨텍스트

### 배경 및 목적

매일 아침 Todoist 오늘 태스크와 Google Calendar 오늘 일정을 통합해 **Notion 일지 Morning 섹션을 자동으로 채우고**, Discord 개인 서버에 브리핑 메시지를 발송한다. 아침 기상 후 무엇부터 해야 할지 판단하는 인지 부하를 줄이는 것이 목적이며, 브리핑은 **기억력 보조 도구**다 — 새로운 정보를 제공하는 것이 아니라 이미 알고 있는 것을 정리해주는 역할이다.

### v3.0 핵심 변경 요약

| 항목 | 변경 전 (v2.0) | 변경 후 (v3.0) |
|------|---------------|---------------|
| Notion 역할 | 수동 작성 → 이월 소스 | LLM이 Morning 섹션 자동 채움 (출력 대상) |
| 소스 수 | 3소스 (Todoist + Notion + GCal) | 2소스 (Todoist + GCal) |
| Step 1b | Notion 이월 수집 | **제거** |
| Step 5 | Discord 발송 | **Notion Write** (신규) |
| Step 6 | 없음 | **Discord 발송** (기존 Step 5) |
| 이월 항목 섹션 | `⚠️ 어제 이월` 존재 | **제거** (Todoist가 이미 관리) |
| Brain Dump | 수동 작성 | LLM이 나머지 Todoist 태스크로 자동 채움 |

### 프로젝트 성격

- **완전한 개인 도구** — 단일 사용자, 개인 Discord 서버로 발송
- **점진적 개발** — 프로토타입에서 시작해 생산성 툴 최적화 방향으로 발전 중
- **실험적 플랫폼** — 다양한 API 연동 학습 및 개인 워크플로우 자동화 탐구

### 소비 패턴 (설계 원칙 도출 기준)

| 항목 | 내용 |
|------|------|
| **수신 방법** | 기상 알람 후 Discord 알림으로 모바일 확인 |
| **읽는 방식** | 한 번 읽고 실행 — 이후 재참조 없음 |
| **기기** | 모바일 우선 (침대에서 폰으로 확인) |
| **이상형 메시지** | 스크롤 없이 한 화면에 들어오는 밀도 |

→ **500자 이내, 다중 섹션 구분이 있는 포맷이 최적**

---

## 2. 핵심 설계 결정

| 항목 | 결정 | 이유 |
|------|------|------|
| **발송 채널** | Discord Incoming Webhook (개인 서버) | 개인 도구, Slack 대비 비용/편의성 우위 |
| **LLM** | Gemini `gemini-2.5-flash` | Free tier로 GitHub Actions 무료 운영 (매일 1회 = Rate limit 무관) |
| **실행 환경** | GitHub Actions cron | 서버리스, 비용 0 |
| **실행 시간** | 08:00 JST = UTC `23:00 (전날)` | 기상 후 첫 확인 타이밍 |
| **Notion 역할** | 출력 대상 — Morning 섹션 자동 채움 | 수동 작성 부담 제거, LLM이 Todoist+GCal에서 자동 도출 |
| **Notion 쓰기 범위** | Morning 섹션만 (Top Priorities 3 + Brain Dump) | Night 성찰 섹션은 사람이 직접 작성하는 영역 |
| **Notion 쓰기 방식** | 텍스트 블록 (체크박스 아님) | 기록/참조 목적, 완료 체크는 Todoist에서 |
| **Notion 덮어쓰기 정책** | 비어있으면 채움, 내용 있으면 append | 직접 쓴 내용 보존 + LLM 제안 구분선으로 구분 |
| **이월 개념** | 제거 | Todoist가 이미 미완료 태스크 이월 관리 |
| **Top 3 도출 기준** | GCal 일정 시간대 전후 인접 태스크 우선 | 캘린더 기준으로 하루를 구조화하는 것이 가장 실용적 |
| **브리핑 메시지 구조** | ⭐ Top 3 → 📋 기타 2단 구조 | 이월 섹션 제거로 단순화 |
| **run_log 설계** | 패턴 분석을 위한 충분한 필드 포함 | 나중에 패턴 분석 가능하도록 |

---

## 3. 워크플로우

### 전체 흐름

```
[GitHub Actions cron — 08:00 JST = UTC 23:00 (전날)]

   ┌──────────────┐
   ▼              ▼
Step 1a        Step 1b
Todoist        GCal
수집           수집
   │              │
   └──────┬───────┘
          ▼
       Step 2
     2소스 병합
  (merged_context.json)
          │
          ▼
       Step 3
  LLM 브리핑 생성
  (Top 3 도출 포함)
          │
          ▼
       Step 4
  LLM 자기검증
          │
    검증 통과?
    ├── NO (≤2회) → Step 3 재시도
    └── YES (또는 2회 초과 → 원문 발송)
          │
          ▼
       Step 5  ← NEW
  Notion Write
  (Morning 섹션 채움)
          │
          ▼
       Step 6
   Discord 발송
```

### 단계별 상세

#### Step 1a: Todoist 오늘 태스크 수집

| 항목 | 내용 |
|------|------|
| **처리 방식** | Python 스크립트 |
| **동작** | 오늘 due date인 미완료 태스크 전체 조회 (p1~p4 포함) |
| **성공 기준** | 태스크 배열 반환 (빈 배열도 성공) |
| **실패 시** | skip + 로그 기록, 나머지 소스로 계속 진행 |
| **출력** | `output/todoist_raw.json` |

#### Step 1b: Google Calendar 오늘 일정 수집

| 항목 | 내용 |
|------|------|
| **처리 방식** | Python 스크립트 |
| **동작** | 오늘 00:00~23:59 JST 이벤트 전체 조회 |
| **인증** | Service Account JSON (base64) — `GCAL_CREDENTIALS_JSON` |
| **실패 시** | skip + 로그 기록, 나머지 소스로 계속 진행 |
| **출력** | `output/gcal_raw.json` |

#### Step 2: 2소스 병합

| 항목 | 내용 |
|------|------|
| **처리 방식** | Python (main.py 인라인) |
| **동작** | 2소스 JSON 읽어 `merged_context.json` 생성 |
| **출력** | `output/merged_context.json` |

#### Step 3: LLM 브리핑 생성 ← LLM 판단 영역

| 항목 | 내용 |
|------|------|
| **처리 방식** | LLM (Gemini gemini-2.5-flash) |
| **핵심 동작** | GCal 시간 블록 + Todoist 우선순위 분석 → **Top 3 도출** → 2단 구조 브리핑 작성 |
| **Top 3 선정 기준** | GCal 일정이 있는 시간대와 시간적으로 인접한 태스크 우선 배치 |
| **성공 기준** | 2단 구조 준수 + 원본 항목 누락 없음 + 500자 이내 |
| **실패 시** | 자동 재시도 최대 2회 |
| **출력** | `output/briefing_draft.md` |

**브리핑 메시지 2단 구조:**
```
🌅 오늘의 브리핑 (03/22 토)

⭐ 오늘의 Top 3
• 10시 회의 전에 → 전략 자료 준비 (p1)
• 14시~16시 슬롯 → 월간 보고서 초안 (p1)
• 저녁 전 → 팀 메시지 회신 (p2)

📋 기타
• 개발 환경 업데이트 (p3)
• 문서 정리 (p4)

💬 오늘도 집중해서.
```

#### Step 4: LLM 자기검증 ← LLM 판단 영역

| 항목 | 내용 |
|------|------|
| **처리 방식** | LLM (인라인, 토큰 최소화 프롬프트) |
| **검증 항목** | ① 2단 구조 준수 ② 500자 이내 ③ 톤 적절성 |
| **실패 시** | Step 3 재시도 (최대 2회) → 초과 시 `merged_context.json` 원문 발송 |

#### Step 5: Notion Write ← NEW

| 항목 | 내용 |
|------|------|
| **처리 방식** | Python 스크립트 (`notion-writer` 스킬) |
| **대상 섹션** | Morning: **Top Priorities 3** + **Brain Dump** |
| **보존 섹션** | Night: 성찰과 감사 — **절대 건드리지 않음** |
| **쓰기 방식** | 텍스트 블록 (to_do 체크박스 아님) |
| **페이지 없음** | 오늘 날짜 신규 페이지 생성 후 템플릿 구조로 채움 |
| **Morning 비어있음** | Top Priorities 3 = LLM Top 3, Brain Dump = 나머지 Todoist |
| **Morning 내용 있음** | 구분선 + `🤖 LLM 제안` 헤딩 추가 후 append |
| **실패 시** | skip + 로그 기록, Discord 발송은 계속 진행 |

**Notion 페이지 구조 (자동 생성 시):**
```
☀️ Morning: 오늘 하루를 어떻게 보낼까요?

1️⃣ Top Priorities 3
10시 회의 전에 → 전략 자료 준비 (p1)
14시~16시 슬롯 → 월간 보고서 초안 (p1)
저녁 전 → 팀 메시지 회신 (p2)

2️⃣ Brain Dump
개발 환경 업데이트 (p3)
문서 정리 (p4)

🌙 Night: 성찰과 감사 (오늘 하루는 어땠나요?)
• 오늘 내가 잘한 것 1가지는?
• 오늘 무엇을 더 잘할 수 있었을까? (Better Me)
```

#### Step 6: Discord 발송

| 항목 | 내용 |
|------|------|
| **처리 방식** | Python 스크립트 |
| **동작** | `output/briefing_draft.md` 읽어 Discord Webhook으로 POST |
| **성공 기준** | HTTP 200 응답 |
| **실패 시** | 자동 재시도 2회 → 실패 시 에러 로그 + 에스컬레이션 |

---

## 4. 구현 스펙

### 4-1. 기술 스택

| 항목 | 내용 |
|------|------|
| **Runtime** | Python 3.11 |
| **Scheduler** | GitHub Actions cron (`0 23 * * *` UTC = 08:00 JST) |
| **Todoist API** | REST v2 (`TODOIST_API_KEY`) |
| **Notion API** | REST (`NOTION_TOKEN`, `NOTION_DATABASE_ID`) |
| **GCal API** | REST, Service Account JSON base64 (`GCAL_CREDENTIALS_JSON`) |
| **LLM** | Gemini `gemini-2.5-flash` (`google-genai` SDK, `GEMINI_API_KEY`) |
| **Discord** | Incoming Webhook (`DISCORD_WEBHOOK_URL`) |

### 4-2. 폴더 구조

```
/
├── main.py                          # 진입점 — 6단계 오케스트레이터
├── requirements.txt
├── CLAUDE.md
├── .claude/skills/
│   ├── todoist-reader/
│   │   ├── SKILL.md
│   │   └── scripts/fetch_todoist_tasks.py       # 변경 없음
│   ├── gcal-reader/
│   │   ├── SKILL.md
│   │   └── scripts/fetch_gcal_events.py         # 변경 없음
│   ├── notion-writer/                            # NEW (notion-reader 대체)
│   │   ├── SKILL.md
│   │   └── scripts/write_notion_morning.py      # Morning 섹션 채우기
│   ├── briefing-generator/
│   │   ├── SKILL.md
│   │   └── references/message_format_guide.md   # 2단 구조로 업데이트
│   └── discord-sender/
│       ├── SKILL.md
│       └── scripts/send_discord_message.py      # 변경 없음
├── output/
│   ├── todoist_raw.json
│   ├── gcal_raw.json
│   ├── merged_context.json
│   ├── briefing_draft.md
│   └── run_log.json                             # append-only
└── .github/workflows/daily_agent.yml
```

**제거되는 파일:**
- `.claude/skills/notion-reader/` (디렉토리 전체)
- `output/notion_raw.json`

### 4-3. 산출물 스키마

**`output/merged_context.json`** (v3.0 — notion_carry_over 제거)
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

**`output/run_log.json`**
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

### 4-4. 분기 처리

| 상황 | 처리 |
|------|------|
| Todoist API 실패 | skip + 로그, GCal만으로 계속 |
| GCal API 실패 | skip + 로그, Todoist만으로 계속 |
| 2소스 모두 비어있음 | 빈 브리핑 Discord 발송 |
| LLM 검증 2회 실패 | `merged_context.json` 원문 그대로 발송 |
| Notion Morning 비어있음 | LLM 내용으로 채움 |
| Notion Morning 내용 있음 | 구분선 + `🤖 LLM 제안` 헤딩으로 append |
| Notion Write 실패 | skip + 로그, Discord 발송은 계속 진행 |
| Discord 발송 실패 | 재시도 2회 → 에러 로그 + 에스컬레이션 |

---

## 5. LLM 브리핑 생성 원칙

LLM은 `merged_context.json`을 받아 다음 원칙으로 브리핑을 생성한다:

### Top 3 도출 방법
1. **GCal 타임라인 먼저 파악** — 오늘의 고정 시간 블록 확인
2. **시간 인접성 기준 배치** — 각 일정 직전/직후에 처리해야 할 Todoist 태스크를 묶음
3. **Todoist 우선순위 반영** — 동일 시간대에 여러 태스크가 있으면 p1 우선
4. **GCal 없는 경우** — Todoist p1 → p2 → p3 순서로 Top 3 선정

### 2단 구조 원칙
- **⭐ Top 3**: LLM이 위 기준으로 선정한 오늘의 집중 태스크 (GCal 컨텍스트 포함)
- **📋 기타**: Top 3에 포함되지 않은 나머지 Todoist 태스크 (있을 때만 표시)
- **💬 코멘트**: 1줄 동기부여 또는 하루 요약
- **분량**: 500자 이내, Discord markdown 사용

---

## 6. 코드 마이그레이션 가이드 (v2.0 → v3.0)

### 삭제
```
.claude/skills/notion-reader/          # 디렉토리 전체 삭제
output/notion_raw.json                 # 더 이상 생성되지 않음
```

### 수정
```
main.py                                # Step 1b 제거, Step 5 Notion Write 삽입, Step 번호 정리
briefing-generator/SKILL.md           # 이월 섹션 제거, 2단 구조로 업데이트
briefing-generator/references/
  message_format_guide.md             # 동일
.github/workflows/daily_agent.yml    # UTC 23:00 확인 (KST→JST 동일)
```

### 신규 작성
```
.claude/skills/notion-writer/
├── SKILL.md                          # notion-writer 스킬 정의
└── scripts/write_notion_morning.py   # Morning 섹션 쓰기 로직
```

---

## 7. GitHub 저장소

**저장소 이름**: `daily-productivity-master`

### 이름 변경 체크리스트
- [ ] GitHub Settings → Repository name 변경
- [ ] 로컬: `git remote set-url origin https://github.com/유저명/daily-productivity-master.git`
- [ ] `CLAUDE.md` 내 저장소 참조 업데이트 (있는 경우)

---

## 8. 진화 방향 (로드맵)

| 단계 | 내용 | 트리거 |
|------|------|--------|
| **v3.1** | Notion Night 섹션 요약 → 다음날 브리핑에 반영 | 저녁 회고를 꾸준히 쓰게 될 때 |
| **v3.2** | Discord Bot 전환 — 커맨드로 할일 완료/추가 | 현재 Webhook의 단방향 한계를 느낄 때 |
| **v4.0** | 주간 매크로 브리핑 — 월요일 아침에 주간 패턴 돌아보기 | run_log 데이터가 충분히 쌓인 후 |

---

*이 설계서는 Claude Code에서 CLAUDE.md, SKILL.md, 스크립트 구현 시 참조하는 계획서입니다.*
