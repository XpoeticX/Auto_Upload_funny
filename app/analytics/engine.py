import os
import json
import requests
from typing import Dict, List, Tuple
from google import genai
from app.database import (
    get_tracked_videos_for_analytics,
    update_video_metrics,
    get_creative_profile,
    save_creative_profile
)
from app.upload.youtube import get_youtube_client

import math
import random
import datetime

def calculate_reward_points(yt_views: int = 0, yt_likes: int = 0, yt_comments: int = 0,
                           fb_views: int = 0, fb_shares: int = 0, fb_comments: int = 0, fb_likes: int = 0,
                           benchmark_views: int = 1000, recorded_at_str: str = None) -> float:
    """
    Mathematical Reward Function with Laplace Smoothing, Two-Stage 48h Evaluation, and Time-Decay:
    R_i = [ (Views / Benchmark * 20) + (Shares / (Views + 100) * 100) + (Comments / (Views + 100) * 50) + Bonuses - Penalties ] * Weight(t)
    """
    total_views = yt_views + fb_views
    total_shares = fb_shares
    total_comments = yt_comments + fb_comments
    total_likes = yt_likes + fb_likes
    
    # 1. Reach Component
    reach_score = (total_views / max(1, benchmark_views)) * 20.0
    
    # 2. Viral & Engagement Multipliers with Laplace Smoothing (Prevents low-sample skew)
    share_ratio = (total_shares / (total_views + 100.0)) * 100.0
    comment_ratio = (total_comments / (total_views + 100.0)) * 50.0
    
    # 3. Calculate Age in Hours and Time-Decay
    delta_hours = 0.0
    delta_days = 0.0
    time_weight = 1.0
    
    if recorded_at_str:
        try:
            clean_ts = recorded_at_str.replace("Z", "+00:00")
            rec_dt = datetime.datetime.fromisoformat(clean_ts)
            now_dt = datetime.datetime.now(datetime.timezone.utc)
            delta_sec = max(0.0, (now_dt - rec_dt).total_seconds())
            delta_hours = delta_sec / 3600.0
            delta_days = delta_sec / 86400.0
            # 7-day half-life exponential decay
            time_weight = math.exp(-(math.log(2.0) / 7.0) * delta_days)
        except Exception:
            delta_hours = 48.0
            time_weight = 1.0
    
    # 4. Two-Stage Evaluation (48-Hour Seed Probation Window)
    penalty = 0.0
    bonus = 0.0
    
    if total_views >= 50000 or total_shares >= 500:
        bonus = 100.0  # Mega-Viral Tier
    elif total_views >= benchmark_views:
        bonus = 25.0   # Above Benchmark Tier
    elif delta_hours < 48.0:
        penalty = 0.0  # 48-Hour Grace Period: Do NOT penalize slow-burn distribution tests
    elif total_views < 100:
        penalty = 60.0 # Critical Penalty (Confirmed dead after 48h)
    elif total_views < 500:
        penalty = 30.0 # Stagnant Penalty (Confirmed underperformer after 48h)
        
    raw_reward = reach_score + share_ratio + comment_ratio + bonus - penalty
    final_reward = raw_reward * time_weight
    return round(final_reward, 2)

