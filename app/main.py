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
from app.story.director import (
    generate_viral_story_concept,
    render_story_video,
    build_viral_yt_description,
    build_viral_fb_description,
    sanitize_viral_title
)
from app.discovery.youtube_scraper import fetch_top_clips
from app.discovery.downloader import download_video
from app.discovery.reddit_scraper import fetch_top_clips as fetch_9gag_clips
from app.ai.narrator import generate_ai_narration
from app.video.remix_engine import transform_video_with_ai

def cleanup():
    print("Cleaning up temp folders...")
    for d in ["data/temp", "data/output"]:
        if os.path.exists(d):
            shutil.rmtree(d)
        os.makedirs(d, exist_ok=True)

def execute_ai_story(primary_mood: str, short_category: str, yt_profile: dict, fb_profile: dict, rlaf_feedback: dict) -> tuple[bool, str]:
    """Generates and uploads a 100% original AI 5-act animated story."""
    print(f"\n--- [MODE: AI STORY] Generating 100% Real AI Animated Short ({primary_mood}) ---")
    try:
        story_concept = generate_viral_story_concept(
            rlaf_feedback=rlaf_feedback,
            yt_profile=yt_profile,
            fb_profile=fb_profile
        )
        story_id = f"ai_story_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
        story_out = os.path.join("data", "output", f"{story_id}.mp4")

        rendered_short = render_story_video(story_concept, story_out)
        if rendered_short and os.path.exists(rendered_short):
            raw_yt_title = story_concept.get("yt_title", f"{story_concept.get('title')} #shorts #viral")
            yt_title = sanitize_viral_title(raw_yt_title, "Amazing Moment! 😂 #shorts #viral")
            fb_title = story_concept.get("fb_title", "Wait till the end! 😂 Tag someone who needs to see this!")
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
                category=short_category,
                hook_style="AI_Story_5Act",
                yt_id=str(yt_res) if yt_res and str(yt_res) != "True" else None,
                fb_id=str(fb_res) if fb_res and str(fb_res) != "True" else None
            )
            return True, f"AI Story -> YT: '{yt_title}' | FB: '{fb_title}'"
        else:
            print("[MODE: AI STORY] Rendering did not produce a valid output.")
            return False, None
    except Exception as e:
        print(f"[MODE: AI STORY] Error during story execution: {e}")
        return False, None

