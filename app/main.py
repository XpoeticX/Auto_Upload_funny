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
from app.video.thumbnail import generate_thumbnail
from app.upload.youtube import upload_to_youtube
from app.upload.facebook import upload_to_facebook
from app.analytics.engine import fetch_and_update_metrics, run_meta_optimizer, get_active_profile, send_telegram_report

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
        
    # 1. Discover clips for Short using combined multi-platform discovery queries
    print(f"\n--- Phase 1: Scraping a pool of clips for the Individual Short ({short_category}) ---")
    custom_yt_queries = yt_short_profile.get("phase_1_discovery_directives", {}).get("primary_search_queries", [])
    custom_fb_queries = fb_short_profile.get("phase_1_discovery_directives", {}).get("primary_search_queries", [])
    combined_queries = list(dict.fromkeys(custom_yt_queries + custom_fb_queries))
    
    short_pool = []
    short_pool.extend(fetch_youtube(15, query_type=primary_mood, custom_queries=combined_queries))
    short_pool.extend(fetch_tiktok(15, query_type=primary_mood))
    short_pool.extend(fetch_imgur(15, query_type=primary_mood))
        
    print(f"Total Short Pool size built: {len(short_pool)} items (YouTube -> TikTok -> Imgur)")
        
    # 2. Discover clips for Compilation
    print(f"\n--- Phase 2: Scraping for Compilation ({long_category}) ---")
    long_compilation = fetch_long_compilation(query_type=primary_mood)
    comp_pool = []
    
    if not long_compilation:
        print("Falling back to downloading individual clips for merging...")
        custom_long_queries = list(dict.fromkeys(
            yt_long_profile.get("phase_1_discovery_directives", {}).get("primary_search_queries", []) +
            fb_long_profile.get("phase_1_discovery_directives", {}).get("primary_search_queries", [])
        ))
        comp_pool.extend(fetch_youtube(35, query_type=primary_mood, custom_queries=custom_long_queries))
        comp_pool.extend(fetch_tiktok(35, query_type=primary_mood))
        comp_pool.extend(fetch_imgur(35, query_type=primary_mood))
            
        print(f"Total Compilation Pool size built: {len(comp_pool)} items (YouTube -> TikTok -> Imgur)")
            
    # 3. Process the Individual Short (Stop after 1 success)
    print(f"\n--- Processing Individual Short ({short_category}) ---")
    short_success = False
    short_clip_id = None
    uploaded_short_title = None
    uploaded_comp_title = None
    
    for target_clip in short_pool:
        # HARD RULE: Verify link/ID in database before downloading
        if is_video_used(target_clip['id']):
            print(f"Skipping duplicate Short candidate: {target_clip['id']} (Already in DB)")
            continue
            
        print(f"\nEvaluating Short candidate: {target_clip['title']}")
        
        raw_video_path = os.path.join("data", "temp", f"raw_short_{target_clip['id']}.mp4")
        downloaded_path = download_video(target_clip["url"], raw_video_path)
        if not downloaded_path:
            continue
            
        try:
            probe = ffmpeg.probe(downloaded_path)
            clip_duration = float(probe['format']['duration'])
            if clip_duration > 180:
                print("Clip too long for a Short. Skipping (Max 3 minutes).")
                continue
        except Exception:
            pass
            
        ai_data = analyze_video_and_generate_script(downloaded_path, is_short=True, profile=yt_short_profile)
        if ai_data.get("rejected"):
            print(f"Skipping {target_clip['id']} because it was flagged as inappropriate, sad, or not engaging enough for a Short.")
            continue
            
        yt_title = ai_data.get("yt_title") or ai_data.get("title", "")
        fb_title = ai_data.get("fb_title") or ai_data.get("title", "")
        
        watermark_handle = "@DailyDosOfFun"
        final_video_path = os.path.join("data", "output", f"final_{target_clip['id']}.mp4")
        rendered_path = normalize_video(
            downloaded_path, final_video_path, is_short=True, 
            watermark_text=watermark_handle, 
            start_time=ai_data.get("hook_start", 0.0), 
            end_time=ai_data.get("hook_end")
        )
        
        if rendered_path:
            print(f"Uploading individual Short | YT: '{yt_title}' | FB: '{fb_title}'...")
            base_title = target_clip['title'].strip()
            
            # --- Dedicated YouTube Metadata ---
            yt_c_gate = yt_short_profile.get("phase_6_copywriting_directives", {})
            yt_cta = yt_c_gate.get("comment_cta") or "Which moment was your favorite? Drop a comment below! 👇"
            yt_hashtags = " ".join(yt_c_gate.get("hashtag_stack", [])) or "#shorts #viral #funny #reaction"
            yt_intro = yt_c_gate.get("description_intro") or f"In this quick Short, we react to: {base_title}!"
            yt_tags = yt_c_gate.get("tag_keywords") or ["shorts", "viral", "funny", "comedy", "reaction"]
            yt_description = f"""{yt_intro}\n\n💬 QUESTION: {yt_cta}\n\n🔔 SUBSCRIBE to Daily Dose of Fun for daily viral moments: https://www.youtube.com/@DailyDosOfFun-q2t\n📱 Follow our Official Facebook Page: https://www.facebook.com/profile.php?id=100077547189991\n\nVia {target_clip.get('source', 'Unknown')}\n{yt_hashtags}"""

            # --- Dedicated Facebook Metadata ---
            fb_c_gate = fb_short_profile.get("phase_6_copywriting_directives", {})
            fb_cta = fb_c_gate.get("comment_cta") or "Tag a friend who needs to see this! 😂👇"
            fb_hashtags = " ".join(fb_c_gate.get("hashtag_stack", [])) or "#reels #viral #comedy #epicfails"
            fb_intro = fb_c_gate.get("description_intro") or f"Wait till the end! 🤣 {base_title}"
            fb_description = f"""{fb_intro}\n\n💬 {fb_cta}\n\n📱 Follow Daily Dose of Fun for daily laughs: https://www.facebook.com/profile.php?id=100077547189991\n🔔 YouTube: https://www.youtube.com/@DailyDosOfFun-q2t\n\n{fb_hashtags}"""
                
            thumb_path = os.path.join("data", "output", f"thumb_{target_clip['id']}.jpg")
            generate_thumbnail(rendered_path, thumb_path)
            
            yt_res = upload_to_youtube(rendered_path, yt_title, yt_description, yt_tags, thumbnail_path=thumb_path)
            fb_res = upload_to_facebook(rendered_path, fb_title, fb_description, is_compilation=False, thumbnail_path=thumb_path)
            
            # Log metrics tracking into Supabase with short_category tag
            log_video_analytics(
                video_id=target_clip['id'],
                title=yt_title,
                category=short_category,
                hook_style=target_clip.get('source', 'Short'),
                yt_id=str(yt_res) if yt_res and str(yt_res) != "True" else None,
                fb_id=str(fb_res) if fb_res and str(fb_res) != "True" else None
            )
            
            mark_video_used(target_clip['id'], target_clip['title'])
            short_clip_id = target_clip['id']
            uploaded_short_title = f"YT: '{yt_title}' | FB: '{fb_title}'"
            short_success = True
            break  # Stop after 1 successful short
            
    if not short_success:
        print("Warning: Failed to upload any Short after exhausting the pool.")
        
    # 4. Process Compilation
    print("\n--- Processing Compilation ---")
    
    merged_path = None
    comp_title = "Incredible Compilation Video! 😂"
    comp_description = ""
    
    if long_compilation:
        if is_video_used(long_compilation['id']):
            print(f"Skipping duplicate Long Compilation: {long_compilation['id']} (Already in DB)")
            long_compilation = None
        else:
            print(f"\nEvaluating Single Long Compilation: {long_compilation['title']}")
            raw_video_path = os.path.join("data", "temp", f"raw_long_comp_{long_compilation['id']}.mp4")
            downloaded_path = download_video(long_compilation["url"], raw_video_path)
            
            if downloaded_path:
                comp_title = f"{long_compilation['title']} (Best Moments)"
                normalized_path = os.path.join("data", "output", f"norm_long_comp_{long_compilation['id']}.mp4")
                if normalize_video(downloaded_path, normalized_path, is_short=False, watermark_text=watermark_handle):
                    merged_path = normalized_path
                    try:
                        mark_video_used(long_compilation['id'], long_compilation['title'])
                    except Exception:
                        pass
                else:
                    print("Failed to normalize long compilation.")
    
    # Fallback to merging individual clips if long_compilation failed or wasn't found
    if not merged_path:
        if not comp_pool:
            print("\n--- Long Compilation unavailable/blocked. Gathering individual clips to build compilation ---")
            if is_pm_run:
                comp_pool.extend(fetch_tiktok(35, query_type=primary_mood))
                comp_pool.extend(fetch_imgur(35, query_type=primary_mood))
                comp_pool.extend(fetch_youtube(35, query_type=primary_mood))
            else:
                comp_pool.extend(fetch_tiktok(35, query_type="muslim couple hijab romance"))
                comp_pool.extend(fetch_imgur(35, query_type=primary_mood))
                comp_pool.extend(fetch_youtube(35, query_type="ytsearch35:muslim couple goals hijab romance shorts"))
            print(f"Total Compilation Pool size built: {len(comp_pool)} items (TikTok -> Imgur -> YouTube)")
            
        processed_compilation_shorts = []
        compilation_titles = []
        total_duration = 0.0
        TARGET_CLIPS = 3  # Fast, viral, and high-retention: 3 punchy clips
        CLIP_MAX_DURATION = 16.0  # 12-16s per clip
        
        for target_clip in comp_pool:
            if len(processed_compilation_shorts) >= TARGET_CLIPS:
                print(f"Successfully gathered {TARGET_CLIPS} viral clips for compilation! (Total: {total_duration:.1f}s)")
                break
                
            if 'short_clip_id' in locals() and short_clip_id and target_clip['id'] == short_clip_id:
                print(f"Skipping {target_clip['id']} because it was already used for the Individual Short.")
                continue
                
            # HARD RULE: Verify link/ID in database before downloading compilation clip
            if is_video_used(target_clip['id']):
                print(f"Skipping duplicate Compilation candidate: {target_clip['id']} (Already in DB)")
                continue
                
            print(f"\nEvaluating Compilation candidate: {target_clip['title']}")
            raw_video_path = os.path.join("data", "temp", f"raw_comp_{target_clip['id']}.mp4")
            downloaded_path = download_video(target_clip["url"], raw_video_path)
            if not downloaded_path:
                continue
                
            try:
                probe = ffmpeg.probe(downloaded_path)
                clip_duration = float(probe['format']['duration'])
                if clip_duration < 4.0:
                    print("Clip too short. Skipping.")
                    continue
                if total_duration + min(clip_duration, CLIP_MAX_DURATION) > MAX_DURATION:
                    print("Adding this clip would exceed the 15-minute limit. Skipping.")
                    continue
            except Exception:
                clip_duration = 15.0
                
            ai_data = analyze_video_and_generate_script(downloaded_path, profile=long_profile)
            if ai_data.get("rejected"):
                print(f"Skipping {target_clip['id']} because it was flagged as inappropriate or sad.")
                continue
                
            # Between clips: generate an animated meme transition poster clip so viewers know it's a new video
            if processed_compilation_shorts:
                frame_path = os.path.join("data", "temp", f"frame_{target_clip['id']}.jpg")
                extract_frame(downloaded_path, frame_path, timestamp=1.0)
                
                trans_clip_path = os.path.join("data", "output", f"trans_{len(processed_compilation_shorts)}_{target_clip['id']}.mp4")
                caption = ai_data.get("meme_caption") or "Wait till you see what happens next! 😂"
                create_meme_transition_clip(caption=caption, output_path=trans_clip_path, duration=1.5, previous_frame_path=frame_path)
                
                if os.path.exists(trans_clip_path):
                    processed_compilation_shorts.append(trans_clip_path)
                    total_duration += 1.5
                
            # Standardize clip to 15-20s max duration maintaining native 9:16 aspect ratio
            normalized_path = os.path.join("data", "output", f"norm_{target_clip['id']}.mp4")
            if normalize_video(
                downloaded_path, normalized_path, is_short=False, 
                max_duration=CLIP_MAX_DURATION, watermark_text=watermark_handle,
                start_time=ai_data.get("hook_start", 0.0),
                end_time=ai_data.get("hook_end")
            ):
                processed_compilation_shorts.append(normalized_path)
                if ai_data.get("title"):
                    compilation_titles.append(ai_data["title"])
                total_duration += min(clip_duration, CLIP_MAX_DURATION)
                try:
                    mark_video_used(target_clip['id'], target_clip['title'])
                except Exception:
                    pass
            else:
                print(f"Failed to normalize {target_clip['id']}. Skipping.")
                
        if len(processed_compilation_shorts) > 1:
            print(f"\n--- Creating Compilation Video with Meme Transition Hooks ({long_category}) ---")
            compilation_path = os.path.join("data", "output", "compilation.mp4")
            merged_path = merge_compilation(processed_compilation_shorts, compilation_path)
            if merged_path:
                yt_comp_title, yt_summary = generate_compilation_details(compilation_titles, mood=primary_mood, profile=yt_long_profile)
                fb_comp_title, fb_summary = generate_compilation_details(compilation_titles, mood=primary_mood, profile=fb_long_profile)
                
                # --- Dedicated YouTube Compilation Description ---
                yt_comp_description = f"""{yt_summary}\n\n🏆 WHICH CLIP WAS YOUR FAVORITE? Drop your vote in the comments below! 👇\n\n🔔 NEVER MISS A LAUGH: Subscribe & tap the bell for daily compilations: https://www.youtube.com/@DailyDosOfFun-q2t\n📱 FOLLOW OUR FACEBOOK PAGE: https://www.facebook.com/profile.php?id=100077547189991\n\n#funny #epicfails #meme #compilation #reaction #comedy #viral #laugh #trynottolaugh #bestof #trending"""
                yt_comp_tags = ["funny", "epic fails", "meme", "compilation", "reaction", "comedy", "viral", "laugh", "try not to laugh", "best of", "relatable fails"]

                # --- Dedicated Facebook Compilation Description ---
                fb_comp_description = f"""{fb_summary}\n\n💬 Which clip made you laugh the hardest? Tag a friend who needs to watch this! 😂👇\n\n📱 Follow Daily Dose of Fun for daily viral moments: https://www.facebook.com/profile.php?id=100077547189991\n🔔 YouTube: https://www.youtube.com/@DailyDosOfFun-q2t\n\n#reels #funnyreels #epicfails #viralpost #comedy"""

    # 5. Upload the final Compilation Video
    if merged_path:
        comp_thumb_path = os.path.join("data", "output", "comp_thumb.jpg")
        generate_thumbnail(merged_path, comp_thumb_path)
        
        comp_yt_res = upload_to_youtube(merged_path, yt_comp_title, yt_comp_description, yt_comp_tags, thumbnail_path=comp_thumb_path)
        comp_fb_res = upload_to_facebook(merged_path, fb_comp_title, fb_comp_description, is_compilation=True, thumbnail_path=comp_thumb_path)
        uploaded_comp_title = f"YT: '{yt_comp_title}'\n  • FB: '{fb_comp_title}'"
        
        log_video_analytics(
            video_id=f"comp_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}",
            title=yt_comp_title,
            category=long_category,
            hook_style="Compilation",
            yt_id=str(comp_yt_res) if comp_yt_res and str(comp_yt_res) != "True" else None,
            fb_id=str(comp_fb_res) if comp_fb_res and str(comp_fb_res) != "True" else None
        )
            
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