def fetch_and_update_metrics() -> None:
    """
    Fetches latest performance metrics using single-request API batching (1 quota unit for 50 videos)
    and updates time-decayed RLAF Reward Points.
    """
    print("\n--- [PHASE 8] Refreshing Performance Analytics & Reward Ledger ---")
    tracked_videos = get_tracked_videos_for_analytics(limit=50)
    if not tracked_videos:
        print("No videos tracked in video_analytics table yet.")
        return

    youtube = get_youtube_client()
    fb_token = os.environ.get("FB_ACCESS_TOKEN")

    # 1. High-Efficiency Batch Fetch for YouTube (1 Quota Unit for up to 50 Videos)
    yt_stats_map = {}
    yt_ids = [item.get("yt_video_id") for item in tracked_videos if item.get("yt_video_id")]
    if yt_ids and youtube:
        try:
            for chunk in [yt_ids[i:i + 50] for i in range(0, len(yt_ids), 50)]:
                res = youtube.videos().list(part="statistics", id=",".join(chunk)).execute()
                for entry in res.get("items", []):
                    yt_stats_map[entry["id"]] = entry.get("statistics", {})
        except Exception as e:
            print(f"Error during batched YouTube metric fetch: {e}")

    for item in tracked_videos:
        video_id = item.get("video_id")
        yt_id = item.get("yt_video_id")
        fb_id = item.get("fb_video_id")
        recorded_at = item.get("recorded_at")
        
        yt_views, yt_likes, yt_comments = 0, 0, 0
        fb_views, fb_shares, fb_comments, fb_likes = 0, 0, 0, 0

        # Read from cached YouTube batch
        if yt_id and yt_id in yt_stats_map:
            stats = yt_stats_map[yt_id]
            yt_views = int(stats.get("viewCount", 0))
            yt_likes = int(stats.get("likeCount", 0))
            yt_comments = int(stats.get("commentCount", 0))

        # 2. Fetch Facebook Metrics
        if fb_id and fb_token:
            try:
                fb_url = f"https://graph.facebook.com/v19.0/{fb_id}"
                params = {
                    "fields": "views,shares,comments.summary(true),likes.summary(true)",
                    "access_token": fb_token
                }
                r = requests.get(fb_url, params=params, timeout=10)
                if r.status_code == 200:
                    fb_data = r.json()
                    fb_views = int(fb_data.get("views", 0))
                    fb_shares = int(fb_data.get("shares", {}).get("count", 0) if isinstance(fb_data.get("shares"), dict) else 0)
                    fb_comments = int(fb_data.get("comments", {}).get("summary", {}).get("total_count", 0))
                    fb_likes = int(fb_data.get("likes", {}).get("summary", {}).get("total_count", 0))
            except Exception as e:
                print(f"Could not fetch Facebook metrics for {fb_id}: {e}")

        reward_score = calculate_reward_points(
            yt_views, yt_likes, yt_comments,
            fb_views, fb_shares, fb_comments, fb_likes,
            recorded_at_str=recorded_at
        )

        updates = {
            "yt_views": yt_views,
            "yt_likes": yt_likes,
            "yt_comments": yt_comments,
            "fb_views": fb_views,
            "fb_shares": fb_shares,
            "fb_comments": fb_comments,
            "viral_score": reward_score
        }
        update_video_metrics(video_id, updates)

    print("Performance reward ledger updated successfully in Supabase.")

