import os
import json
import time
import subprocess
import shutil
import re
from typing import Dict, List, Optional
from pydantic import BaseModel, Field
from google import genai
from app.video.ai_diffusion import generate_ai_video_from_prompt, animate_image_to_video
from app.analytics.engine import get_rlaf_ai_feedback
from app.story.audio_director import build_scene_audio_timeline

class StoryScene(BaseModel):
    scene_number: int
    act_name: str # "Hook -> Conflict", "The Comeback", "Climax Payoff" (Jack Craig Conflict Arc)
    visual_prompt: str # High-detail prompt for video diffusion
    foley_sound_type: str # knife_chop, sizzle, crunch, meow, ding, splash, bonk, whoosh, boing
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
    related_queries: Optional[List[str]] = None

FALLBACK_CONCEPTS = [
    {
        "title": "Shark Chef's Sneaker Recipe",
        "niche": "Surreal Animal Comedy",
        "character_name": "Chef Jaws",
        "character_description": "Muscular anthropomorphic shark wearing a chef apron in a luxury kitchen, hyper-detailed 3d pixar CGI, vivid cinematic lighting",
        "scenes": [
            {
                "scene_number": 1,
                "act_name": "Hook -> Conflict",
                "visual_prompt": "Muscular shark chef chopping a colorful Nike sneaker on cutting board, shoe laces suddenly snap back and knock his chef hat into a flaming stove, 3d pixar animation",
                "foley_sound_type": "knife_chop",
                "foley_description": "Rapid wooden cutting board knife chops and sudden snap"
            },
            {
                "scene_number": 2,
                "act_name": "The Comeback",
                "visual_prompt": "Shark chef grins fiercely with sharp teeth, pulls out dual glowing cleavers, and dices the flying sneaker pieces in mid-air with lightning speed, 3d animation",
                "foley_sound_type": "whoosh",
                "foley_description": "Fast acrobatic blade whooshes and wok catch"
            },
            {
                "scene_number": 3,
                "act_name": "Climax Payoff",
                "visual_prompt": "Shark chef proudly presents a gourmet sneaker burger on golden platter with ketchup drizzle, sparkling clean kitchen, triumph boss pose, 3d pixar style",
                "foley_sound_type": "ding",
                "foley_description": "Triumph presentation bell ding"
            }
        ],
        "music_vibe": "bouncy_comedy",
        "yt_title": "Who Let The Shark In The Kitchen?! 🦈👟 #shorts #viral #funny",
        "fb_title": "His cooking skills are 10/10 but the recipe is questionable! 😂🦈 Tag a friend who would eat this!",
        "tags": ["shorts", "shark", "animation", "3danimation", "food", "viral", "comedy", "funny"]
    },
    {
        "title": "Baby & The Dancing Mini Cow",
        "niche": "Cute Baby & Animal Adventure",
        "character_name": "Baby Leo & Daisy the Cow",
        "character_description": "Chubby laughing cute baby in diaper riding a tiny spotted miniature dairy cow, 3d pixar animation style, soft warm sunlit garden",
        "scenes": [
            {
                "scene_number": 1,
                "act_name": "Hook -> Conflict",
                "visual_prompt": "Adorable chubby baby in diaper riding mini dairy cow on flower path, cow suddenly skids towards a giant messy mud puddle, baby eyes wide open in shock, 3d pixar animation",
                "foley_sound_type": "whoosh",
                "foley_description": "Playful trot into sudden skid sound"
            },
            {
                "scene_number": 2,
                "act_name": "The Comeback",
                "visual_prompt": "Chubby baby bursts out laughing, twists cow's ear like motorcycle throttle, mini cow pops a wheelie and gracefully drifts sideways over the puddle, 3d pixar style",
                "foley_sound_type": "boing",
                "foley_description": "Springy dance bounce and engine rev boing"
            },
            {
                "scene_number": 3,
                "act_name": "Climax Payoff",
                "visual_prompt": "Baby and mini cow stick a superhero landing on blooming flower bed wearing matching tiny sunglasses, giving high-fives with huge joyful smiles, 3d pixar animation",
                "foley_sound_type": "ding",
                "foley_description": "Achievement bell chime"
            }
        ],
        "music_vibe": "bouncy_comedy",
        "yt_title": "The Cutest Duo In History! 👶🐮❤️ #shorts #viral #cutebaby",
        "fb_title": "I cannot stop smiling at this! 😭🐮 Tag someone who needs cuteness today! 👇",
        "tags": ["shorts", "cutebaby", "cow", "animation", "3danimation", "viral", "cute"]
    },
    {
        "title": "The Cockroach Family Dinner",
        "niche": "Role Reversal / Ulti Duniya",
        "character_name": "Papa Cockroach",
        "character_description": "Anthropomorphic cartoon cockroach family wearing striped pajamas sitting around a dining table in a dollhouse, 3d pixar style",
        "scenes": [
            {
                "scene_number": 1,
                "act_name": "Hook -> Conflict",
                "visual_prompt": "Cockroach family in pajamas enjoying tiny pie at dinner table, suddenly a giant cartoon human foot steps down right outside the window shaking the room, 3d pixar animation",
                "foley_sound_type": "bonk",
                "foley_description": "Heavy earthquake foot thud"
            },
            {
                "scene_number": 2,
                "act_name": "The Comeback",
                "visual_prompt": "Papa cockroach puts on tiny sunglasses, taps a remote control, and a miniature red sports car zooms into the dining room for emergency evacuation, 3d pixar style",
                "foley_sound_type": "whoosh",
                "foley_description": "Toy race car tire screech"
            },
            {
                "scene_number": 3,
                "act_name": "Climax Payoff",
                "visual_prompt": "Entire cockroach family in pajamas speeds away in the tiny convertible waving happily as human trips over broom in hilarious background fail, 3d pixar animation",
                "foley_sound_type": "ding",
                "foley_description": "Victory chime and happy horn beep"
            }
        ],
        "music_vibe": "bouncy_comedy",
        "yt_title": "Inside A Cockroach's Emotional Dinner 😂🪳 #shorts #viral #animation",
        "fb_title": "When you realize cockroaches have family drama too! 😂🪳 Tag a friend who hates bugs!",
        "tags": ["shorts", "ultiduniya", "animation", "3danimation", "comedy", "viral", "funny"]
    },
    {
        "title": "Princess Tomato's Kitchen Escape",
        "niche": "Living Food & Objects",
        "character_name": "Princess Tomato",
        "character_description": "Giant glossy cute red tomato with big sparkling anime Pixar eyes, rosy blushing cheeks, wearing a red ribbon bow, 3d pixar animation",
        "scenes": [
            {
                "scene_number": 1,
                "act_name": "Hook -> Conflict",
                "visual_prompt": "Glossy cute tomato with anime eyes and red bow on cutting board, chef's cleaver suddenly slams down inches away, tomato gasps in comical terror, 3d pixar animation",
                "foley_sound_type": "bonk",
                "foley_description": "Heavy blade slam and squeak"
            },
            {
                "scene_number": 2,
                "act_name": "The Comeback",
                "visual_prompt": "Cute tomato rolls backwards like an acrobat, puts on tiny black sunglasses, and hops onto a wooden butter knife to surf across the counter, 3d pixar animation",
                "foley_sound_type": "whoosh",
                "foley_description": "Countertop knife slide whoosh"
            },
            {
                "scene_number": 3,
                "act_name": "Climax Payoff",
                "visual_prompt": "Tomato ollies into a soft fruit basket, making a tiny peace sign with stem leaf while chef scratches head looking completely baffled, 3d pixar style",
                "foley_sound_type": "ding",
                "foley_description": "Cool reveal chime"
            }
        ],
        "music_vibe": "bouncy_comedy",
        "yt_title": "Do NOT Slice The Princess! 🍅🎀😂 #shorts #viral #animation",
        "fb_title": "She was NOT going to become ketchup today! 😎🍅 Tag someone who loves cute things!",
        "tags": ["shorts", "tomato", "cute", "animation", "3danimation", "viral", "comedy"]
    },
    {
        "title": "Chef Leo's Crispy Chicken",
        "niche": "Cat Comedy",
        "character_name": "Chef Leo",
        "character_description": "Chubby ginger cat wearing a white chef toque and headphones, 3d pixar animation style",
        "scenes": [
            {
                "scene_number": 1,
                "act_name": "Hook -> Conflict",
                "visual_prompt": "Chubby ginger cat chef rapidly dicing chicken, pan suddenly catches giant fire with flames shooting to ceiling, cat eyes popping in panic, 3d pixar style",
                "foley_sound_type": "sizzle",
                "foley_description": "Violent oil fire sizzle"
            },
            {
                "scene_number": 2,
                "act_name": "The Comeback",
                "visual_prompt": "Cat chef snaps on welding goggles, flips the fiery wok into the air, and catches every crispy chicken tender back into the pan in one slick move, 3d pixar",
                "foley_sound_type": "whoosh",
                "foley_description": "Acrobatic pan flip whoosh"
            },
            {
                "scene_number": 3,
                "act_name": "Climax Payoff",
                "visual_prompt": "Cat chef munches on giant golden crispy fried chicken drumstick with supreme joyful swagger, crumbs flying, triumph smile, 3d pixar style",
                "foley_sound_type": "crunch",
                "foley_description": "Crispy chicken crunch and ending service bell ding"
            }
        ],
        "music_vibe": "bouncy_comedy",
        "yt_title": "Chef Leo Cooks A Masterpiece! 🍗🐾 #shorts #viral #funnycats",
        "fb_title": "He took his cooking shift WAY too seriously! 😂🍗 Tag someone who loves fried chicken!",
        "tags": ["shorts", "funnycats", "animation", "3danimation", "food", "viral", "comedy"]
    }
]

