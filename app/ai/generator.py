import os
import json
import random
from google import genai
from pydantic import BaseModel, Field
from typing import List, Dict

class OptionItem(BaseModel):
    text: str
    emoji: str = "⚡"
    percentage: int = Field(default=50, ge=10, le=90)

class DilemmaItem(BaseModel):
    topic: str
    question: str = "WOULD YOU RATHER..."
    option_a: OptionItem
    option_b: OptionItem
    voiceover_script: str
    comment_cta: str
    yt_title: str
    fb_title: str
    tags: List[str] = ["shorts", "wouldyourather", "pickone", "dilemma", "viral", "challenge"]

_LOCKED_KEY_INDEX = 0

FALLBACK_DILEMMAS = [
    {
        "topic": "Ultimate Superpower Showdown",
        "question": "WOULD YOU RATHER...",
        "option_a": {"text": "Pause Time For 10 Seconds", "emoji": "⏱️", "percentage": 67},
        "option_b": {"text": "Teleport Anywhere Instantly", "emoji": "⚡", "percentage": 33},
        "voiceover_script": "Would you rather have the ability to pause time for 10 seconds, or teleport anywhere on Earth instantly? Lock in your pick before the timer runs out!",
        "comment_cta": "Which power are you choosing? Tell us in the comments! 👇",
        "yt_title": "Pause Time vs Teleport Anywhere? ⏱️⚡ #shorts #wouldyourather",
        "fb_title": "Be honest: Which superpower are you taking? 😂👇",
        "tags": ["shorts", "wouldyourather", "superpower", "dilemma", "viral", "quiz"]
    },
    {
        "topic": "The Millionaire Trap",
        "question": "WOULD YOU RATHER...",
        "option_a": {"text": "Get $10,000 Every Single Day", "emoji": "💵", "percentage": 78},
        "option_b": {"text": "Lump Sum $50,000,000 Right Now", "emoji": "💰", "percentage": 22},
        "voiceover_script": "Would you rather wake up to ten thousand dollars in your bank account every single day, or get a lump sum of fifty million dollars right this second? Decide before the clock stops!",
        "comment_cta": "Are you taking the daily cash or the lump sum? Vote below! 👇",
        "yt_title": "$10,000 Every Day vs $50 Million Now? 💰💵 #shorts #money",
        "fb_title": "Which payout are you taking? Most people get this wrong! 🤑👇",
        "tags": ["shorts", "wouldyourather", "money", "dilemma", "viral", "challenge"]
    },
    {
        "topic": "The Food Dilemma",
        "question": "WOULD YOU RATHER...",
        "option_a": {"text": "Unlimited Free Pizza Forever", "emoji": "🍕", "percentage": 58},
        "option_b": {"text": "Unlimited Free Burgers & Fries", "emoji": "🍔", "percentage": 42},
        "voiceover_script": "Would you rather eat unlimited free pizza for the rest of your life, or have unlimited free gourmet burgers and crispy fries? Lock in your choice right now!",
        "comment_cta": "Pizza or Burgers? Settle the ultimate debate below! 👇",
        "yt_title": "Unlimited Pizza vs Unlimited Burgers? 🍕🍔 #shorts #foodie",
        "fb_title": "The ultimate food debate: Pizza or Burgers for life? 🤤👇",
        "tags": ["shorts", "wouldyourather", "foodie", "pizza", "burgers", "viral"]
    },
    {
        "topic": "The Time Travel Dilemma",
        "question": "WOULD YOU RATHER...",
        "option_a": {"text": "Travel 100 Years Into The Past", "emoji": "📜", "percentage": 29},
        "option_b": {"text": "Travel 100 Years Into The Future", "emoji": "🚀", "percentage": 71},
        "voiceover_script": "Would you rather travel 100 years into the past with all your modern knowledge, or travel 100 years into the future to see what humanity becomes? Choose your timeline before time runs out!",
        "comment_cta": "Past or Future? Where are you going? Drop a comment! 👇",
        "yt_title": "100 Years in the Past vs 100 Years Future? 🚀📜 #shorts #timetravel",
        "fb_title": "Would you go to the past or the future? Tell us why below! ⏳👇",
        "tags": ["shorts", "wouldyourather", "timetravel", "future", "history", "viral"]
    }
]

