# todoist-reader 스킬

## 역할
Todoist REST v2에서 오늘 due date인 미완료 태스크를 수집해 `output/todoist_raw.json`에 저장한다.

## Step 1a — Todoist 태스크 수집 (`fetch_todoist_tasks.py`)

**입력**: 환경 변수 `TODOIST_API_KEY`
**출력**: `output/todoist_raw.json`

### 동작
1. `GET https://api.todoist.com/rest/v2/tasks?filter=today` 호출
2. 오늘 날짜 due date인 태스크만 필터링
3. Todoist priority를 역변환 (API 4→p1, 3→p2, 2→p3, 1→p4)
4. due_time이 있으면 JST 기준 HH:MM 포맷

### 출력 스키마
```json
{
  "date": "YYYY-MM-DD",
  "tasks": [
    { "text": "할일 내용", "priority": 1, "due_time": "09:00" }
  ]
}
```

### Exit codes
- `0`: 성공 (빈 배열도 성공)
- `1`: API 오류 또는 인증 실패

## 환경 변수
- `TODOIST_API_KEY`: Todoist REST v2 API 키 (필수)
