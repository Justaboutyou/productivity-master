# briefing-generator 스킬

## 역할
Gemini LLM을 사용해 할일 목록을 Slack 브리핑 메시지로 변환하고 자기 검증한다.

## Step 3 — 브리핑 생성

**모델**: `gemini-1.5-flash`
**입력**: `output/todo_raw.json`의 todos 배열
**참조**: `references/message_format_guide.md`

### 프롬프트 규칙
- 헤더: `🌅 오늘의 할일 브리핑 (MM/DD 요일)`
- `top_priorities` 섹션 → `📌 우선순위 높음` 아래 표시
- `brain_dump` 섹션 → `📋 일반` 아래 표시
- Slack mrkdwn 형식
- 전체 500자 이내
- `💬` 동기부여 한 마디로 마무리
- 완료 항목 (`checked: true`) → `~취소선~` 표시

## Step 4 — 자기 검증

**검증 항목**:
1. 원본 할일 전체 포함 여부
2. 500자 이내
3. Slack mrkdwn 형식 준수
4. 톤 적절성

**반환 형식**:
```json
{"pass": true, "issues": []}
{"pass": false, "issues": ["이슈 설명"]}
```

**재시도**: 검증 실패 시 최대 2회 재생성
**Fallback**: 2회 초과 시 원본 할일 목록을 그대로 포맷하여 발송
