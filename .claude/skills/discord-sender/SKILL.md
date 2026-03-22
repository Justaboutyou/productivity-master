# discord-sender 스킬

## 역할
`output/briefing_draft.md`를 읽어 Discord Incoming Webhook으로 발송한다.

## Step 6 — 메시지 발송 (`send_discord_message.py`)

**입력**: `output/briefing_draft.md`, 환경 변수 `DISCORD_WEBHOOK_URL`
**동작**:
1. `briefing_draft.md` 내용을 읽는다.
2. `POST {DISCORD_WEBHOOK_URL}` — `{"content": message}` 전송
3. HTTP 200 or 204 확인
4. 실패 시 1초 대기 후 최대 2회 재시도

**Exit codes**:
- `0`: 발송 성공
- `1`: 최종 실패 (재시도 소진)

**실패 시**: `output/run_log.json`에 `status: "failed"`, `reason: "discord_error"` 기록

## 환경 변수
- `DISCORD_WEBHOOK_URL`: Discord Incoming Webhook URL (필수)
  - 설정 경로: Discord 서버 설정 → 연동 → 웹후크 → 새 웹후크
