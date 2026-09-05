import os
import shutil
import datetime
import ffmpeg
from app.database import init_db, mark_video_used, is_video_used, log_video_analytics
from app.discovery.youtube_scraper import fetch_top_clips as fetch_youtube, fetch_long_compilation
from app.discovery.tiktok_scraper import fetch_tiktok
from app.discovery.imgur_scraper import fetch_top_clips as fetch_imgur
from app.discovery.downloader import download_video
from app.ai.vision import analyze_video_and_generate_script, generate_compilation_details, generate_compilation_title
from app.video.editor import normalize_video, merge_compilation, create_meme_transition_clip, extract_frame
from app.ai.generator import generate_ai_dilemmas
from app.video.ai_generator import create_dilemma_video, create_dilemma_compilation
from app.ai.narrator import generate_ai_narration
from app.video.remix_engine import transform_video_with_ai
from app.video.thumbnail import generate_thumbnail
from app.upload.youtube import upload_to_youtube
from app.upload.facebook import upload_to_facebook
from app.analytics.engine import fetch_and_update_metrics, run_meta_optimizer, get_active_profile, send_telegram_report, get_rlaf_ai_feedback
from app.story.director import generate_viral_story_concept, render_story_video

def cleanup():
    print("Cleaning up temp folders...")
    for d in ["data/temp", "data/output"]:
        if os.path.exists(d):
            shutil.rmtree(d)
        os.makedirs(d, exist_ok=True)

