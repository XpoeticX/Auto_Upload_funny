import os
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/youtube']

def main():
    if not os.path.exists('client_secrets.json'):
        print("client_secrets.json not found.")
        return

    print("Authenticating with full YouTube permissions to delete videos on DailyDos Of Fun...")
    flow = InstalledAppFlow.from_client_secrets_file('client_secrets.json', SCOPES)
    creds = flow.run_local_server(port=8080)

    youtube = build('youtube', 'v3', credentials=creds)

    ch_res = youtube.channels().list(mine=True, part='snippet,contentDetails').execute()
    items = ch_res.get('items', [])
    if not items:
        print("No channel found.")
        return

    channel = items[0]
    channel_name = channel['snippet']['title']
    uploads_id = channel['contentDetails']['relatedPlaylists']['uploads']

    print(f"\nConnected to channel: {channel_name}")
    print("Collecting all uploaded videos...")

    all_videos = []
    next_page_token = None
    while True:
        pl_res = youtube.playlistItems().list(
            playlistId=uploads_id,
            part='snippet',
            maxResults=50,
            pageToken=next_page_token
        ).execute()
        for v in pl_res.get('items', []):
            vid_id = v['snippet']['resourceId']['videoId']
            vid_title = v['snippet']['title']
            all_videos.append((vid_id, vid_title))
        next_page_token = pl_res.get('nextPageToken')
        if not next_page_token:
            break

    total = len(all_videos)
    print(f"Found {total} videos on {channel_name}.")
    if total == 0:
        print("No videos to delete.")
        return

    print(f"Deleting all {total} videos now...")
    deleted = 0
    failed = 0
    for idx, (vid_id, vid_title) in enumerate(all_videos, start=1):
        try:
            youtube.videos().delete(id=vid_id).execute()
            deleted += 1
            print(f"[{idx}/{total}] DELETED: {vid_id} - {vid_title[:45]}")
            time.sleep(0.3)
        except Exception as e:
            failed += 1
            print(f"[{idx}/{total}] ERROR deleting {vid_id}: {e}")

    print(f"\nFinished! Deleted: {deleted}, Failed: {failed}")

if __name__ == '__main__':
    main()
