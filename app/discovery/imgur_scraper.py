import requests
from app.database import is_video_used

def fetch_top_clips(limit=6, query_type="funny"):
    import random
    if query_type == "funny":
        tag = "funny"
    elif query_type == "food":
        tag = random.choice(["food", "baking", "cooking", "foodporn"])
    elif query_type == "romantic":
        tag = random.choice(["aww", "wholesome", "love"])
    else:
        tag = query_type
        
    print(f"Searching Imgur for #{tag} viral clips...")
    valid_clips = []
    
    url = f"https://api.imgur.com/3/gallery/t/{tag}/viral/1?showViral=true&mature=false&album_previews=true"
    headers = {
        "Authorization": "Client-ID 546c25a59c58ad7"
    }
    
    try:
        r = requests.get(url, headers=headers)
        if r.status_code != 200:
            print(f"Failed to fetch Imgur: {r.status_code}")
            return valid_clips
            
        data = r.json()
        items = data.get('data', {}).get('items', [])
        
        for item in items:
            video_url = None
            if item.get('is_album'):
                images = item.get('images', [])
                if images and images[0].get('type') == 'video/mp4':
                    video_url = images[0].get('link')
            elif item.get('type') == 'video/mp4':
                video_url = item.get('link')
                
            if video_url:
                video_id = item.get('id')
                if not video_id:
                    continue
                    
                if is_video_used(video_id):
                    print(f"Skipping {video_id} - Already used.")
                    continue
                    
                title = item.get('title', 'Funny Video')
                
                clip_data = {
                    "id": video_id,
                    "title": title,
                    "url": video_url,
                    "source": "imgur",
                    "subreddit": "imgur"
                }
                
                valid_clips.append(clip_data)
                
                if len(valid_clips) >= limit:
                    break
                    
    except Exception as e:
        print(f"Error fetching from Imgur: {e}")

    return valid_clips
