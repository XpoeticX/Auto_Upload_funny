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
    Mathematical Reward Function with Multi-Window Exponential Time-Decay:
    R_i = [ (Views / Benchmark * 20) + (Shares / Views * 100) + (Comments / Views * 50) + Bonuses - Penalties ] * Weight(t)
    
    Time-Decay: Weight(t) = exp( -ln(2)/7.0 * delta_days ) (7-day half-life for algorithmic freshness)
    """
    total_views = yt_views + fb_views
    total_shares = fb_shares
    total_comments = yt_comments + fb_comments
    total_likes = yt_likes + fb_likes
    
    # 1. Reach Component
    reach_score = (total_views / max(1, benchmark_views)) * 20.0
    
    # 2. Viral Multiplier (Shares/Views)
    share_ratio = (total_shares / max(1, total_views)) * 100.0
    
    # 3. Engagement Multiplier (Comments/Views)
    comment_ratio = (total_comments / max(1, total_views)) * 50.0
    
    # 4. Penalties & Bonuses
    penalty = 0.0
    bonus = 0.0
    
    if total_views >= 50000 or total_shares >= 500:
        bonus = 100.0
    elif total_views >= benchmark_views:
        bonus = 25.0
    elif total_views < 100:
        penalty = 60.0  # Critical Penalty
    elif total_views < 500:
        penalty = 30.0  # Stagnant Penalty
        
    raw_reward = reach_score + share_ratio + comment_ratio + bonus - penalty
    
    # 5. Multi-Window Time-Decay Weighting
    time_weight = 1.0
    if recorded_at_str:
        try:
            # Parse ISO timestamp
            clean_ts = recorded_at_str.replace("Z", "+00:00")
            rec_dt = datetime.datetime.fromisoformat(clean_ts)
            now_dt = datetime.datetime.now(datetime.timezone.utc)
            delta_days = max(0.0, (now_dt - rec_dt).total_seconds() / 86400.0)
            time_weight = math.exp(-(math.log(2.0) / 7.0) * delta_days)
        except Exception:
            time_weight = 1.0
            
    final_reward = raw_reward * time_weight
    return round(final_reward, 2)

def fetch_and_update_metrics() -> None:
    """
    Fetches latest performance metrics from YouTube Data API and Facebook Graph API
    for tracked videos and calculates time-decayed RLAF Reward Points.
    """
    print("\n--- [PHASE 8] Refreshing Performance Analytics & Reward Ledger ---")
    tracked_videos = get_tracked_videos_for_analytics(limit=50)
    if not tracked_videos:
        print("No videos tracked in video_analytics table yet.")
        return

    youtube = get_youtube_client()
    fb_token = os.environ.get("FB_ACCESS_TOKEN")

    for item in tracked_videos:
        video_id = item.get("video_id")
        yt_id = item.get("yt_video_id")
        fb_id = item.get("fb_video_id")
        recorded_at = item.get("recorded_at")
        
        yt_views, yt_likes, yt_comments = 0, 0, 0
        fb_views, fb_shares, fb_comments, fb_likes = 0, 0, 0, 0

        # 1. Fetch YouTube Metrics
        if yt_id and youtube:
            try:
                res = youtube.videos().list(part="statistics", id=yt_id).execute()
                entries = res.get("items", [])
                if entries:
                    stats = entries[0].get("statistics", {})
                    yt_views = int(stats.get("viewCount", 0))
                    yt_likes = int(stats.get("likeCount", 0))
                    yt_comments = int(stats.get("commentCount", 0))
            except Exception as e:
                print(f"Could not fetch YouTube metrics for {yt_id}: {e}")

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
    Autonomous Reinforcement Learning Agent with Epsilon-Greedy Strategy:
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
    - Stagnant / Flatlining / Low Retention = HEAVY PENALTY (-30 to -60 Points).
    - Goal: Maximize long-term point yield by dynamically adapting ALL creative parameters.

    CURRENT AGENT STATE & HISTORICAL PERFORMANCE LEDGER:
    {{
      "category": "{category}",
      "total_lifetime_reward": {cumulative_reward},
      "recent_batch_performance": {recent_batch_json}
    }}

    {strategy_instruction}

    ANALYSIS REQUIRED:
    1. Identify the root cause of all PENALTY (negative point) videos:
       - What visual elements, pacing, or title styles caused drop-offs?
    2. Identify the common patterns of all REWARD (positive point) videos:
       - What triggered the algorithms to push impressions?

    AUTONOMOUS DECISION-MAKING:
    You have total authority to override and select:
    - Search Queries & Discovery Keywords for Phase 1.
    - Visual Hook Validation Criteria for Phase 4.
    - Title Archetypes, Meme Captions, and Comment CTAs for Phase 6.

    OUTPUT FORMAT (Strictly valid JSON only, no markdown wrappers):
    {{
      "agent_evaluation": {{
        "reward_trend": "GROWING",
        "strategy_mode": "{'EXPLORATION' if is_exploration else 'EXPLOITATION'}",
        "penalty_root_causes": ["string"],
        "reward_drivers": ["string"]
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
