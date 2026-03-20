# slack-sender 스킬

## 역할
`output/briefing_draft.md`를 읽어 Slack Incoming Webhook으로 발송한다.

## Step 5 — 메시지 발송 (`send_slack_message.py`)

**입력**: `output/briefing_draft.md`, 환경 변수 `SLACK_WEBHOOK_URL`
**동작**:
1. `briefing_draft.md` 내용을 읽는다.
2. `POST {SLACK_WEBHOOK_URL}` — `{"text": message}` 전송
3. HTTP 200 확인
4. 실패 시 1초 대기 후 최대 2회 재시도

**Exit codes**:
- `0`: 발송 성공
- `1`: 최종 실패 (재시도 소진)

**실패 시**: `output/run_log.json`에 `status: "failed"`, `reason: "slack_error"` 기록

## 환경 변수
- `SLACK_WEBHOOK_URL`: Slack Incoming Webhook URL (필수)
  - 설정 경로: Slack 앱 → Incoming Webhooks → Add New Webhook to Workspace
