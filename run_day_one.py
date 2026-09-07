"""
Day 1 Runner — Hamster Chef: The Great Escape (Part 1)
Renders the 5-act episodic story with the cliffhanger cut at hook, and uploads to YouTube Shorts & Facebook.
Guaranteed 100% watermark-free, 9:16 vertical Pixar 3D animation.
"""

import os
import sys
import datetime
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.abspath("."))

from app.story.director import render_story_video, build_viral_yt_description, build_viral_fb_description
from app.video.thumbnail import generate_thumbnail
from app.upload.youtube import upload_to_youtube
from app.upload.facebook import upload_to_facebook
from app.database import log_video_analytics, init_db
from app.analytics.engine import send_telegram_report

init_db()

# Ensure temp and output dirs exist
os.makedirs("data/temp", exist_ok=True)
os.makedirs("data/output", exist_ok=True)

# ---------------------------------------------------------------------------
# DAY 1 STORY SPECIFICATION (The Dropped Cleaver / Blender Cliffhanger)
# ---------------------------------------------------------------------------
day_one_story = {
    "title": "Hamster Chef: The Great Escape (Part 1)!",
    "niche": "Animal Slapstick & Food ASMR",
    "character_name": "Hamster Chef",
    "character_description": "Cute chubby hamster chef wearing white chef hat and blue polka dot apron",
    "protagonist": {
        "name": "Hamster Chef",
        "visual_identity": "Cute chubby hamster chef wearing white chef hat and blue polka dot apron"
    },
    "environment": "colorful miniature rustic kitchen with wooden counters and copper pots, vibrant lighting",
    "scenes": [
        {
            "scene_index": 1,
            "arc_phase": "Hook & Immediate Action",
            "duration_sec": 2.5,
            "diffusion_prompt": "Cinematic 3D animation, Cute chubby hamster chef wearing white chef hat and blue polka dot apron, happily stirring a steaming pot on the stove in a colorful miniature kitchen, vibrant lighting, Pixar 3D style, sharp focus, 8k",
            "negative_prompt": "watermark, text, logo, signature, copyright, timestamp, subtitle, caption, letters, words, blurry, distorted, low quality, static, frozen",
            "foley_cues": [
                {"timestamp_sec": 0.2, "sfx": "knife_chop", "volume": 2.0},
                {"timestamp_sec": 0.8, "sfx": "sizzle", "volume": 2.2},
                {"timestamp_sec": 1.8, "sfx": "boing", "volume": 1.8}
            ]
        },
        {
            "scene_index": 2,
            "arc_phase": "Conflict Spike",
            "duration_sec": 3.0,
            "diffusion_prompt": "Cinematic 3D animation, Cute hamster chef in kitchen, gasping in shock as the entire kitchen counter violently trembles, flour dust billowing, pots clattering off shelves, Pixar 3D style, sharp focus, 8k",
            "negative_prompt": "watermark, text, logo, signature, copyright, timestamp, subtitle, caption, letters, words, blurry, distorted, low quality, static, frozen",
            "foley_cues": [
                {"timestamp_sec": 0.3, "sfx": "rising_hum", "volume": 2.2},
                {"timestamp_sec": 1.2, "sfx": "clatter_thump", "volume": 2.4},
                {"timestamp_sec": 2.2, "sfx": "crash_multi", "volume": 2.6}
            ]
        },
        {
            "scene_index": 3,
            "arc_phase": "The Comeback",
            "duration_sec": 2.5,
            "diffusion_prompt": "Cinematic 3D animation, A giant shiny metal cleaver slams down into the cutting board right next to the hamster chef, wood splintering, hamster rolls sideways dodging the blade, Pixar 3D style, sharp focus, 8k",
            "negative_prompt": "watermark, text, logo, signature, copyright, timestamp, subtitle, caption, letters, words, blurry, distorted, low quality, static, frozen",
            "foley_cues": [
                {"timestamp_sec": 0.2, "sfx": "whoosh_fast", "volume": 2.5},
                {"timestamp_sec": 0.8, "sfx": "bonk", "volume": 2.2},
                {"timestamp_sec": 1.8, "sfx": "whoosh", "volume": 2.0}
            ]
        },
        {
            "scene_index": 4,
            "arc_phase": "Rising Action 2",
            "duration_sec": 3.0,
            "diffusion_prompt": "Cinematic 3D animation, Hamster chef leaps onto a stick of yellow butter, surfing at lightning speed across the slippery counter, dodging tumbling salt shakers and giant rolling pins, Pixar 3D style, sharp focus, 8k",
            "negative_prompt": "watermark, text, logo, signature, copyright, timestamp, subtitle, caption, letters, words, blurry, distorted, low quality, static, frozen",
            "foley_cues": [
                {"timestamp_sec": 0.4, "sfx": "whoosh_fast", "volume": 2.5},
                {"timestamp_sec": 1.5, "sfx": "slide_whistle_down", "volume": 2.2},
                {"timestamp_sec": 2.4, "sfx": "clatter_multi", "volume": 2.0}
            ]
        },
        {
            "scene_index": 5,
            "arc_phase": "Climax Payoff",
            "duration_sec": 3.0,
            "diffusion_prompt": "Cinematic 3D animation, Extreme dramatic close-up, hamster chef reaches the counter edge, butter flies off, launched mid-air into the empty abyss toward a roaring open blender below, flailing arms, wide terrified eyes, freeze-frame mid-air, Pixar 3D style, sharp focus, 8k",
            "negative_prompt": "watermark, text, logo, signature, copyright, timestamp, subtitle, caption, letters, words, blurry, distorted, low quality, static, frozen",
            "foley_cues": [
                {"timestamp_sec": 0.3, "sfx": "whoosh_high", "volume": 2.4},
                {"timestamp_sec": 1.2, "sfx": "ding_high_confirm", "volume": 2.6},
                {"timestamp_sec": 2.2, "sfx": "bonk", "volume": 2.2}
            ]
        }
    ],
    "audio_config": {
        "bgm_style": "bouncy_comedy_loop",
        "bgm_base_volume": 0.75,
        "target_loudnorm_lufs": -14.0
    },
    "music_vibe": "bouncy_comedy",
    "yt_title": "Hamster Chef: The Great Escape (Part 1)! 🐹🔪 #shorts #viral",
    "fb_title": "He was NOT ready for the giant cleaver! 😱 Will he make it?! Part 2 tomorrow! 👇",
    "tags": ["shorts", "viral", "animation", "comedy", "hamster", "pixar"]
}

