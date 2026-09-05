import os
import json
import time
from google import genai
from pydantic import BaseModel
from typing import List, Dict

class NarrationData(BaseModel):
    character_persona: str = "Comedic Narrator"
    voice_name: str = "en-US-ChristopherNeural"
    voiceover_script: str
    top_meme_headline: str = "WAIT TILL THE END 😂💀"
    yt_title: str
    fb_title: str
    tags: List[str] = ["shorts", "viral", "funny", "comedy"]

_LOCKED_KEY_INDEX = 0

FALLBACK_NARRATIONS = [
    {
        "character_persona": "Grumpy Cat",
        "voice_name": "en-US-ChristopherNeural",
        "voiceover_script": "Human, I am giving you exactly three seconds to explain what you are doing right now. If this ends up on the internet, your shoes will pay the price.",
        "top_meme_headline": "BRO IS NOT HAVING IT TODAY 💀",
        "yt_title": "He was NOT having it today 😂💀 #shorts #funnycats",
        "fb_title": "The exact face you make when Monday hits 😂 Tag a friend! 👇",
        "tags": ["shorts", "funnycats", "viral", "comedy", "pets"]
    },
    {
        "character_persona": "Panicked Animal",
        "voice_name": "en-US-GuyNeural",
        "voiceover_script": "Look at him go! Total confidence, zero regret, and absolute chaotic energy! Somebody call for backup right now!",
        "top_meme_headline": "MISTAKES WERE MADE 😭",
        "yt_title": "The instant regret was REAL 😭💀 #shorts #viral",
        "fb_title": "He knew he messed up the second he jumped 😂👇",
        "tags": ["shorts", "instantregret", "viral", "comedy", "fails"]
    }
]

def generate_ai_narration(video_path: str, clip_duration: float = 12.0) -> Dict:
    """
    Uses Gemini Vision to watch the video clip and generate a hilarious,
    transformative character voiceover (e.g. funny pet inner monologue).
    """
    global _LOCKED_KEY_INDEX

    api_keys = [
        os.environ.get("GEMINI_API_KEY"),
        os.environ.get("GEMINI_API_KEY_2"),
        os.environ.get("GEMINI_API_KEY_3"),
        os.environ.get("GEMINI_API_KEY_4")
    ]
    api_keys = [k for k in api_keys if k and str(k).strip() != "None"]

    num_keys = len(api_keys)
    if num_keys == 0:
        print("[AI NARRATOR] No Gemini API keys found. Using curated narration.")
        return FALLBACK_NARRATIONS[0]

    model_names = [
        "gemini-3.7-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-1.5-flash"
    ]

    target_word_count = max(18, min(50, int(clip_duration * 2.8)))

    prompt = f"""
    [SYSTEM: VIRAL PET & COMEDY VOICE-OVER ENGINE (LIKE KLR PRODUCTIONS / RXCKSTXR)]

    Watch this video clip carefully.
    Your task is to write a HILARIOUS, high-retention character voice-over monologue that transforms this clip into viral gold.

    GUIDELINES:
    1. PERSONA: Give the main animal or person a distinct funny personality:
       - Sarcastic Cat, Overhyped Dog, Panicked Culprit, Dramatic Narrator, or Snarky Commentator.
    2. SCRIPT LENGTH: Exactly ~{target_word_count} words (must take ~{clip_duration:.1f}s to speak at high energy).
    3. TIMING & PACING: The voiceover must match the physical action and punchline happening on screen.
    4. VOICE SELECTION: Pick from ["en-US-ChristopherNeural" (punchy/male), "en-US-GuyNeural" (expressive/male), "en-US-JennyNeural" (sassy/female), "en-US-AnaNeural" (cute/playful)].
    5. HEADLINE: A short, viral 4-6 word meme banner to place on top (e.g. "HE THOUGHT HE WAS SLICK 💀", "WAIT FOR THE REACTION 😭").
    6. PLATFORM COPY:
       - yt_title: Clickable title with emojis & #shorts #viral (under 70 chars).
       - fb_title: Engaging question that provokes friend tags in comments (under 80 chars).

    OUTPUT FORMAT: Return STRICTLY a valid JSON object (no markdown, no backticks):
    {{
      "character_persona": "Sarcastic Cat",
      "voice_name": "en-US-ChristopherNeural",
      "voiceover_script": "Hilarious spoken monologue matching the video action.",
      "top_meme_headline": "BRO TOOK IT PERSONALLY 💀",
      "yt_title": "He took it so personally 😂💀 #shorts #funny",
      "fb_title": "Tag the friend who acts exactly like this! 😂👇",
      "tags": ["shorts", "funny", "viral", "comedy", "pets"]
    }}
    """

    for model in model_names:
        for offset in range(num_keys):
            key_idx = (_LOCKED_KEY_INDEX + offset) % num_keys
            api_key = api_keys[key_idx]
            try:
                client = genai.Client(api_key=api_key)
                uploaded_file = client.files.upload(file=video_path)

                while str(uploaded_file.state).endswith("PROCESSING") or (hasattr(uploaded_file.state, 'name') and uploaded_file.state.name == "PROCESSING"):
                    time.sleep(1.5)
                    uploaded_file = client.files.get(name=uploaded_file.name)

                if str(uploaded_file.state).endswith("FAILED") or (hasattr(uploaded_file.state, 'name') and uploaded_file.state.name == "FAILED"):
                    continue

                response = client.models.generate_content(
                    model=model,
                    contents=[uploaded_file, prompt]
                )

                if response and response.text:
                    cleaned_text = response.text.strip()
                    if cleaned_text.startswith("```json"):
                        cleaned_text = cleaned_text.split("```json")[1].split("```")[0].strip()
                    elif cleaned_text.startswith("```"):
                        cleaned_text = cleaned_text.split("```")[1].split("```")[0].strip()

                    data = json.loads(cleaned_text)
                    validated = NarrationData(**data).model_dump()
                    _LOCKED_KEY_INDEX = key_idx
                    print(f"[AI NARRATOR] Generated voiceover script via {model} (Locked Key #{key_idx + 1})")
                    return validated
            except Exception as e:
                continue

    print("[AI NARRATOR] Fallback narration triggered.")
    return FALLBACK_NARRATIONS[0]
