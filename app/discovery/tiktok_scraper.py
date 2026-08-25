import yt_dlp
import random
import urllib.parse
from typing import List, Dict
from app.database import is_video_used

def fetch_tiktok(limit: int = 5, query_type: str = "funny") -> List[Dict]:
    """
    Scrapes TikTok using verified creator channels and fallbacks.
    """
    print(f"Searching TikTok for '{query_type}' clips...")
    
    from app.discovery.tiktok_scraper_users import FUNNY_USERS, ROMANTIC_USERS, FOOD_USERS
    if query_type == "food":
        user_list = list(FOOD_USERS)
    elif query_type == "romantic":
        user_list = list(ROMANTIC_USERS)
    else:
        user_list = list(FUNNY_USERS)
        
    random.shuffle(user_list)
    
    ydl_opts = {
        'quiet': True,
        'extract_flat': True,
        'playlistend': limit * 2,
    }
    
    valid_clips = []
    consecutive_failures = 0
    
    for username in user_list:
        if len(valid_clips) >= limit or consecutive_failures >= 2:
            break
            
        url = f"https://www.tiktok.com/@{username}"
        print(f"Scraping TikTok creator: @{username}...")
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if 'entries' in info and info['entries']:
                    for entry in info['entries']:
                        if len(valid_clips) >= limit:
                            break
                            
                        raw_id = entry.get('id') or entry.get('url', '').split('/')[-1]
                        video_id = f"tt_{raw_id}"
                        title = entry.get('title', f"TikTok clip by @{username}")
                        video_url = entry.get('url') or f"https://www.tiktok.com/@{username}/video/{raw_id}"
                        
                        if raw_id and video_url:
                            if is_video_used(video_id) or is_video_used(raw_id):
                                print(f"Skipping duplicate TikTok video: {video_id}")
                                continue
                                
                            valid_clips.append({
                                "id": video_id,
                                "title": title,
                                "url": video_url,
                                "source": f"TikTok (@{username})"
                            })
                    consecutive_failures = 0
        except Exception as e:
            consecutive_failures += 1
            print(f"Could not scrape @{username} ({e}).")
            if consecutive_failures >= 2:
                print("TikTok anti-bot active on IP. Fast failing over to YouTube/Imgur...")
                break
            continue
            
    print(f"Successfully scraped {len(valid_clips)} TikTok clips.")
    return valid_clips