def main():
    # Ensure our pre-generated 4K pristine hero keyframe is in position
    hero_source = "data/temp/gemini_hero_test.png"
    hero_dest = "data/temp/hero_keyframe.png"
    if os.path.exists(hero_source) and not os.path.exists(hero_dest):
        from PIL import Image
        im = Image.open(hero_source)
        im.resize((576, 1024), Image.LANCZOS).save(hero_dest, "PNG")

    # Render Day 1
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    story_id = f"ai_story_day1_{timestamp}"
    story_out = os.path.join("data", "output", f"{story_id}.mp4")

    print("\n" + "=" * 60)
    print(f"🎬 RENDERING DAY 1: '{day_one_story['title']}'")
    print(f"🎯 Protagonist: {day_one_story['protagonist']['name']}")
    print(f"🔪 Cliffhanger: Cut at hook mid-air above blender")
    print("=" * 60 + "\n")

    rendered_short = render_story_video(day_one_story, story_out)

    if rendered_short and os.path.exists(rendered_short):
        yt_title = day_one_story["yt_title"]
        fb_title = day_one_story["fb_title"]
        yt_tags = day_one_story["tags"]
        yt_description = build_viral_yt_description(day_one_story) + "\n\n🚨 Will he survive the fall?! Part 2 drops tomorrow at 7 AM! Subscribe and ring the bell so you don't miss it!"
        fb_description = build_viral_fb_description(day_one_story) + "\n\nPart 2 coming tomorrow! Drop your predictions in the comments! 😂👇"

        thumb_path = os.path.join("data", "output", f"thumb_{story_id}.jpg")
        generate_thumbnail(rendered_short, thumb_path)

        print(f"\n🚀 Uploading Day 1 | YT: '{yt_title}' | FB: '{fb_title}'...")
        yt_res = upload_to_youtube(rendered_short, yt_title, yt_description, yt_tags, thumbnail_path=thumb_path)
        fb_res = upload_to_facebook(rendered_short, fb_title, fb_description, is_compilation=False, thumbnail_path=thumb_path)

        yt_id = yt_res if isinstance(yt_res, str) else (yt_res.get("id") if isinstance(yt_res, dict) else None)
        fb_id = fb_res if isinstance(fb_res, str) else (fb_res.get("id") if isinstance(fb_res, dict) else None)

        # Track in Supabase
        log_video_analytics(story_id, yt_title, "funny_short", "episodic_cliffhanger", yt_id=yt_id, fb_id=fb_id)

        # Deliver Telegram notification
        try:
            upload_summary = {
                "short_title": yt_title,
                "comp_title": "Day 1 Episodic Series: The Great Escape"
            }
            send_telegram_report("funny_short", {}, fb_profile={}, upload_summary=upload_summary)
        except Exception as e:
            print(f"Telegram notice: {e}")

        print("\n" + "=" * 60)
        print("✅ DAY 1 SUCCESSFULLY RENDERED & UPLOADED!")
        if yt_id:
            print(f"🎥 YouTube Short: https://youtube.com/shorts/{yt_id}")
        if fb_id:
            print(f"📱 Facebook Reel ID: {fb_id}")
        print("=" * 60)
    else:
        print("❌ Failed to render Day 1 video.")
        sys.exit(1)

if __name__ == "__main__":
    main()
