# briefing-generator 스킬

## 역할
Gemini LLM을 사용해 `merged_context.json`을 2단 구조 Discord 브리핑으로 변환하고 자기 검증한다.

## Step 3 — 브리핑 생성

**모델**: `gemini-2.5-flash`
**입력**: `output/merged_context.json` (todoist + gcal_events)
**참조**: `references/message_format_guide.md`

### Top 3 선정 기준 (LLM 판단)
1. GCal 일정이 있는 시간대와 **시간적으로 인접한** Todoist 태스크 우선 배치
2. 동일 시간대에 여러 태스크가 있으면 p1 > p2 > p3 순
3. GCal 없으면 Todoist p1 → p2 → p3 순서로 Top 3 선정

### 출력 형식 (2단 구조)
```
🌅 오늘의 브리핑 (MM/DD 요일)

⭐ 오늘의 Top 3
• GCal 시간 컨텍스트 → 태스크 (p1)
• ...

📋 기타
• Top 3 외 나머지 Todoist 태스크 (항목 없으면 섹션 생략)

💬 한 줄 동기부여 코멘트
```

### 규칙
- 전체 500자 이내
- Discord markdown 사용
- 한국어

## Step 4 — 자기 검증

**검증 항목**:
1. ⭐ 오늘의 Top 3 섹션 존재
2. 500자 이내
3. 톤 적절성

**반환 형식**:
```json
{"pass": true, "issues": []}
{"pass": false, "issues": ["이슈 설명"]}
```

**재시도**: 검증 실패 시 최대 2회 재생성
**Fallback**: 2회 초과 시 `merged_context.json` 원문 그대로 발송