def main():
    print("--- Starting Funny Video Automation Pipeline ---")
    
    # Ensure working directory is project root
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    cleanup()
    init_db()
    
    current_hour = datetime.datetime.now(datetime.timezone.utc).hour
    is_pm_run = (12 <= current_hour <= 20) # 14:00 UTC is PM run (8:00 PM BST), 01:00 UTC is AM run (7:00 AM BST)
    
    env_category = os.environ.get("CONTENT_CATEGORY") or os.environ.get("PRIMARY_MOOD")
    if env_category:
        primary_mood = env_category.lower().strip()
        print(f"Content Category Override: {primary_mood.upper()}")
    elif is_pm_run:
        print("Schedule: PM Run (08:00 PM BST) -> ALL Content is FUNNY (Epic Fails)")
        primary_mood = "funny"
    else:
        print("Schedule: AM Run (07:00 AM BST) -> ALL Content is ROMANTIC")
        primary_mood = "romantic"
        
    short_category = f"{primary_mood}_short"
    long_category = f"{primary_mood}_long"

    # --- PHASE 8: DECOUPLED PLATFORM RLAF OPTIMIZERS ---
    try:
        fetch_and_update_metrics()
        yt_short_profile = run_meta_optimizer(short_category, platform="youtube")
        fb_short_profile = run_meta_optimizer(short_category, platform="facebook")
        yt_long_profile = run_meta_optimizer(long_category, platform="youtube")
        fb_long_profile = run_meta_optimizer(long_category, platform="facebook")
        print(f"Loaded YouTube Directives: {yt_short_profile.get('agent_evaluation', {}).get('strategy_mode', 'Active')}")
        print(f"Loaded Facebook Directives: {fb_short_profile.get('agent_evaluation', {}).get('strategy_mode', 'Active')}")
    except Exception as e:
        print(f"Feedback engine notice ({e}). Using baseline profiles.")
        yt_short_profile = get_active_profile(short_category, platform="youtube")
        fb_short_profile = get_active_profile(short_category, platform="facebook")
        yt_long_profile = get_active_profile(long_category, platform="youtube")
        fb_long_profile = get_active_profile(long_category, platform="facebook")
        
    # --- PHASE 1: GENERATE VIRAL AI DILEMMAS WITH RLAF ADAPTATION ---
    print(f"\n--- Phase 1: Generating 100% AI Dilemmas ({primary_mood}) ---")
    rlaf_feedback = get_rlaf_ai_feedback()
    dilemmas = generate_ai_dilemmas(theme=primary_mood, count=4, rlaf_feedback=rlaf_feedback)
    short_dilemma = dilemmas[0]
    comp_dilemmas = dilemmas[1:4]
    
    uploaded_short_title = None
    uploaded_comp_title = None
    
    # --- PHASE 2: 100% REAL AI 3-ACT STORY GENERATION (RLAF DECIDED + NEURAL MOTION + DYNAMIC FOLEY & MUSIC) ---
    print(f"\n--- Phase 2: Autonomous AI Story Generation (RLAF Steered: {primary_mood}) ---")
    story_concept = generate_viral_story_concept(rlaf_feedback=rlaf_feedback)
    story_id = f"story_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    story_out = os.path.join("data", "output", f"{story_id}.mp4")

    rendered_short = render_story_video(story_concept, story_out)
    remix_success = False
    if rendered_short and os.path.exists(rendered_short):
        yt_title = story_concept.get("yt_title", f"{story_concept.get('title')} 🐾😂 #shorts #viral")
        fb_title = story_concept.get("fb_title", f"Wait till the end! 😂 Tag someone who needs to see this!")
        yt_tags = story_concept.get("tags") or ["shorts", "viral", "animation", "comedy"]
        yt_hashtags = " ".join([f"#{t}" for t in yt_tags[:5]])
        yt_description = f"""{yt_title}\n\n💬 {fb_title}\n\n🔔 SUBSCRIBE to Daily Dose of Fun for daily laughs: https://www.youtube.com/@DailyDosOfFun-q2t\n📱 Follow on Facebook: https://www.facebook.com/profile.php?id=100077547189991\n\n{yt_hashtags}"""
        fb_description = f"""{fb_title}\n\n📱 Follow Daily Dose of Fun for daily viral moments: https://www.facebook.com/profile.php?id=100077547189991\n🔔 YouTube: https://www.youtube.com/@DailyDosOfFun-q2t\n\n#reels #funnyreels #viral #animation #comedy"""
        
        thumb_path = os.path.join("data", "output", f"thumb_{story_id}.jpg")
        generate_thumbnail(rendered_short, thumb_path)
        
        print(f"Uploading 100% AI Story Short | YT: '{yt_title}' | FB: '{fb_title}'...")
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
        remix_success = True

    # Fail-safe Fallback: If scraper pool was empty or blocked, generate 100% AI Dilemma Short
    if not remix_success:
        print("\nScraper pool exhausted. Triggering AI Dilemma Short Engine as fail-safe...")
        short_id = f"ai_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
        short_path = os.path.join("data", "output", f"short_{short_id}.mp4")
        rendered_short = create_dilemma_video(short_dilemma, short_path)
        
        if rendered_short and os.path.exists(rendered_short):
            yt_title = short_dilemma.get("yt_title", "Would You Rather? ⚡ #shorts #viral")
            fb_title = short_dilemma.get("fb_title", "Which one are you choosing? Be honest! 😂👇")
            yt_tags = short_dilemma.get("tags") or ["shorts", "wouldyourather", "dilemma", "viral"]
            yt_hashtags = " ".join([f"#{t}" for t in yt_tags[:5]])
            yt_description = f"""⚡ {short_dilemma.get('topic')}!\n\n💬 {yt_title}\n\n🔔 SUBSCRIBE: https://www.youtube.com/@DailyDosOfFun-q2t\n📱 Follow on Facebook: https://www.facebook.com/profile.php?id=100077547189991\n\n{yt_hashtags}"""
            fb_description = f"""⚡ {short_dilemma.get('topic')}\n\n💬 {fb_title}\n\n#reels #wouldyourather #viral"""
            
            thumb_path = os.path.join("data", "output", f"thumb_{short_id}.jpg")
            generate_thumbnail(rendered_short, thumb_path)
            
            yt_res = upload_to_youtube(rendered_short, yt_title, yt_description, yt_tags, thumbnail_path=thumb_path)
            fb_res = upload_to_facebook(rendered_short, fb_title, fb_description, is_compilation=False, thumbnail_path=thumb_path)
            
            log_video_analytics(
                video_id=short_id,
                title=yt_title,
                category=short_category,
                hook_style="AI_Dilemma",
                yt_id=str(yt_res) if yt_res and str(yt_res) != "True" else None,
                fb_id=str(fb_res) if fb_res and str(fb_res) != "True" else None
            )
            uploaded_short_title = f"YT: '{yt_title}' | FB: '{fb_title}'"

    # --- PHASE 3: RENDER & UPLOAD 3-ROUND COMPILATION ---
    print("\n--- Phase 3: Rendering 3-Round Showdown Compilation ---")
    comp_id = f"comp_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    comp_path = os.path.join("data", "output", f"comp_{comp_id}.mp4")
    rendered_comp = create_dilemma_compilation(comp_dilemmas, comp_path)
    
    if rendered_comp and os.path.exists(rendered_comp):
        yt_comp_title = f"The Ultimate Dilemma Showdown! ⚡ 3 Impossible Choices! #shorts #viral"
        fb_comp_title = f"3 Impossible Decisions: How many did you agree with? 😂👇"
        
        yt_comp_desc = f"""🔥 3 ROUNDS OF IMPOSSIBLE CHOICES! Which ones did you pick?\n\n🏆 Drop your score in the comments below! 👇\n\n🔔 SUBSCRIBE: https://www.youtube.com/@DailyDosOfFun-q2t\n📱 Follow on Facebook: https://www.facebook.com/profile.php?id=100077547189991\n\n#shorts #wouldyourather #challenge #viral"""
        fb_comp_desc = f"""🔥 3 Rounds of Impossible Dilemmas! Tag a friend to see if you agree on any of these! 😂👇\n\n📱 Follow on Facebook: https://www.facebook.com/profile.php?id=100077547189991\n🔔 YouTube: https://www.youtube.com/@DailyDosOfFun-q2t\n\n#reels #wouldyourather #viralreels"""
        
        comp_tags = ["shorts", "wouldyourather", "compilation", "challenge", "viral", "quiz"]
        comp_thumb_path = os.path.join("data", "output", f"comp_thumb_{comp_id}.jpg")
        generate_thumbnail(rendered_comp, comp_thumb_path)
        
        print(f"Uploading AI Compilation | YT: '{yt_comp_title}' | FB: '{fb_comp_title}'...")
        comp_yt_res = upload_to_youtube(rendered_comp, yt_comp_title, yt_comp_desc, comp_tags, thumbnail_path=comp_thumb_path)
        comp_fb_res = upload_to_facebook(rendered_comp, fb_comp_title, fb_comp_desc, is_compilation=True, thumbnail_path=comp_thumb_path)
        
        log_video_analytics(
            video_id=comp_id,
            title=yt_comp_title,
            category=long_category,
            hook_style="AI_Compilation",
            yt_id=str(comp_yt_res) if comp_yt_res and str(comp_yt_res) != "True" else None,
            fb_id=str(comp_fb_res) if comp_fb_res and str(comp_fb_res) != "True" else None
        )
        uploaded_comp_title = f"YT: '{yt_comp_title}'\n  • FB: '{fb_comp_title}'"
            
    # 6. Send Decoupled Multi-Platform Telegram Report
    try:
        upload_summary = {
            "short_title": uploaded_short_title or "Not Uploaded (Pool Exhausted)",
            "comp_title": uploaded_comp_title or "Not Uploaded (Single Short Mode)"
        }
        send_telegram_report(primary_mood, yt_short_profile, fb_profile=fb_short_profile, upload_summary=upload_summary)
    except Exception as e:
        print(f"Telegram report notification notice: {e}")

    # Clean up large files
    cleanup()
    print("Pipeline finished.")

if __name__ == "__main__":
    main()