def execute_viral_remix(primary_mood: str, short_category: str, yt_profile: dict, fb_profile: dict, rlaf_feedback: dict) -> tuple[bool, str]:
    """Discovers, downloads, scripts, remixes, and uploads trending viral clips with 0 restrictions."""
    print(f"\n--- [MODE: VIRAL REMIX] Discovering & Transforming Viral Clips ({primary_mood}) ---")
    
    # 1. Gather RLAF Steered Search Queries
    custom_queries = []
    if yt_profile:
        custom_queries = yt_profile.get("phase_1_discovery_directives", {}).get("primary_search_queries", [])
    
    # 2. Fetch Viral Candidates (YouTube Shorts first, fallback to 9GAG)
    candidates = []
    try:
        candidates = fetch_top_clips(limit=6, query_type=primary_mood, custom_queries=custom_queries)
    except Exception as e:
        print(f"[VIRAL REMIX] YouTube search notice: {e}")

    if not candidates:
        print("[VIRAL REMIX] YouTube candidates exhausted. Trying fallback clip network...")
        try:
            candidates = fetch_9gag_clips(limit=6, query_type=primary_mood)
        except Exception as e:
            print(f"[VIRAL REMIX] Fallback network notice: {e}")

    if not candidates:
        print("[VIRAL REMIX] No candidate clips found across discovery networks.")
        return False, None

    # 3. Process candidates
    for clip in candidates:
        clip_id = str(clip.get("id"))
        if is_video_used(clip_id):
            continue

        clip_title = clip.get("title", "Viral Clip")
        clip_url = clip.get("url")
        print(f"\n[VIRAL REMIX] Processing candidate: '{clip_title}' ({clip_url})")

        raw_path = os.path.join("data", "temp", f"raw_{clip_id}.mp4")
        downloaded = download_video(clip_url, raw_path)
        if not downloaded or not os.path.exists(downloaded):
            print(f"[VIRAL REMIX] Failed to download {clip_url}. Trying next candidate...")
            continue

        # Check duration
        try:
            probe = ffmpeg.probe(downloaded)
            clip_dur = float(probe['format']['duration'])
            if clip_dur < 4.0 or clip_dur > 65.0:
                print(f"[VIRAL REMIX] Clip duration ({clip_dur:.1f}s) outside optimal window. Skipping.")
                continue
        except Exception:
            clip_dur = 14.0

        # --- QURAN PRESERVATION SAFEGUARD ---
        # User requirement: For Quran videos, do not alter or add meme banners; use original video.
        if primary_mood == "quran" or "quran" in clip_title.lower():
            print("[QURAN PRESERVATION] Uploading authentic original video without meme banners or alteration.")
            final_video = downloaded
            yt_title = sanitize_viral_title(clip_title, "Beautiful Quran Recitation 📖✨ #shorts #quran")
            fb_title = clip_title
            yt_tags = ["quran", "islamic", "recitation", "shorts", "peace"]
            yt_description = f"{yt_title}\n\n📖 Beautiful Quran Recitation.\n\n#quran #islam #recitation #shorts"
            fb_description = f"{fb_title}\n\n#quran #islam #recitation #reels"
            hook_style = "Quran_Original"
        else:
            # Transformative AI Remix (Comedic voiceover + 9:16 reframe + unique hash + meme banner + watermark)
            print(f"[VIRAL REMIX] Generating AI voiceover commentary for '{clip_title}'...")
            ai_data = generate_ai_narration(downloaded, clip_duration=clip_dur, clip_title=clip_title)

            remix_out = os.path.join("data", "output", f"remix_{clip_id}.mp4")
            final_video = transform_video_with_ai(downloaded, ai_data, remix_out)
            if not final_video or not os.path.exists(final_video):
                print("[VIRAL REMIX] Video transformation failed. Trying next candidate...")
                continue

            raw_yt_title = ai_data.get("yt_title", f"{clip_title} 😂💀 #shorts #viral")
            yt_title = sanitize_viral_title(raw_yt_title, "Wait for the reaction! 😂💀 #shorts #viral")
            fb_title = ai_data.get("fb_title", "He was not having it today 😂 Tag a friend! 👇")
            yt_tags = ai_data.get("tags") or ["shorts", "viral", "funny", "comedy"]
            yt_hashtags = " ".join([f"#{t}" for t in yt_tags[:5]])
            yt_description = (
                f"{yt_title}\n\n💬 {fb_title}\n\n"
                f"🔔 SUBSCRIBE to Daily Dose of Fun for daily laughs: https://www.youtube.com/@DailyDosOfFun-q2t\n"
                f"📱 Follow on Facebook: https://www.facebook.com/profile.php?id=100077547189991\n\n"
                f"{yt_hashtags}\n\n"
                f"Disclaimer: Content transformed with original commentary and creative editing under Fair Use principles."
            )
            fb_description = (
                f"{fb_title}\n\n"
                f"📱 Follow Daily Dose of Fun for daily viral moments: https://www.facebook.com/profile.php?id=100077547189991\n"
                f"🔔 YouTube: https://www.youtube.com/@DailyDosOfFun-q2t\n\n"
                f"#reels #funnyreels #viral #comedy"
            )
            hook_style = "AI_Viral_Remix"

        # Generate thumbnail and upload
        thumb_path = os.path.join("data", "output", f"thumb_{clip_id}.jpg")
        generate_thumbnail(final_video, thumb_path)

        print(f"Uploading Transformed Short | YT: '{yt_title}' | FB: '{fb_title}'...")
        yt_res = upload_to_youtube(final_video, yt_title, yt_description, yt_tags, thumbnail_path=thumb_path)
        fb_res = upload_to_facebook(final_video, fb_title, fb_description, is_compilation=False, thumbnail_path=thumb_path)

        log_video_analytics(
            video_id=clip_id,
            title=yt_title,
            category=short_category,
            hook_style=hook_style,
            yt_id=str(yt_res) if yt_res and str(yt_res) != "True" else None,
            fb_id=str(fb_res) if fb_res and str(fb_res) != "True" else None
        )
        mark_video_used(clip_id, clip_title, source=clip.get("source", "youtube"))
        return True, f"Viral Remix -> YT: '{yt_title}' | FB: '{fb_title}'"

    print("[VIRAL REMIX] All candidates exhausted without successful upload.")
    return False, None

