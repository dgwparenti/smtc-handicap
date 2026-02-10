# test_gmail_auth.py
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CREDENTIALS_FILE = Path("credentials/client_secret_476582044326-bk4gin0gc4our2gl9m5t3ntvkpafktsu.apps.googleusercontent.com.json")
TOKEN_FILE = Path("credentials/gmail_token.json")

def authenticate():
    creds = None

    # Load existing token if available
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    # If no valid creds, do the OAuth flow
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refreshing expired token...")
            creds.refresh(Request())
        else:
            print("Opening browser for authentication...")
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)

        # Save token for next time
        TOKEN_FILE.parent.mkdir(exist_ok=True)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
        print(f"Token saved to {TOKEN_FILE}")

    return creds

def main():
    creds = authenticate()

    # Build Gmail service
    service = build("gmail", "v1", credentials=creds)

    # Test: Search for Daily Results emails
    query = 'subject:"Daily Results" from:@cresta-run.com'
    print(f"\nSearching: {query}")

    results = service.users().messages().list(
        userId="me",
        q=query,
        maxResults=5
    ).execute()

    messages = results.get("messages", [])
    print(f"Found {len(messages)} emails")

    # Show first few
    for msg in messages[:3]:
        full = service.users().messages().get(userId="me", id=msg["id"], format="metadata").execute()
        headers = {h["name"]: h["value"] for h in full["payload"]["headers"]}
        print(f"  - {headers.get('Date', 'No date')}: {headers.get('Subject', 'No subject')}")

if __name__ == "__main__":
    main()
