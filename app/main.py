import os
import shutil
import datetime
from dotenv import load_dotenv
import ffmpeg

load_dotenv()
from app.database import init_db, mark_video_used, is_video_used, log_video_analytics
from app.video.thumbnail import generate_thumbnail
from app.upload.youtube import upload_to_youtube
from app.upload.facebook import upload_to_facebook
from app.analytics.engine import fetch_and_update_metrics, run_meta_optimizer, get_active_profile, send_telegram_report, get_rlaf_ai_feedback
from app.story.director import generate_viral_story_concept, render_story_video, build_viral_yt_description, build_viral_fb_description

def cleanup():
    print("Cleaning up temp folders...")
    for d in ["data/temp", "data/output"]:
        if os.path.exists(d):
            shutil.rmtree(d)
        os.makedirs(d, exist_ok=True)

def main():
    print("--- Starting 100% Real AI Video Automation Pipeline ---")
    
    # Ensure working directory is project root
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    cleanup()
    init_db()
    
    env_category = os.environ.get("CONTENT_CATEGORY") or os.environ.get("PRIMARY_MOOD")
    if env_category:
        primary_mood = env_category.lower().strip()
    else:
        primary_mood = "funny"
        
    short_category = f"{primary_mood}_short"

    # --- PHASE 1: REFRESH RLAF PERFORMANCE LEDGERS ---
    print(f"\n--- Refreshing Audience Feedback & Analytics ({primary_mood}) ---")
    try:
        fetch_and_update_metrics()
        yt_short_profile = run_meta_optimizer(short_category, platform="youtube")
        fb_short_profile = run_meta_optimizer(short_category, platform="facebook")
        print(f"Loaded YouTube Directives: {yt_short_profile.get('agent_evaluation', {}).get('strategy_mode', 'Active')}")
        print(f"Loaded Facebook Directives: {fb_short_profile.get('agent_evaluation', {}).get('strategy_mode', 'Active')}")
    except Exception as e:
        print(f"Feedback engine notice ({e}). Using baseline profiles.")
        yt_short_profile = get_active_profile(short_category, platform="youtube")
        fb_short_profile = get_active_profile(short_category, platform="facebook")
        
    rlaf_feedback = get_rlaf_ai_feedback()
    uploaded_short_title = None

    # --- PHASE 2: 100% REAL AI 3-ACT ANIMATED STORY (NEURAL DIFFUSION + DYNAMIC FOLEY & MUSIC) ---
    print(f"\n--- Generating 100% Real AI Animated Short (RLAF Steered: {primary_mood}) ---")
    story_concept = generate_viral_story_concept(rlaf_feedback=rlaf_feedback)
    story_id = f"ai_story_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    story_out = os.path.join("data", "output", f"{story_id}.mp4")

    rendered_short = render_story_video(story_concept, story_out)
    if rendered_short and os.path.exists(rendered_short):
        yt_title = story_concept.get("yt_title", f"{story_concept.get('title')} 🐾😂 #shorts #viral")
        fb_title = story_concept.get("fb_title", f"Wait till the end! 😂 Tag someone who needs to see this!")
        yt_tags = story_concept.get("tags") or ["shorts", "viral", "animation", "comedy"]
        yt_description = build_viral_yt_description(story_concept)
        fb_description = build_viral_fb_description(story_concept)
        
        thumb_path = os.path.join("data", "output", f"thumb_{story_id}.jpg")
        generate_thumbnail(rendered_short, thumb_path)
        
        print(f"Uploading 100% AI Animated Short | YT: '{yt_title}' | FB: '{fb_title}'...")
        yt_res = upload_to_youtube(rendered_short, yt_title, yt_description, yt_tags, thumbnail_path=thumb_path)
        fb_res = upload_to_facebook(rendered_short, fb_title, fb_description, is_compilation=False, thumbnail_path=thumb_path)
        
        log_video_analytics(
            video_id=story_id,
            title=yt_title,
            category=story_concept.get("niche", "AI_Animation"),
            hook_style="AI_Story_3Act",
            yt_id=str(yt_res) if yt_res and str(yt_res) != "True" else None,
            fb_id=str(fb_res) if fb_res and str(fb_res) != "True" else None
        )
        uploaded_short_title = f"YT: '{yt_title}' | FB: '{fb_title}'"
    else:
        print("[ERROR] AI Story rendering failed. No video generated.")

    # --- PHASE 3: MULTI-PLATFORM TELEGRAM NOTIFICATION ---
    try:
        upload_summary = {
            "short_title": uploaded_short_title or "Upload Failed",
            "comp_title": "100% AI Animation Mode (No text dilemmas)"
        }
        send_telegram_report(primary_mood, yt_short_profile, fb_profile=fb_short_profile, upload_summary=upload_summary)
    except Exception as e:
        print(f"Telegram report notification notice: {e}")

    # Clean up temp files
    cleanup()
    print("Pipeline finished successfully.")

if __name__ == "__main__":
    main()