def run_meta_optimizer(category: str, epsilon: float = 0.20) -> dict:
    """
    Autonomous Reinforcement Learning Agent with Epsilon-Greedy Strategy & Structured Attribution Taxonomy:
    - Exploit (80%): Refines & scales proven winning hook patterns and high-CTR title formulas.
    - Explore (20%): Intentionally tests novel wild-card keywords and emerging subgenres to avoid local optima.
    """
    is_exploration = random.random() < epsilon
    mode_tag = "EXPLORATION (Wild-Card Innovation)" if is_exploration else "EXPLOITATION (Precision Scaling)"
    print(f"\n--- [RLAF META-AGENT] Mode: {mode_tag} for '{category}' ---")
    
    tracked_videos = get_tracked_videos_for_analytics(limit=50)
    cat_videos = [v for v in tracked_videos if v.get("category") == category]
    
    cumulative_reward = sum(v.get("viral_score", 0) for v in cat_videos)
    
    if len(cat_videos) < 2:
        print(f"Historical reward data accumulating for '{category}'. Initializing baseline directives.")
        return get_active_profile(category)
        
    recent_batch_json = json.dumps([{
        "title": v.get("title"),
        "reward_score": v.get("viral_score"),
        "yt_views": v.get("yt_views"),
        "fb_views": v.get("fb_views"),
        "shares": v.get("fb_shares"),
        "comments": (v.get("yt_comments", 0) + v.get("fb_comments", 0))
    } for v in cat_videos[:15]], indent=2)
    
    strategy_instruction = """
    STRATEGY MODE: EXPLORATION (20% Wild-Card Discovery)
    - Do NOT just repeat past queries.
    - Intentionally generate 2-3 fresh, high-velocity trending keywords, emerging meme hooks, or new viral subgenres to break out of local optima.
    """ if is_exploration else """
    STRATEGY MODE: EXPLOITATION (80% Precision Scaling)
    - Double down on the highest-rewarding search queries, visual hooks, and title structures identified in the positive reward dataset.
    - Eliminate all penalty-inducing elements.
    """
    
    prompt = f"""
    [SYSTEM: AUTONOMOUS REINFORCEMENT LEARNING AGENT (MAX_REWARD_MODE)]

    You are an autonomous AI Agent whose sole objective is to MAXIMIZE CUMULATIVE REWARD POINTS across YouTube Shorts and Facebook Reels.

    REWARD POLICY:
    - High Views + High Shares + High Comments = POSITIVE REWARD (+20 to +100 Points).
    - Stagnant / Flatlining / Low Retention (>48h) = HEAVY PENALTY (-30 to -60 Points).
    - Videos under 48h are in seed testing phase.
    - Goal: Maximize long-term point yield by dynamically adapting ALL creative parameters.

    CURRENT AGENT STATE & HISTORICAL PERFORMANCE LEDGER:
    {{
      "category": "{category}",
      "total_lifetime_reward": {cumulative_reward},
      "recent_batch_performance": {recent_batch_json}
    }}

    {strategy_instruction}

    ATTRIBUTION TAXONOMY CONSTRAINTS:
    When assigning penalty causes and reward drivers, choose from these standardized categories:
    - Penalty Tags: [HOOK_PACING_LAG, WEAK_CURIOSITY_GAP, NICHE_SATURATION, FLAT_CTA, LOW_CONTRAST_SETUP, AUDIO_MISMATCH]
    - Reward Tags: [IMMEDIATE_PHYSICAL_TWIST, STRONG_CURIOSITY_LOOP, HIGH_DEBATE_CTA, EMOTIONAL_RELATABILITY, FAST_PACED_EDIT, SENSORY_HOOK]

    OUTPUT FORMAT (Strictly valid JSON only, no markdown wrappers):
    {{
      "agent_evaluation": {{
        "reward_trend": "GROWING",
        "strategy_mode": "{'EXPLORATION' if is_exploration else 'EXPLOITATION'}",
        "penalty_root_causes": ["HOOK_PACING_LAG: reason description"],
        "reward_drivers": ["IMMEDIATE_PHYSICAL_TWIST: reason description"]
      }},
      "phase_1_discovery_directives": {{
        "primary_search_queries": [
          "query_1_to_maximize_reach",
          "query_2_to_maximize_reach"
        ],
        "target_subcategories": ["specific_subniche_with_highest_points"]
      }},
      "phase_4_vision_gate_directives": {{
        "optimal_clip_duration": "12-18 seconds",
        "mandatory_visual_hooks": [
          "Immediate physical motion or emotional disruption in 0.0s-1.2s"
        ],
        "instant_reject_triggers": [
          "Static talking heads or slow build-up over 2.5s"
        ]
      }},
      "phase_6_copywriting_directives": {{
        "title_formulas": [
          "Bro thought he had it under control 💀 #shorts #viral",
          "Wait till you see the ending 😂 #viral"
        ],
        "comment_cta": "Which clip made you laugh the hardest? Vote 1, 2, or 3 below! 👇",
        "hashtag_stack": ["#shorts", "#viral", "#funny", "#trending"]
      }}
    }}
    """

    api_keys = [
        os.environ.get("GEMINI_API_KEY"),
        os.environ.get("GEMINI_API_KEY_2"),
        os.environ.get("GEMINI_API_KEY_3"),
        os.environ.get("GEMINI_API_KEY_4")
    ]
    api_keys = [k for k in api_keys if k and str(k).strip() != "None"]
    
    model_names = [
        "gemini-3.7-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-2.5-flash"
    ]
    
    for model in model_names:
        for api_key in api_keys:
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
                    
                    profile_data = json.loads(cleaned_text)
                    save_creative_profile(category, profile_data)
                    return profile_data
            except Exception as e:
                continue
                
    return get_active_profile(category)