def generate_ai_dilemmas(theme: str = "funny", count: int = 1) -> List[Dict]:
    """
    Generates structured, viral 'Would You Rather' dilemmas using Gemini.
    Iterates through the model waterfall and API keys with stateful key locking.
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
        print("[AI GENERATOR] No Gemini API keys found. Using curated viral dilemmas.")
        return random.sample(FALLBACK_DILEMMAS, min(count, len(FALLBACK_DILEMMAS)))
        
    model_names = [
        "gemini-3.7-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-1.5-flash"
    ]
    
    prompt = f"""
    [SYSTEM: VIRAL 'WOULD YOU RATHER' / INTERACTIVE DILEMMA ENGINE]

    Generate {count} extremely addictive, highly polarizing "Would You Rather" challenge scenarios for YouTube Shorts and Facebook Reels.
    Theme: {theme} (Focus on funny dilemmas, extreme choices, lifestyle perks, superpowers, or absurd consequences).

    CRITICAL RULES:
    1. The two options must be GENUINELY TOUGH to choose between (no obvious winner).
    2. Voiceover script must be natural, fast-paced (under 60 words), dramatic, and build suspense for a 3-second countdown.
    3. Percentage estimates for Option A and Option B must sum to 100 (e.g. 62 and 38).
    4. Provide platform-tailored titles:
       - yt_title: curiosity hook with emojis & #shorts #wouldyourather (under 70 chars).
       - fb_title: conversational engagement question provoking friend tags (under 80 chars).

    OUTPUT FORMAT: Return strictly a valid JSON array of objects (no markdown wrappers, no backticks):
    [
      {{
        "topic": "Short 3-4 word topic",
        "question": "WOULD YOU RATHER...",
        "option_a": {{
          "text": "Clear 3-6 word option A",
          "emoji": "🔥",
          "percentage": 64
        }},
        "option_b": {{
          "text": "Clear 3-6 word option B",
          "emoji": "❄️",
          "percentage": 36
        }},
        "voiceover_script": "Engaging 2-3 sentence narration presenting the dilemma and telling them to pick before the timer ends.",
        "comment_cta": "Which one did you choose? Comment A or B below! 👇",
        "yt_title": "Catchy YouTube Shorts Title ⚡ #shorts #wouldyourather",
        "fb_title": "Be honest: Are you choosing Option A or Option B? Tag a friend! 😂👇",
        "tags": ["shorts", "wouldyourather", "challenge", "viral", "quiz"]
      }}
    ]
    """
    
    for model in model_names:
        for offset in range(num_keys):
            key_idx = (_LOCKED_KEY_INDEX + offset) % num_keys
            api_key = api_keys[key_idx]
            try:
                client = genai.Client(api_key=api_key)
                response = client.models.generate_content(
                    model=model,
                    contents=prompt
                )
                if response and response.text:
                    cleaned_text = response.text.strip()
                    if cleaned_text.startswith("```json"):
                        cleaned_text = cleaned_text.split("```json")[1].split("```")[0].strip()
                    elif cleaned_text.startswith("```"):
                        cleaned_text = cleaned_text.split("```")[1].split("```")[0].strip()
                    
                    data = json.loads(cleaned_text)
                    if isinstance(data, list) and len(data) > 0:
                        validated = [DilemmaItem(**item).model_dump() for item in data]
                        _LOCKED_KEY_INDEX = key_idx
                        print(f"[AI GENERATOR] Generated {len(validated)} dilemmas with {model} (Locked Key #{key_idx + 1})")
                        return validated
            except Exception as e:
                # Silently continue to next key or model
                continue

    print("[AI GENERATOR] All API calls exhausted. Using curated viral dilemmas.")
    return random.sample(FALLBACK_DILEMMAS, min(count, len(FALLBACK_DILEMMAS)))
