import os
from google_auth_oauthlib.flow import InstalledAppFlow

# The scopes required for uploading to YouTube and reading video analytics
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly"
]

def main():
    print("=== YouTube Authentication Setup for New Channel ===")
    print("This script will help you link your brand new YouTube channel to the automation pipeline.")
    
    if not os.path.exists("client_secrets.json"):
        print("\nERROR: 'client_secrets.json' not found in this folder.")
        print("Please go to Google Cloud Console, create a new project with your new account,")
        print("enable the YouTube Data API v3, create OAuth 2.0 Client IDs (Desktop App),")
        print("download the JSON file, and save it here as 'client_secrets.json'.")
        return

    print("\nStarting authentication flow... A browser window will open.")
    print("Make sure you log in with the Google Account of your NEW YouTube channel!")
    
    flow = InstalledAppFlow.from_client_secrets_file("client_secrets.json", SCOPES)
    
    # Run local server to catch the callback
    creds = flow.run_local_server(port=0)
    
    # Save the credentials for the next run
    with open("token.json", "w") as token:
        token.write(creds.to_json())
        
    print("\nSUCCESS! Your 'token.json' has been generated.")
    print("You can now copy the contents of 'token.json' and paste it into your GitHub Secrets")
    print("under the name 'YOUTUBE_TOKEN_JSON'.")

if __name__ == "__main__":
    main()