def get_active_profile(category: str) -> dict:
    """
    Retrieves dynamic profile for category (e.g., 'funny_short', 'funny_long'),
    falling back to base category baselines if needed.
    """
    db_profile = get_creative_profile(category)
    if db_profile and (db_profile.get("winning_hook_patterns") or db_profile.get("phase_4_vision_gate_directives")):
        return db_profile

    # Determine base theme: 'funny', 'romantic', or 'food'
    base_theme = category.split("_")[0] if "_" in category else category
    format_type = category.split("_")[1] if "_" in category else "short"

    baselines = {
        "funny": {
            "phase_1_discovery_directives": {
                "primary_search_queries": [
                    "malloy hooks funny viral #shorts",
                    "wait for it unexpected ending funny",
                    "instant regret fails 2024",
                    "try not to laugh best fails"
                ] if format_type == "short" else [
                    "ultimate funny fails compilation",
                    "try not to laugh epic moments",
                    "best viral comedy compilation"
                ]
            },
            "phase_4_vision_gate_directives": {
                "optimal_clip_duration": "9-14 seconds" if format_type == "short" else "12-18 seconds",
                "mandatory_visual_hooks": [
                    "Immediate physical motion, stunt, or visual hook in the first 1.2 seconds",
                    "Unexpected twist or relatable fail moment with visual punchline"
                ],
                "instant_reject_triggers": [
                    "Slow build-up over 3 seconds",
                    "Stage comedy or static dialogue scenes"
                ]
            },
            "phase_6_copywriting_directives": {
                "title_formulas": [
                    "Bro thought he had it under control 💀 #shorts #viral",
                    "Instant regret level 100! 😭 #funny #fails",
                    "Wait till you see the ending 😂 #trynottolaugh #viral"
                ] if format_type == "short" else [
                    "EPIC FAILS 🚨 You Will Laugh So Hard 😂 #funny #compilation",
                    "Try Not To Laugh: Ultimate Hilarious Fails 😂 #bestof #viral"
                ],
                "comment_cta": "Which clip made you laugh the hardest? Vote below! 👇",
                "hashtag_stack": ["#funny", "#epicfails", "#meme", "#viral", "#trynottolaugh"]
            }
        },
        "romantic": {
            "phase_1_discovery_directives": {
                "primary_search_queries": [
                    "muslim couple goals halal romance #shorts",
                    "halal relationship aesthetic wholesome",
                    "muslim husband and wife comedy"
                ] if format_type == "short" else [
                    "muslim couple goals wholesome compilation",
                    "halal love story married life compilation"
                ]
            },
            "phase_4_vision_gate_directives": {
                "optimal_clip_duration": "12-16 seconds" if format_type == "short" else "15-20 seconds",
                "mandatory_visual_hooks": [
                    "Wholesome couple surprise, sweet gesture, or modest halal relationship moment",
                    "Emotional warmth and natural chemistry"
                ],
                "instant_reject_triggers": [
                    "Immodest non-Islamic clothing (must wear hijab/purdah)",
                    "Fake staged drama with slow progression"
                ]
            },
            "phase_6_copywriting_directives": {
                "title_formulas": [
                    "The cutest halal love story you'll see today ❤️ #romantic #couplegoals",
                    "Husband surprises wife in the sweetest way 🥹❤️ #love #shorts",
                    "Pure couple goals right here! ❤️ #halallove #wholesome #viral"
                ] if format_type == "short" else [
                    "Wholesome Couple Goals ❤️ Cutest Halal Moments Compilation",
                    "Pure Love & Happiness ❤️ Best Romantic Couple Moments"
                ],
                "comment_cta": "What's the sweetest couple moment you've ever witnessed? Drop a comment below! 👇",
                "hashtag_stack": ["#romantic", "#couplegoals", "#cute", "#love", "#wholesome"]
            }
        },
        "food": {
            "phase_1_discovery_directives": {
                "primary_search_queries": [
                    "satisfying street food cooking ASMR #shorts",
                    "delicious viral food recipes hacks",
                    "mouthwatering cheese pull food prep"
                ] if format_type == "short" else [
                    "ultimate street food compilation around the world",
                    "satisfying cooking ASMR food compilation"
                ]
            },
            "phase_4_vision_gate_directives": {
                "optimal_clip_duration": "9-15 seconds" if format_type == "short" else "12-18 seconds",
                "mandatory_visual_hooks": [
                    "Crispy sizzling sounds, melting cheese, or immediate mouthwatering food prep",
                    "Fast, satisfying ASMR cooking action"
                ],
                "instant_reject_triggers": [
                    "Long ingredient explanations before cooking",
                    "Unappealing visual plating"
                ]
            },
            "phase_6_copywriting_directives": {
                "title_formulas": [
                    "Would you eat this or pass? 🍔🍕 #food #streetfood #viral",
                    "The ultimate satisfying food hack you need to try! 🤤 #foodie #recipe",
                    "Wait till you see the cheese pull 🧀🤤 #delicious #asmr #shorts"
                ] if format_type == "short" else [
                    "MOST SATISFYING FOOD COMPILATION 🤤 Best Street Food Recipes",
                    "Delicious Street Food Hacks You Must Try! 🍔🍕 #compilation"
                ],
                "comment_cta": "Would you eat this or pass? Rate it 1 to 10 in the comments below! 👇",
                "hashtag_stack": ["#food", "#streetfood", "#delicious", "#recipe", "#satisfying"]
            }
        }
    }
    
    return baselines.get(base_theme, baselines["funny"])

