import os
import json
import time
import subprocess
import shutil
from typing import Dict, List, Optional
from pydantic import BaseModel, Field
from google import genai
from app.video.ai_diffusion import generate_ai_video_from_prompt, animate_image_to_video
from app.analytics.engine import get_rlaf_ai_feedback
from app.story.audio_director import build_scene_audio_timeline

class StoryScene(BaseModel):
    scene_number: int
    act_name: str # Setup, Conflict/Chaos, Punchline/Payoff
    visual_prompt: str # High-detail prompt for video diffusion
    foley_sound_type: str # knife_chop, sizzle, crunch, meow, ding, splash, bonk, whoosh
    foley_description: str

class ViralStoryScript(BaseModel):
    title: str
    niche: str # e.g. "Cat Comedy", "Animal Duo", "Epic Fail", "Food ASMR", "Fantasy Comedy"
    character_name: str
    character_description: str # Master description for visual consistency
    scenes: List[StoryScene]
    music_vibe: str # bouncy_comedy, sneaky, triumphant
    yt_title: str
    fb_title: str
    tags: List[str]

FALLBACK_CONCEPTS = [
    {
        "title": "Chef Leo's Crispy Chicken",
        "niche": "Cat Comedy",
        "character_name": "Chef Leo",
        "character_description": "Chubby ginger cat wearing a white chef toque and headphones, 3d pixar animation style",
        "scenes": [
            {
                "scene_number": 1,
                "act_name": "Setup",
                "visual_prompt": "Chubby orange cat chef chopping raw chicken on wooden cutting board, knife slicing rapidly, flour flying, 3d pixar style",
                "foley_sound_type": "knife_chop",
                "foley_description": "Rapid rhythmic wooden board knife chops"
            },
            {
                "scene_number": 2,
                "act_name": "Conflict",
                "visual_prompt": "Orange cat chef pan-frying at gas stove, thick steam billowing, flames flickering, focused intense facial expression",
                "foley_sound_type": "sizzle",
                "foley_description": "Deep hot oil frying pan sizzle"
            },
            {
                "scene_number": 3,
                "act_name": "Payoff",
                "visual_prompt": "Orange cat chef devouring giant crispy fried chicken drumstick, mouth chewing, crumbs flying, big joyful cartoon smile",
                "foley_sound_type": "crunch",
                "foley_description": "Crispy chicken crunch and ending service bell ding"
            }
        ],
        "music_vibe": "bouncy_comedy",
        "yt_title": "Chef Leo Cooks A Masterpiece! 🍗🐾 #shorts #viral #funnycats",
        "fb_title": "He took his cooking shift WAY too seriously! 😂🍗 Tag someone who loves fried chicken!",
        "tags": ["shorts", "funnycats", "animation", "3danimation", "food", "viral", "comedy"]
    },
    {
        "title": "The Cat & The Little Duckling",
        "niche": "Animal Duo",
        "character_name": "Boss Leo & Duckie",
        "character_description": "Fat orange cat with gold chain and tiny cute yellow duckling, 3d cartoon animation",
        "scenes": [
            {
                "scene_number": 1,
                "act_name": "Setup",
                "visual_prompt": "Fat orange cat wearing gold chain walking through meadow holding wooden stick alongside tiny cute baby duck, cartoon 3d",
                "foley_sound_type": "footsteps",
                "foley_description": "Playful cartoon footsteps and happy quack"
            },
            {
                "scene_number": 2,
                "act_name": "Conflict",
                "visual_prompt": "Orange cat heroically swinging wooden stick in kung fu stance to protect baby duck, dynamic action camera, cartoon 3d",
                "foley_sound_type": "whoosh",
                "foley_description": "Dramatic stick whoosh and cartoon bonk"
            },
            {
                "scene_number": 3,
                "act_name": "Payoff",
                "visual_prompt": "Orange cat wearing dark sunglasses driving a mini motorcycle with baby duck in front basket, speeding down road, cartoon 3d",
                "foley_sound_type": "motorcycle",
                "foley_description": "Motorcycle engine rev and cool beat drop"
            }
        ],
        "music_vibe": "triumphant",
        "yt_title": "The Most Badass Duo In History! 🐱🦆😎 #shorts #viral #animation",
        "fb_title": "Nobody messes with his little bro! 😎🏍️ Tag your best friend!",
        "tags": ["shorts", "funny", "cat", "duck", "3danimation", "viral", "friendship"]
    }
]

