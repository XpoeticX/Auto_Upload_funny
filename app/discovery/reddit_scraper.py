import requests
from app.database import is_video_used

def fetch_top_clips(limit=5, query_type="funny"):
    """
    Fetches funny videos from 9GAG API.
    Bypasses Reddit and YouTube rate limits against GitHub Actions.
    """
    print("Searching 9GAG for funny viral clips...")
    
    valid_clips = []
    
    url = "https://9gag.com/v1/group-posts/group/funny/type/hot"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 FunnyVideoBot/2.0"
    }
    
    next_cursor = ""
    max_pages = 5
    pages_fetched = 0
    
    while len(valid_clips) < limit and pages_fetched < max_pages:
        try:
            req_url = f"{url}?{next_cursor}" if next_cursor else url
            r = requests.get(req_url, headers=headers)
            if r.status_code != 200:
                print(f"Failed to fetch 9GAG: {r.status_code}")
                break
                
            data = r.json()
            posts = data.get('data', {}).get('posts', [])
            
            for p in posts:
                if p.get('type') == 'Animated':
                    video_id = p.get('id')
                    if not video_id:
                        continue
                        
                    if is_video_used(video_id):
                        print(f"Skipping {video_id} - Already used.")
                        continue
                        
                    title = p.get('title', 'Funny Video')
                    images = p.get('images', {})
                    
                    if 'image460sv' in images and 'url' in images['image460sv']:
                        video_url = images['image460sv']['url']
                        
                        clip_data = {
                            "id": video_id,
                            "title": title,
                            "url": video_url,
                            "source": "9gag",
                            "subreddit": "9gag"
                        }
                        
                        valid_clips.append(clip_data)
                        
                        if len(valid_clips) >= limit:
                            return valid_clips
                            
            next_cursor = data.get('data', {}).get('nextCursor')
            if not next_cursor:
                break
                
            pages_fetched += 1
            
        except Exception as e:
            print(f"Error fetching from 9GAG: {e}")
            break

    return valid_clips