def generate_viral_story_concept(rlaf_feedback: Optional[Dict] = None) -> Dict:
    """
    Uses Gemini / Qwen-72B to autonomously brainstorm ultra-viral surrealist AI animated short stories
    (inspired by 10M-80M view trends: Shark chefs, Ulti Duniya cockroach families, Baby & animal duos, Living food).
    """
    api_keys = [
        os.environ.get("GEMINI_API_KEY"),
        os.environ.get("GEMINI_API_KEY_2"),
        os.environ.get("GEMINI_API_KEY_3"),
    ]
    api_keys = [k for k in api_keys if k and str(k).strip() != "None"]

    from app.story.trend_radar import get_global_viral_intelligence
    global_intel = get_global_viral_intelligence()
    market_context = global_intel.get("market_summary", "")

    feedback_context = ""
    if rlaf_feedback:
        summary = rlaf_feedback.get("summary", "")
        top_cats = rlaf_feedback.get("top_categories", [])
        if summary or top_cats:
            feedback_context = f"\nChannel Specific Feedback:\n- Summary: {summary}\n- Top Performing on Your Channel: {top_cats}"

    prompt = f"""You are the Executive Creative Director for viral AI animated YouTube Shorts and Facebook Reels (producing 10M to 80M+ view hits).
Your mission is to look at GLOBAL TRENDING MARKET DATA (what is getting 10M-80M views right now across YouTube Shorts) combined with channel audience feedback to design the ultimate high-retention Short:

=== 1. CURRENT GLOBAL VIRAL MARKET INTELLIGENCE ===
{market_context}

=== 2. CHANNEL AUDIENCE DATA ===
{feedback_context or "Channel is in growth phase. Prioritize the high-velocity Global Trends above!"}

=== 3. MANDATORY CREATIVE DIRECTIVES (THE 2-WAVE CONFLICT ARC) ===
Every video must strictly follow the viral "CONFLICT ARC" algorithm curve (Progression vs. Intensity):
1. Universal visual humor & shock / awe / WTF hook (ZERO spoken voiceover / dialogue).
2. Exactly 3 interconnected visual scenes with character consistency following the 2-wave curve:
   - Act 1: "Hook -> Conflict" (0s-3s):
     * Hook (0-1s): Immediate visual shock mid-action (in media res).
     * Rising Action -> Conflict (1-3s): Tension builds fast into a crisis, obstacle, or disaster (First Intensity Peak).
   - Act 2: "The Comeback" (3s-6s):
     * The Comeback (Trough to Pivot): The character refuses to lose! They pull off an unexpected counter-move, bizarre secret tool, or hilarious pivot that flips the crisis on its head.
   - Act 3: "Climax Payoff" (6s-9s):
     * Rising Action -> Climax Payoff (6-9s): Intensity skyrockets to the highest peak on the chart, ending in an explosive, hilarious punchline, triumphant boss moment, or mind-blowing resolution.
3. Model after the highest-velocity global formats:
   - Surreal Anthropomorphic (e.g., Muscular Shark chef slicing a sneaker, Crocodile dentist)
   - Adorable Baby & Animal Companions (e.g., Chubby cute baby riding a mini cow, Baby on giant pelican)
   - Living Cartoon Food & Objects with huge expressive Pixar eyes (e.g., Giant glossy red tomato escaping knife)
   - "Ulti Duniya" / Absurd Role Reversal (e.g., Cockroach family in pajamas having dinner)
   - Animal Slapstick / Food ASMR (e.g., Cat chef, Hamster bakery escape)
4. Style: Always describe as "hyper-detailed 3d pixar animation style, cinematic lighting, expressive facial features, 8k resolution, vivid colors".
5. Specific Foley sound effect requirements for each scene (choose from: whoosh, bonk, quack, bark, crunch, meow, sizzle, boing, knife_chop, ding).

Return valid JSON conforming strictly to the ViralStoryScript schema.
"""

    for k in api_keys:
        try:
            client = genai.Client(api_key=k)
            response = client.models.generate_content(
                model="gemini-2.0-flash",
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
            # Fallback to permanent neural motion assets if available
            fallback_map = {
                1: os.path.join("data", "assets", "motion_fallback", "scene1.mp4"),
                2: os.path.join("data", "assets", "motion_fallback", "scene2.mp4"),
                3: os.path.join("data", "assets", "motion_fallback", "scene3.mp4")
            }
            fb_path = fallback_map.get(num)
            if fb_path and os.path.exists(fb_path):
                print(f"[STORY DIRECTOR] Using motion fallback asset for Scene {num}: {fb_path}")
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

def build_viral_yt_description(story: Dict) -> str:
    """
    Builds a high-retention, YouTube SEO-optimized description modeled directly after
    200M+ view reference channels (e.g. Manoranjan Tales):
    - Top hashtag cluster
    - All-ages audience & minor safety compliance notice
    - Channel subscribe CTAs with links
    - Semantic search keyword block for recommendation algorithm
    - Trending hashtags & remix permission notice
    """
    yt_title = story.get("yt_title", "Funny AI Animation Short 😂 #shorts #viral")
    char_name = story.get("character_name", "Funny Animal")
    niche = story.get("niche", "Animal Comedy")
    tags = story.get("tags", ["shorts", "animation", "funny", "viral", "comedy"])
    
    # 1. Header hashtags
    tag_list = ["#shorts", "#ai", "#3danimation", "#funny", "#animation"]
    for t in tags[:6]:
        clean_t = re.sub(r'[^a-zA-Z0-9]', '', t)
        if clean_t and f"#{clean_t}" not in tag_list:
            tag_list.append(f"#{clean_t}")
    header_tags = " ".join(tag_list[:6])
    
    # 2. Semantic search keywords for YouTube BERT/algorithm
    queries = story.get("related_queries") or [
        f"funny ai {char_name.lower()} animation",
        f"3d {niche.lower()} story",
        "ai funny animal shorts",
        "mischievous animal short video",
        "3d animation comedy",
        "ai viral youtube shorts",
        "cute funny moments",
        "animated animal shorts for all ages"
    ]
    queries_str = "\n".join([f"• {q}" for q in queries])
    
    # 3. Trending hashtags
    related_hashtags = " ".join([f"#{re.sub(r'[^a-zA-Z0-9]', '', t.title())}" for t in tags[:12]])
    
    desc = f"""{header_tags}

{yt_title}

Welcome to Daily Dose of Fun! We bring you top-notch 3D AI-animated animal comedy shorts suitable for all-age audiences who love lovable characters and hilarious adventures.

👉 Don’t forget to like, share & subscribe for more funny animal shorts!
✨ Subscribe for daily laughs: https://www.youtube.com/@DailyDosOfFun-q2t
📱 Follow on Facebook: https://www.facebook.com/profile.php?id=100077547189991

🔍 Related Topics & Search Queries:
{queries_str}

---
🔥 Trending Hashtags:
{related_hashtags} #allages #funny #viral #comedy

⚠️ Disclaimer & YouTube Community Safety Notice:
This video features 100% fictional AI-animated characters in a humorous slapstick scenario. It is created strictly for entertainment and is suitable for all ages. No real animals or minors were involved, harmed, or endangered in any way. This content strictly adheres to YouTube's Minor and Child Safety policies.
© Daily Dose of Fun — All Rights Reserved. Feel free to remix this video directly from YouTube!"""
    return desc.strip()

def build_viral_fb_description(story: Dict) -> str:
    """
    Builds a high-retention Facebook Reels caption tailored strictly for Facebook's algorithm:
    - Short & punchy: Under 120 chars so it doesn't get cut off by '...See More' on mobile.
    - Zero external links: Prevents Facebook from downranking the Reel for linking to YouTube.
    - High-comment trigger: Asks a direct question or prompt to ignite comment engagement.
    - Clean, native Reels hashtag cluster.
    """
    fb_title = story.get("fb_title", "Wait till you see what happens! 😂 Tag a friend!")
    tags = story.get("tags", ["funny", "animation", "viral", "comedy"])
    
    clean_tags = [f"#{re.sub(r'[^a-zA-Z0-9]', '', t.lower())}" for t in tags if t.lower() not in ["shorts", "ytshorts"]]
    fb_tags = " ".join(clean_tags[:4])
    
    desc = f"""{fb_title}

Rate this 1-10 in the comments! 😂👇 Tag a friend who needs a laugh!

{fb_tags} #reels #funnyreels #viralreels #reelsfb #comedy"""
    return desc.strip()
