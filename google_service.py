import os
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError

def create_service(client_secret_file, api_name, api_version, *scopes, prefix=''):
    """
    Creates and returns a Google API service client, handling OAuth2 token storage and refresh.

    Parameters:
    - client_secret_file: Path to the OAuth2 client_secret.json file
    - api_name: Name of the Google API (e.g., 'gmail')
    - api_version: Version of the API (e.g., 'v1')
    - scopes: One or more OAuth2 scopes
    - prefix: Optional token filename prefix

    Token storage:
    - Uses '/tmp/token files/' in cloud environments or defaults to '/tmp/'
    - Reads existing token JSON from env var 'GMAIL_OAUTH_TOKEN' if provided
    - Falls back to browser or console flow for first auth
    """
    SCOPES = list(scopes)

    # Determine base directory for token storage (use /tmp in cloud)
    base_dir = Path(os.getenv('BASE_TOKEN_DIR', '/tmp'))
    token_dir = base_dir / 'token files'
    token_dir.mkdir(parents=True, exist_ok=True)
    token_file = token_dir / f'token_{api_name}_{api_version}{prefix}.json'

    # If a token is provided via environment, write it once
    token_json = os.getenv('GMAIL_OAUTH_TOKEN')
    if token_json and not token_file.exists():
        token_file.write_text(token_json)

    creds = None
    # Attempt to load existing credentials
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)

    # If no valid credentials, perform OAuth flow or refresh
    if not creds or not creds.valid:
        # 1) Try to refresh an expired token
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                # Refresh token was revoked or expired: delete and force re-auth
                token_file.unlink(missing_ok=True)
                creds = None

        # 2) If still no valid creds, run the OAuth flow
        if not creds:
            flow = InstalledAppFlow.from_client_secrets_file(
                client_secret_file,
                SCOPES
            )
            try:
                creds = flow.run_local_server(
                    port=0,
                    access_type='offline',   # request a refresh token
                    prompt='consent'         # force the consent screen every time
                )
            except Exception:
                # Fallback for environments without a browser
                creds = flow.run_console(
                    access_type='offline',
                    prompt='consent'
                )

            # Save the new credentials
            token_file.write_text(creds.to_json())

    # Build service client
    try:
        service = build(api_name, api_version, credentials=creds, static_discovery=False)
        print(f"{api_name} {api_version} service created successfully")
        return service
    except Exception as e:
        print(e)
        print(f"Failed to create service instance for {api_name}")
        # Remove bad token to force re-auth next time
        token_file.unlink(missing_ok=True)
        return None
