import os
import yt_dlp
from app.database import is_video_used

def fetch_top_clips(limit=6, query_type="funny", custom_queries: list = None):
    print("Searching YouTube Shorts for clips...")
    valid_clips = []
    
    # Write cookies to file if available
    cookies_content = os.environ.get("YOUTUBE_COOKIES")
    cookies_path = "data/temp/youtube_cookies.txt"
    os.makedirs("data/temp", exist_ok=True)
    if cookies_content:
        with open(cookies_path, "w", encoding="utf-8") as f:
            f.write(cookies_content)
    
    ydl_opts = {
        'quiet': True,
        'extract_flat': True,
        'force_generic_extractor': False,
    }
    
    import random
    
    if os.path.exists(cookies_path):
        ydl_opts['cookiefile'] = cookies_path

    if custom_queries and len(custom_queries) > 0:
        raw_q = random.choice(custom_queries)
        search_query = raw_q if raw_q.startswith("ytsearch") else f'ytsearch30:"{raw_q}" #shorts'
    elif query_type == "funny" or query_type == "hooks" or query_type == "malloy":
        queries = [
            'ytsearch30:"malloy hooks" OR "viral video hook" #shorts',
            'ytsearch30:"wait for it" "unexpected ending" funny #shorts',
            'ytsearch30:"instant regret" OR "people who got caught" #shorts',
            'ytsearch30:"try not to laugh" "best fails" #shorts',
            'ytsearch30:"bro thought" funny fails #shorts',
            'ytsearch30:"cartoon box" OR "funny animation" #shorts'
        ]
        search_query = random.choice(queries)
    elif query_type == "food":
        queries = [
            'ytsearch30:"street food" OR "delicious recipe" #shorts',
            'ytsearch30:"satisfying cooking" ASMR #shorts',
            'ytsearch30:"viral food hacks" delicious #shorts',
            'ytsearch30:"mouthwatering food" #shorts'
        ]
        search_query = random.choice(queries)
    elif query_type == "romantic":
        queries = [
            'ytsearch30:"muslim couple" OR "halal relationship" #shorts',
            'ytsearch30:POV muslim couple #shorts',
            'ytsearch30:"halal dating" OR "married life" muslim #shorts',
            'ytsearch30:aesthetic muslim couple #shorts'
        ]
        search_query = random.choice(queries)
    else:
        search_query = query_type if query_type.startswith("ytsearch") else f'ytsearch30:"{query_type}" #shorts'
        
    print(f"YouTube Search Query (RLAF Driven): {search_query}")

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(search_query, download=False)
            entries = info.get('entries', [])
            
            for entry in entries:
                video_id = entry.get('id')
                if not video_id:
                    continue
                    
                title = entry.get('title', 'Video')
                duration = entry.get('duration')
                
                # Ensure it's a short (under 60s/180s)
                if duration and duration > 181:
                    continue
                    
                if is_video_used(video_id):
                    print(f"Skipping {video_id} - Already used.")
                    continue
                    
                video_url = f"https://www.youtube.com/watch?v={video_id}"
                
                clip_data = {
                    "id": video_id,
                    "title": title,
                    "url": video_url,
                    "source": "youtube"
                }
                
                valid_clips.append(clip_data)
                
                if len(valid_clips) >= limit:
                    break
    except Exception as e:
        print(f"Error fetching from YouTube: {e}")

    return valid_clips

def fetch_long_compilation(query_type="funny") -> dict:
    """
    Searches YouTube for a single massive 10-15 minute compilation video
    so we can skip downloading and merging 35 individual shorts.
    """
    print("\n[OPTIMIZER] Searching for a Long-Form Compilation Video...")
    
    ydl_opts = {
        'quiet': True,
        'extract_flat': True,
        'force_generic_extractor': False,
    }
    
    cookies_path = "data/temp/youtube_cookies.txt"
    if os.path.exists(cookies_path):
        ydl_opts['cookiefile'] = cookies_path
        
    import random
    if query_type == "funny":
        queries = [
            'ytsearch20:"funny fails" compilation long',
            'ytsearch20:best fails compilation 2024 try not to laugh',
            'ytsearch20:instant regret fails compilation'
        ]
        search_query = random.choice(queries)
    elif query_type == "food":
        queries = [
            'ytsearch20:"street food compilation" satisfying cooking',
            'ytsearch20:"best food compilation" delicious recipes',
            'ytsearch20:"satisfying cooking ASMR compilation"'
        ]
        search_query = random.choice(queries)
    elif query_type == "romantic":
        queries = [
            'ytsearch20:muslim couple tiktok compilation',
            'ytsearch20:halal relationship goals compilation',
            'ytsearch20:funny muslim husband and wife compilation'
        ]
        search_query = random.choice(queries)
    else:
        search_query = query_type if query_type.startswith("ytsearch") else f'ytsearch20:"{query_type} compilation"'
        
    print(f"Long Compilation Search Query: {search_query}")
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(search_query, download=False)
            entries = info.get('entries', [])
            
            for entry in entries:
                video_id = entry.get('id')
                duration = entry.get('duration')
                
                if not video_id or not duration:
                    continue
                    
                # We want a video strictly between 5 and 20 minutes
                if 300 <= duration <= 1200:
                    if is_video_used(video_id):
                        continue
                        
                    print(f"✅ Found perfect Long Compilation! ID: {video_id} (Duration: {duration}s)")
                    return {
                        "id": video_id,
                        "title": entry.get('title', 'Compilation Video'),
                        "url": f"https://www.youtube.com/watch?v={video_id}",
                        "source": "youtube",
                        "duration": duration
                    }
                    
    except Exception as e:
        print(f"Error fetching long compilation: {e}")
        
    return None
