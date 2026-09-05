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
    palette: str = "classic"
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
        "palette": "cyberpunk",
        "option_a": {"text": "Pause Time For 10 Seconds", "emoji": "⏱️", "percentage": 67},
        "option_b": {"text": "Teleport Anywhere Instantly", "emoji": "⚡", "percentage": 33},
        "voiceover_script": "Would you rather have the ability to pause time for 10 seconds, or teleport anywhere on Earth instantly? Lock in your pick before the timer runs out!",
        "comment_cta": "Which power are you choosing? Tell us in the comments! 👇",
        "yt_title": "Pause Time vs Teleport Anywhere? ⏱️⚡ #shorts #wouldyourather",
        "fb_title": "Be honest: Which superpower are you taking? 😂👇",
        "tags": ["shorts", "wouldyourather", "superpower", "dilemma", "viral", "quiz"]
    },
    {
        "topic": "The Billionaire Temptation",
        "question": "WOULD YOU RATHER...",
        "palette": "royal",
        "option_a": {"text": "Get $10,000 Every Single Day", "emoji": "💵", "percentage": 78},
        "option_b": {"text": "Lump Sum $50,000,000 Right Now", "emoji": "💰", "percentage": 22},
        "voiceover_script": "Would you rather wake up to ten thousand dollars in your bank account every single day, or get a lump sum of fifty million dollars right this second? Decide before the clock stops!",
        "comment_cta": "Are you taking the daily cash or the lump sum? Vote below! 👇",
        "yt_title": "$10,000 Every Day vs $50 Million Now? 💰💵 #shorts #money",
        "fb_title": "Which payout are you taking? Most people get this wrong! 🤑👇",
        "tags": ["shorts", "wouldyourather", "money", "dilemma", "viral", "challenge"]
    },
    {
        "topic": "Zombie Apocalypse Survival",
        "question": "WOULD YOU RATHER...",
        "palette": "toxic",
        "option_a": {"text": "Survive With John Wick In A Bunker", "emoji": "🔫", "percentage": 61},
        "option_b": {"text": "Survive On An Aircraft Carrier Solo", "emoji": "🚢", "percentage": 39},
        "voiceover_script": "In a zombie apocalypse, would you rather hide out in an underground bunker with John Wick, or control a fully stocked military aircraft carrier completely alone? Pick your survival plan now!",
        "comment_cta": "Who is surviving this? Drop your choice below! 👇",
        "yt_title": "Survive With John Wick or Military Carrier? 🧟‍♂️🚢 #shorts #apocalypse",
        "fb_title": "How would you survive the apocalypse? Be honest! 🧟‍♂️👇",
        "tags": ["shorts", "wouldyourather", "survival", "apocalypse", "action", "viral"]
    },
    {
        "topic": "The Impossible Curse",
        "question": "WOULD YOU RATHER...",
        "palette": "inferno",
        "option_a": {"text": "Always Speak Your Exact Thoughts", "emoji": "🗣️", "percentage": 34},
        "option_b": {"text": "Never Be Able To Speak Again", "emoji": "🤐", "percentage": 66},
        "voiceover_script": "Would you rather be forced to say every single thought that enters your mind out loud, or never be able to speak a single word ever again? Lock in your answer before time runs out!",
        "comment_cta": "Which curse is worse? Comment below! 👇",
        "yt_title": "Say Every Thought vs Never Speak Again? 🗣️🤐 #shorts #dilemma",
        "fb_title": "Which curse would ruin your life faster? Vote below! 😂👇",
        "tags": ["shorts", "wouldyourather", "curse", "dilemma", "viral", "funny"]
    },
    {
        "topic": "The Mind-Reading Paradox",
        "question": "WOULD YOU RATHER...",
        "palette": "classic",
        "option_a": {"text": "Know What Everyone Thinks Of You", "emoji": "🧠", "percentage": 43},
        "option_b": {"text": "Know Exactly How & When You Die", "emoji": "⏳", "percentage": 57},
        "voiceover_script": "Would you rather know the brutal truth of what everyone actually thinks about you, or know the exact date and way your life ends? Choose carefully before the buzzer sounds!",
        "comment_cta": "Which forbidden knowledge are you unlocking? Comment below! 👇",
        "yt_title": "Know Everyone's Thoughts vs Know Your Death Date? 🧠⏳ #shorts #mystery",
        "fb_title": "Which secret would you rather know? Tell us in the comments! 🔮👇",
        "tags": ["shorts", "wouldyourather", "mystery", "psychology", "viral", "challenge"]
    }
]