def generate_viral_story_concept(rlaf_feedback: Optional[Dict] = None) -> Dict:
    """
    Uses Gemini to autonomously brainstorm and plan a 3-act viral AI short story
    based on real audience feedback, high-performing topics, and watch time signals.
    """
    api_keys = [
        os.environ.get("GEMINI_API_KEY"),
        os.environ.get("GEMINI_API_KEY_2"),
        os.environ.get("GEMINI_API_KEY_3"),
    ]
    api_keys = [k for k in api_keys if k and str(k).strip() != "None"]

    feedback_context = ""
    if rlaf_feedback:
        summary = rlaf_feedback.get("summary", "")
        top_cats = rlaf_feedback.get("top_categories", [])
        feedback_context = f"\nPerformance Feedback from previous uploads:\n- Summary: {summary}\n- Top Performing Categories: {top_cats}\nUse this feedback to double down on what gets highest views!"

    prompt = f"""You are the Executive Creative Director for viral AI animated YouTube Shorts and Facebook Reels (like Manoranjan Tales with 200M+ views).
Your goal is to design a high-retention 3-Act Mini-Story (8 to 10 seconds total) that has:
1. Universal visual humor (ZERO spoken voiceover / dialogue).
2. Exactly 3 interconnected visual scenes:
   - Act 1 (Setup / Hook: 0s-3s): Introduce adorable or absurd character situation.
   - Act 2 (Conflict / Chaos: 3s-6s): A sudden mistake, intense effort, near-disaster, or action.
   - Act 3 (Payoff / Punchline: 6s-9s): A hilarious twist, triumphant boss moment, or funny fail resolution.
3. Character consistency across all 3 scenes.
4. Specific Foley sound effect requirements for each scene (e.g. knife chops, sizzle, crunch, whoosh, engine rev, meow).

Explore across high-retention genres:
- Cute animal comedy (cats, dogs, ducklings, hamsters)
- Food & Cooking ASMR disasters
- Unlikely animal friendships
- Epic slapstick fails & instant regret
- Heroic boss moments with sunglasses & cool phonk/bouncy beats

{feedback_context}

Return valid JSON conforming strictly to the ViralStoryScript schema.
"""

    for k in api_keys:
        try:
            client = genai.Client(api_key=k)
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "response_schema": ViralStoryScript
                }
            )
            data = json.loads(response.text)
            print(f"[STORY DIRECTOR] Conceived new story via Gemini: '{data.get('title')}' in niche '{data.get('niche')}'")
            return data
        except Exception as e:
            print(f"[STORY DIRECTOR] Gemini notice: {e}")

    # Fallback to Hugging Face Qwen-72B Autonomous Brainstorming
    hf_token = os.environ.get("HF_TOKEN")
    if hf_token:
        try:
            from huggingface_hub import InferenceClient
            import re
            hf_client = InferenceClient(api_key=hf_token)
            hf_prompt = prompt + "\nOutput strictly valid JSON with keys: title, niche, character_name, character_description, scenes (with scene_number, act_name, visual_prompt, foley_sound_type, foley_description), music_vibe, yt_title, fb_title, tags. No markdown formatting."
            res = hf_client.chat.completions.create(
                messages=[{"role": "user", "content": hf_prompt}],
                model="Qwen/Qwen2.5-72B-Instruct",
                max_tokens=1200,
                temperature=0.85
            )
            raw = res.choices[0].message.content.strip()
            raw = re.sub(r"^```json\s*", "", raw)
            raw = re.sub(r"^```\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
            data = json.loads(raw.strip())
            print(f"[STORY DIRECTOR] Conceived new story via Qwen-72B: '{data.get('title')}' in niche '{data.get('niche')}'")
            return data
        except Exception as e:
            print(f"[STORY DIRECTOR] Hugging Face Qwen-72B notice: {e}")

    import random
    chosen = random.choice(FALLBACK_CONCEPTS)
    print(f"[STORY DIRECTOR] Using curated viral concept: '{chosen['title']}'")
    return chosen

def render_story_video(story: Dict, output_path: str) -> Optional[str]:
    """
    Renders the 3-act story into a complete 1080x1920 Short:
    - Generates 3 real AI video diffusion scenes.
    - Synchronizes real Foley sound effects for each scene.
    - Adds ducked comedy background music.
    - Concatenates and encodes final high-bitrate MP4.
    """
    os.makedirs("data/temp", exist_ok=True)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    scenes = story.get("scenes", [])
    if len(scenes) < 3:
        print("[STORY DIRECTOR] Error: Story must have at least 3 scenes.")
        return None

    rendered_scene_vids = []

    for sc in scenes:
        num = sc.get("scene_number", 1)
        p = sc.get("visual_prompt", "")
        sc_out = os.path.join("data", "temp", f"story_scene_{num}.mp4")

        print(f"[STORY DIRECTOR] Generating Scene {num} ({sc.get('act_name')}): {p[:60]}...")
        vid_path = generate_ai_video_from_prompt(p, sc_out, duration=3)
        if not vid_path or not os.path.exists(vid_path):
            print(f"[STORY DIRECTOR] Warning: Scene {num} generation issue. Retrying with fallback...")
            # Fallback to existing valid neural scenes if available
            fallback_map = {
                1: "data/output/real_ai_cat_chef.mp4",
                2: "data/temp/scene2_real_motion.mp4",
                3: "data/temp/scene3_real_motion.mp4"
            }
            fb_path = fallback_map.get(num)
            if fb_path and os.path.exists(fb_path):
                shutil.copy2(fb_path, sc_out)
                vid_path = sc_out
            else:
                return None

        # Format scene to 1080x1920 30fps
        sc_fmt = os.path.join("data", "temp", f"story_scene_{num}_fmt.mp4")
        subprocess.run([
            "ffmpeg", "-y", "-i", vid_path,
            "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
            "-t", "2.8" if num < 3 else "3.0", "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", sc_fmt
        ], check=True)
        rendered_scene_vids.append(sc_fmt)

    # Concatenate video scenes
    concat_txt = "data/temp/director_concat.txt"
    with open(concat_txt, "w") as f:
        for v in rendered_scene_vids:
            f.write(f"file '{os.path.abspath(v).replace(chr(92), '/')}'\n")

    visual_only = "data/temp/director_visual.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_txt,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", visual_only
    ], check=True)

    # Dynamic Foley & Music Generation tailored to this specific story
    master_audio = os.path.join("data", "temp", "story_master_audio.wav")
    total_dur = 2.8 * (len(scenes) - 1) + 3.0
    build_scene_audio_timeline(story, total_duration=total_dur, output_wav=master_audio)

    cmd_mux = [
        "ffmpeg", "-y",
        "-i", visual_only,
        "-i", master_audio,
        "-map", "0:v", "-map", "1:a",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "256k",
        "-shortest",
        output_path
    ]
    subprocess.run(cmd_mux, check=True)

    if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
        print(f"[STORY DIRECTOR] Successfully rendered 3-scene story: {output_path}")
        return output_path
    return None
