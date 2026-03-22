"""
Google Calendar OAuth2 인증 설정 스크립트 (로컬 1회 실행용)

실행 방법:
  python .claude/skills/gcal-reader/scripts/gcal_auth.py

완료 후:
  1. token.json이 생성됨
  2. base64 인코딩된 값을 GCAL_TOKEN_JSON으로 GitHub Secrets에 등록
  3. GCAL_CLIENT_ID, GCAL_CLIENT_SECRET도 GitHub Secrets에 등록

필요 환경변수 (.env):
  GCAL_CLIENT_ID
  GCAL_CLIENT_SECRET
"""

import base64
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
TOKEN_PATH = Path(__file__).parents[4] / "token.json"


def main():
    client_id = os.environ.get("GCAL_CLIENT_ID")
    client_secret = os.environ.get("GCAL_CLIENT_SECRET")

    if not client_id or not client_secret:
        print("에러: GCAL_CLIENT_ID 또는 GCAL_CLIENT_SECRET이 설정되지 않았습니다.")
        print(".env 파일을 확인하세요.")
        return

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    creds = flow.run_local_server(port=0)

    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes),
    }

    TOKEN_PATH.write_text(json.dumps(token_data, indent=2))
    print(f"\n✓ token.json 생성 완료: {TOKEN_PATH}")

    encoded = base64.b64encode(json.dumps(token_data).encode()).decode()
    print("\n=== GitHub Secrets에 등록할 값 (GCAL_TOKEN_JSON) ===")
    print(encoded)
    print("\n=== 다음 3개 GitHub Secrets를 등록하세요 ===")
    print(f"GCAL_CLIENT_ID     = {client_id}")
    print(f"GCAL_CLIENT_SECRET = {client_secret}")
    print(f"GCAL_TOKEN_JSON    = (위의 base64 문자열)")


if __name__ == "__main__":
    main()