def generate_ai_dilemmas(theme: str = "any", count: int = 1, rlaf_feedback: dict = None) -> List[Dict]:
    """
    Generates structured, viral 'Would You Rather' dilemmas using Gemini.
    - NO TOPIC RESTRICTIONS: Explores any high-retention viral concept.
    - RLAF ADAPTATION: Automatically doubles down on high-view niches and explores wild-cards.
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
    
    # Construct dynamic RLAF guidance
    rlaf_guidance = ""
    if rlaf_feedback:
        top_topics = rlaf_feedback.get("top_topics", [])
        low_topics = rlaf_feedback.get("low_topics", [])
        strategy = rlaf_feedback.get("strategy_mode", "EXPLORATION")
        if top_topics:
            rlaf_guidance += f"\nHISTORICAL PERFORMANCE: Topics with highest view retention: {', '.join(top_topics)}."
        if low_topics:
            rlaf_guidance += f"\nAVOID OR RE-INVENT: Topics with poor engagement: {', '.join(low_topics)}."
        rlaf_guidance += f"\nSTRATEGY MODE: {strategy}."

    prompt = f"""
    [SYSTEM: HIGH-VIRALITY INTERACTIVE DILEMMA ENGINE]
    
    GOAL: MAXIMUM ORGANIC VIEWS, MAXIMUM WATCH TIME, MAXIMUM COMMENTS, AND MAXIMUM FOLLOWER GROWTH.
    CRITICAL MANDATE: NO RESTRICTIONS ON TOPIC. You are 100% free to explore ANY topic that captures human curiosity and triggers passionate debate:
    - Extreme wealth, billionaire dilemmas, and money traps
    - Crazy survival, apocalypse, and life-or-death scenarios
    - Insane superpowers, time travel, and sci-fi abilities
    - Absurd body modifications, weird physical curses, and funny glitches
    - Mind-bending psychological paradoxes and moral dilemmas
    - Relatable relationship, dating, and partner dilemmas
    - Gaming, futuristic AI, and cyber tech
    - Dark humor, escape rooms, or crime-solving puzzles
    - Everyday hilarious battles and controversial food/habit opinions

    {rlaf_guidance}

    Generate {count} unique, highly polarizing "Would You Rather" scenarios.

    CRITICAL RULES:
    1. The two options must be GENUINELY TOUGH to choose between (split should feel close, e.g. 52/48 or 65/35).
    2. Voiceover script must be natural, high-energy, fast-paced (under 60 words), and build suspense for a 3-second countdown.
    3. Assign a vibrant visual palette for each dilemma from: ["classic", "cyberpunk", "toxic", "inferno", "royal"].
    4. Provide platform-tailored copy:
       - yt_title: high-curiosity question with emojis and #shorts #wouldyourather (under 70 chars).
       - fb_title: conversational engagement question provoking friend tags and comments (under 80 chars).

    OUTPUT FORMAT: Return strictly a valid JSON array of objects (no markdown wrappers, no backticks):
    [
      {{
        "topic": "Short 3-4 word topic",
        "question": "WOULD YOU RATHER...",
        "palette": "classic",
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
        "voiceover_script": "Engaging 2-3 sentence narration presenting the dilemma and building suspense before the countdown.",
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