def send_telegram_report(category: str, adaptive_profile: dict, upload_summary: dict = None) -> bool:
    """
    Sends a formatted executive summary of the RLAF analytics, learning drivers,
    and dynamic pipeline adjustments to a Telegram Channel or Group.
    """
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        print("Telegram notification skipped: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not configured.")
        return False
        
    eval_data = adaptive_profile.get("agent_evaluation", {})
    reward_trend = eval_data.get("reward_trend", "ACTIVE")
    mode = eval_data.get("strategy_mode", "EXPLOITATION")
    
    rewards_list = eval_data.get("reward_drivers", [])
    rewards = "\n".join([f"  • {r}" for r in rewards_list[:3]]) if rewards_list else "  • Scaling high-retention reach"
    
    penalties_list = eval_data.get("penalty_root_causes", [])
    penalties = "\n".join([f"  • {p}" for p in penalties_list[:3]]) if penalties_list else "  • Zero major drop-off penalties"
    
    p1 = adaptive_profile.get("phase_1_discovery_directives", {})
    queries = "\n".join([f"  🔍 <i>{q}</i>" for q in p1.get("primary_search_queries", [])[:3]]) or "  🔍 Baseline queries"
    
    p4 = adaptive_profile.get("phase_4_vision_gate_directives", {})
    hooks = "\n".join([f"  🎯 {h}" for h in p4.get("mandatory_visual_hooks", [])[:2]]) or "  🎯 Immediate visual motion"
    rejects = "\n".join([f"  ⛔ {r}" for r in p4.get("instant_reject_triggers", [])[:2]]) or "  ⛔ Slow build-up"
    
    p6 = adaptive_profile.get("phase_6_copywriting_directives", {})
    title_formulas = "\n".join([f"  ✍️ <i>{t}</i>" for t in p6.get("title_formulas", [])[:2]]) or "  ✍️ Curiosity loop templates"
    cta = p6.get("comment_cta", "Which moment was your favorite? Vote below! 👇")
    
    short_title = upload_summary.get("short_title", "Published") if upload_summary else "Published"
    comp_title = upload_summary.get("comp_title", "Published") if upload_summary else "Published"
    
    message = f"""
🤖 <b>[RLAF AGENT REPORT] @DailyDosOfFun</b>
━━━━━━━━━━━━━━━━━━━━
📂 <b>Category:</b> <code>{category.upper()}</code>
⚡ <b>Strategy Mode:</b> <b>{mode}</b>
📈 <b>Reward Trend:</b> <b>{reward_trend}</b>

🏆 <b>Top Reward Drivers (What's Winning):</b>
{rewards}

⚠️ <b>Penalty Root Causes (What Got Cut):</b>
{penalties}

━━━━━━━━━━━━━━━━━━━━
🔄 <b>AUTONOMOUS CHANGES APPLIED:</b>

🔍 <b>New Discovery Search Queries:</b>
{queries}

🎯 <b>Mandatory Visual Hooks (Vision Gate):</b>
{hooks}

⛔ <b>Instant Reject Triggers:</b>
{rejects}

✍️ <b>Dynamic Title Formulas:</b>
{title_formulas}

💬 <b>Optimized Comment CTA:</b>
  <i>"{cta}"</i>

━━━━━━━━━━━━━━━━━━━━
🚀 <b>LATEST UPLOADS POSTED:</b>
🎬 <b>Short:</b> {short_title}
📼 <b>Compilation:</b> {comp_title}
"""
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message.strip(),
            "parse_mode": "HTML"
        }
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            print("Telegram Executive Report delivered successfully!")
            return True
        else:
            print(f"Telegram Delivery failed ({res.status_code}): {res.text}")
            return False
    except Exception as e:
        print(f"Telegram notification error: {e}")
        return False
