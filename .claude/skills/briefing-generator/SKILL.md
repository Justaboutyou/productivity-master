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

## 에러 처리

LLM JSON 파싱 실패 시: `starred=[]`, `comment=raw_text` 로 폴백.
