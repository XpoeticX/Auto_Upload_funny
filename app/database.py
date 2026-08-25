import os
from supabase import create_client, Client

# We will initialize this gracefully so local testing without Supabase doesn't instantly crash
supabase: Client = None

def init_db():
    global supabase
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    
    if url and key:
        try:
            supabase = create_client(url, key)
            print("Supabase database initialized successfully.")
        except Exception as e:
            print(f"Failed to initialize Supabase: {e}")
    else:
        print("WARNING: Supabase credentials not found. Tracking will be disabled.")

def is_video_used(video_id: str) -> bool:
    """Checks if a video ID is already in the database."""
    if not supabase:
        return False
        
    try:
        response = supabase.table("used_videos").select("*").eq("id", video_id).execute()
        return len(response.data) > 0
    except Exception as e:
        print(f"Error checking if video {video_id} is used: {e}")
        return False

def mark_video_used(video_id: str, title: str, source: str = "reddit"):
    """Saves the video ID to the database so we don't use it again."""
    if not supabase:
        print(f"Skipping DB save for {video_id} (No Supabase connected).")
        return
        
    try:
        supabase.table("used_videos").insert({
            "id": video_id,
            "title": title,
            "source": source
        }).execute()
        print(f"Marked video {video_id} as used in DB.")
    except Exception as e:
        print(f"Error marking video {video_id} as used: {e}")

def log_video_analytics(video_id: str, title: str, category: str, hook_style: str = "visual_twist", yt_id: str = None, fb_id: str = None):
    """Logs uploaded video details into video_analytics table for metric tracking."""
    if not supabase:
        return
        
    try:
        data = {
            "video_id": video_id,
            "title": title,
            "category": category,
            "hook_style": hook_style,
            "yt_video_id": yt_id or "",
            "fb_video_id": fb_id or "",
            "viral_score": 0.0
        }
        supabase.table("video_analytics").upsert(data, on_conflict="video_id").execute()
        print(f"Logged {video_id} in video_analytics table.")
    except Exception as e:
        print(f"Note: Could not log to video_analytics ({e}).")

def get_tracked_videos_for_analytics(limit: int = 50):
    """Fetches recent tracked videos from video_analytics table."""
    if not supabase:
        return []
    try:
        res = supabase.table("video_analytics").select("*").order("id", desc=True).limit(limit).execute()
        return res.data or []
    except Exception as e:
        print(f"Error fetching tracked videos: {e}")
        return []

def update_video_metrics(video_id: str, updates: dict):
    """Updates performance metrics and viral score for a video."""
    if not supabase or not updates:
        return
    try:
        supabase.table("video_analytics").update(updates).eq("video_id", video_id).execute()
    except Exception as e:
        print(f"Error updating video metrics for {video_id}: {e}")

def get_creative_profile(category: str) -> dict:
    """Fetches the latest dynamic creative profile for a category from Supabase."""
    if not supabase:
        return {}
    try:
        res = supabase.table("dynamic_creative_profile").select("*").eq("category", category).execute()
        if res.data and len(res.data) > 0:
            return res.data[0]
        return {}
    except Exception as e:
        print(f"Note: Could not read dynamic_creative_profile ({e}).")
        return {}

def save_creative_profile(category: str, profile_data: dict):
    """Saves/upserts the updated dynamic creative profile to Supabase."""
    if not supabase or not profile_data:
        return
    try:
        payload = {
            "category": category,
            "optimal_clip_length": profile_data.get("optimal_clip_length", "12-18 seconds"),
            "winning_hook_patterns": profile_data.get("winning_visual_hooks", []),
            "banned_topics": profile_data.get("underperforming_elements_to_ban", []),
            "title_archetypes": profile_data.get("high_converting_title_templates", []),
            "retention_rules": profile_data.get("retention_rules", {}),
            "high_engagement_cta": profile_data.get("high_engagement_cta", ""),
            "reasoning_summary": profile_data.get("reasoning_summary", "")
        }
        supabase.table("dynamic_creative_profile").upsert(payload, on_conflict="category").execute()
        print(f"✅ Dynamic creative profile for '{category}' successfully updated in Supabase!")
    except Exception as e:
        print(f"Error saving creative profile for {category}: {e}")