def main():
    print("--- Starting Zero-Restriction Multi-Modal Automation Pipeline ---")
    
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

    # --- PHASE 2: ADAPTIVE CONTENT ROUTING (0 RESTRICTION) ---
    content_mode = os.environ.get("CONTENT_MODE", "auto").lower().strip()
    preferred_format = rlaf_feedback.get("recommended_format", "remix")
    print(f"\n[ORCHESTRATOR] Content Mode Config: '{content_mode}' | RLAF Recommended: '{preferred_format.upper()}'")

    success = False
    
    # Mode Router with Zero-Failure Waterfall
    if content_mode == "ai_story":
        success, uploaded_short_title = execute_ai_story(primary_mood, short_category, yt_short_profile, fb_short_profile, rlaf_feedback)
        if not success:
            print("[ORCHESTRATOR] AI Story failed. Cascading to Viral Remix fallback...")
            success, uploaded_short_title = execute_viral_remix(primary_mood, short_category, yt_short_profile, fb_short_profile, rlaf_feedback)
    elif content_mode == "remix":
        success, uploaded_short_title = execute_viral_remix(primary_mood, short_category, yt_short_profile, fb_short_profile, rlaf_feedback)
        if not success:
            print("[ORCHESTRATOR] Viral Remix failed. Cascading to AI Story fallback...")
            success, uploaded_short_title = execute_ai_story(primary_mood, short_category, yt_short_profile, fb_short_profile, rlaf_feedback)
    else:  # "auto" — adapt dynamically based on audience feedback & view velocity
        if preferred_format == "remix":
            print("[ORCHESTRATOR] Strategy: Executing Viral Download & AI Remix (High Velocity)...")
            success, uploaded_short_title = execute_viral_remix(primary_mood, short_category, yt_short_profile, fb_short_profile, rlaf_feedback)
            if not success:
                print("[ORCHESTRATOR] Viral Remix pool exhausted. Cascading to 100% AI Story Director...")
                success, uploaded_short_title = execute_ai_story(primary_mood, short_category, yt_short_profile, fb_short_profile, rlaf_feedback)
        else:
            print("[ORCHESTRATOR] Strategy: Executing 100% AI Story Director...")
            success, uploaded_short_title = execute_ai_story(primary_mood, short_category, yt_short_profile, fb_short_profile, rlaf_feedback)
            if not success:
                print("[ORCHESTRATOR] AI Story rendering failed. Cascading to Viral Download & AI Remix...")
                success, uploaded_short_title = execute_viral_remix(primary_mood, short_category, yt_short_profile, fb_short_profile, rlaf_feedback)

    # --- PHASE 3: MULTI-PLATFORM TELEGRAM NOTIFICATION ---
    try:
        upload_summary = {
            "short_title": uploaded_short_title or "Upload Failed (All Modes Exhausted)",
            "comp_title": f"Zero-Restriction Pipeline (Mode: {content_mode}, Executed: {uploaded_short_title[:30] if uploaded_short_title else 'None'})"
        }
        send_telegram_report(short_category, yt_short_profile, fb_profile=fb_short_profile, upload_summary=upload_summary)
    except Exception as e:
        print(f"Telegram report notification notice: {e}")

    # Clean up temp files
    cleanup()
    print("Pipeline finished successfully.")

if __name__ == "__main__":
    main()
