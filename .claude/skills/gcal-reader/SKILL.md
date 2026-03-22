# gcal-reader 스킬

## 역할
Google Calendar에서 오늘 00:00~23:59 JST 이벤트를 수집해 `output/gcal_raw.json`에 저장한다.

## Step 1b — GCal 일정 수집 (`fetch_gcal_events.py`)

**인증 방식**: OAuth2 (Client ID + Client Secret + Token JSON)
**출력**: `output/gcal_raw.json`

### 동작
1. `GCAL_TOKEN_JSON` base64 디코딩 → `Credentials` 객체 생성
2. 액세스 토큰 만료 시 refresh_token으로 자동 갱신
3. Google Calendar API v3로 오늘 primary 캘린더 이벤트 조회
4. 시간 범위: JST 00:00 ~ 23:59
5. 시작·종료 시간을 JST HH:MM 포맷으로 변환

### 출력 스키마
```json
{
  "date": "YYYY-MM-DD",
  "events": [
    { "title": "이벤트 제목", "start": "10:00", "end": "11:00" }
  ]
}
```

### Exit codes
- `0`: 성공 (빈 배열도 성공)
- `1`: 인증 오류 또는 API 실패

## 환경 변수
- `GCAL_CLIENT_ID`: OAuth2 클라이언트 ID
- `GCAL_CLIENT_SECRET`: OAuth2 클라이언트 시크릿
- `GCAL_TOKEN_JSON`: token.json의 base64 인코딩 값

## 초기 설정 (최초 1회)

1. Google Cloud Console에서 OAuth2 클라이언트 ID 생성 (데스크톱 앱)
2. `.env`에 `GCAL_CLIENT_ID`, `GCAL_CLIENT_SECRET` 설정
3. 인증 스크립트 실행:
   ```bash
   python .claude/skills/gcal-reader/scripts/gcal_auth.py
   ```
4. 브라우저에서 Google 계정 인증 완료
5. 출력된 base64 값을 `GCAL_TOKEN_JSON`으로 GitHub Secrets에 등록
