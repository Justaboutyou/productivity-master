# notion-writer 스킬

## 역할
`output/briefing_draft.md`를 파싱해 Notion 일지 페이지의 Morning 섹션을 채운다.
Night 섹션은 절대 건드리지 않는다.

## Step 5 — Notion Morning 섹션 채우기 (`write_notion_morning.py`)

**입력**: `output/briefing_draft.md`, 환경 변수 `NOTION_TOKEN`, `NOTION_DATABASE_ID`
**출력**: Notion 페이지 Morning 섹션 업데이트

### 동작
1. `briefing_draft.md`에서 Top 3와 기타(Brain Dump) 항목 추출
2. 오늘 날짜 Notion 페이지 조회 (없으면 신규 생성)
3. Morning 섹션 상태 확인 → 비어있으면 채움, 내용 있으면 append

### 쓰기 정책

| 상황 | 동작 |
|------|------|
| 오늘 페이지 없음 | 템플릿으로 신규 생성 (Morning + Night 섹션) |
| Morning 비어있음 | Top Priorities 3 + Brain Dump 채움 |
| Morning 내용 있음 | 구분선 + `🤖 LLM 제안` 헤딩 후 append |
| Night 섹션 | **절대 건드리지 않음** |

### Notion 페이지 구조
```
☀️ Morning: 오늘 하루를 어떻게 보낼까요?
  1️⃣ Top Priorities 3
  • Top 3 항목들
  2️⃣ Brain Dump
  • 나머지 Todoist 태스크

🌙 Night: 성찰과 감사 (오늘 하루는 어땠나요?)
  • 오늘 내가 잘한 것 1가지는?
  • 오늘 무엇을 더 잘할 수 있었을까? (Better Me)
```

### Exit codes
- `0`: 성공
- `1`: 오류 (환경 변수 누락, API 실패)

## 환경 변수
- `NOTION_TOKEN`: Notion Integration Token (필수)
- `NOTION_DATABASE_ID`: 일지 데이터베이스 ID (필수)
  - 데이터베이스에 `날짜` (Date 타입) 속성 필요
