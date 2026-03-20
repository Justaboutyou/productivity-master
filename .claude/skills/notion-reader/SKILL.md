# notion-reader 스킬

## 역할
Notion API를 호출하여 일지 페이지를 조회하고 할일 블록을 추출한다.

## Step 1 — 페이지 조회 (`fetch_yesterday_page.py`)

**입력**: 환경 변수 `NOTION_TOKEN`, `NOTION_DATABASE_ID`
**동작**:
1. 어제 날짜를 계산한다.
2. Notion DB에 title contains 필터로 쿼리한다.
   - 날짜 포맷 fallback: `YYYY-MM-DD` → `YYYY/MM/DD` → `MM/DD`
3. 결과 page_id를 stdout으로 출력한다.

**Exit codes**:
- `0`: 페이지 발견 (page_id stdout 출력)
- `1`: API 오류
- `2`: 페이지 없음 (스킵 신호)

## Step 2 — 할일 추출 (`extract_todo_blocks.py`)

**입력**: `page_id` (인자), 환경 변수 `NOTION_TOKEN`
**동작**:
1. Notion blocks API로 페이지 블록 전체 조회 (페이지네이션 처리)
2. 헤딩을 기준으로 섹션 추적:
   - `"Top Priorities 3"` → `section: "top_priorities"`
   - `"Brain dump"` → `section: "brain_dump"`
3. 각 섹션 아래 `to_do` 블록 수집
4. `output/todo_raw.json` 저장

**출력 스키마** (`output/todo_raw.json`):
```json
{
  "date": "YYYY-MM-DD",
  "page_id": "xxxx",
  "todos": [
    { "text": "할일 내용", "checked": false, "section": "top_priorities" }
  ]
}
```

**Exit codes**:
- `0`: 성공 (todos 비어있어도 정상)
- `1`: API 오류
