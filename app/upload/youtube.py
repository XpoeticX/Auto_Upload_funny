import os
import google_auth_oauthlib.flow
import googleapiclient.discovery
import googleapiclient.errors
from google.oauth2.credentials import Credentials
from googleapiclient.http import MediaFileUpload

def get_youtube_client():
    # In a GitHub Action, we inject token.json from secrets
    if not os.path.exists("token.json"):
        print("token.json not found! You must authenticate locally first.")
        return None
        
    try:
        creds = Credentials.from_authorized_user_file("token.json")
        return googleapiclient.discovery.build("youtube", "v3", credentials=creds)
    except Exception as e:
        print(f"Error initializing YouTube client: {e}")
        return None

def upload_to_youtube(video_path: str, title: str, description: str, tags: list, thumbnail_path: str = None):
    try:
        youtube = get_youtube_client()
        if not youtube:
            print("⚠️ Skipping YouTube upload: YouTube client unavailable.")
            return False
            
        print(f"Uploading {video_path} to YouTube Shorts...")
        
        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": "23" # Comedy
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False
            }
        }
        
        media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
        
        request = youtube.videos().insert(
            part=",".join(body.keys()),
            body=body,
            media_body=media
        )
        response = request.execute()
        video_id = response.get('id')
        print(f"Upload Successful! Video ID: {video_id}")
        
        # Upload Thumbnail if provided
        if thumbnail_path and os.path.exists(thumbnail_path):
            try:
                print(f"Uploading thumbnail: {thumbnail_path}")
                youtube.thumbnails().set(
                    videoId=video_id,
                    media_body=MediaFileUpload(thumbnail_path)
                ).execute()
                print("Thumbnail successfully attached!")
            except Exception as e:
                print(f"Failed to set YouTube thumbnail: {e}")
                
        return video_id
    except googleapiclient.errors.HttpError as e:
        print(f"An HTTP error {e.resp.status} occurred: {e.content}")
        return False
    except Exception as e:
        print(f"⚠️ YouTube Upload Error: {e}")
        if "invalid_grant" in str(e).lower() or "expired" in str(e).lower() or "revoked" in str(e).lower():
            print("\n" + "="*70)
            print("❌ CRITICAL: Your YouTube OAuth token in GitHub Secrets has expired or been revoked!")
            print("👉 Run `python setup_youtube_auth.py` locally to re-authenticate.")
            print("👉 Copy the contents of the generated `token.json` into your GitHub Secret `YOUTUBE_TOKEN_JSON`.")
            print("="*70 + "\n")
        return False
