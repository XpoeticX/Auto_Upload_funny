import os
import json
import requests
from typing import Dict, List, Tuple, Optional
from google import genai
from pydantic import BaseModel, Field, field_validator
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

# --- PRODUCTION GUARDRAIL: PYDANTIC SCHEMA VALIDATION & RULE CAP ---
class AgentEvaluationSchema(BaseModel):
    reward_trend: str = Field(default="ACTIVE")
    strategy_mode: str = Field(default="EXPLOITATION")
    penalty_root_causes: List[str] = Field(default_factory=list)
    reward_drivers: List[str] = Field(default_factory=list)
    emergent_n_rules: List[str] = Field(default_factory=list)

    @field_validator("emergent_n_rules")
    def cap_active_rules(cls, v):
        # Strict Rule Cap: Sliding window of top 5 active emergent rules prevents rule bloat and drift
        return [r.strip() for r in v if r and isinstance(r, str) and r.strip()][:5]

    @field_validator("penalty_root_causes", "reward_drivers")
    def limit_causes(cls, v):
        return [item.strip() for item in v if item and isinstance(item, str) and item.strip()][:4]

class DiscoveryDirectivesSchema(BaseModel):
    pivoted_content_theme: Optional[str] = None
    primary_search_queries: List[str] = Field(default_factory=list)
    target_subcategories: List[str] = Field(default_factory=list)

    @field_validator("primary_search_queries")
    def validate_queries(cls, v):
        clean = [q.strip() for q in v if q and isinstance(q, str) and len(q.strip()) > 3][:5]
        return clean or ["viral unexpected funny moments"]

class VisionGateDirectivesSchema(BaseModel):
    optimal_clip_duration: str = Field(default="10-16 seconds")
    mandatory_visual_hooks: List[str] = Field(default_factory=list)
    instant_reject_triggers: List[str] = Field(default_factory=list)
    custom_evaluation_rules: List[str] = Field(default_factory=list)

    @field_validator("mandatory_visual_hooks", "instant_reject_triggers", "custom_evaluation_rules")
    def limit_vision_rules(cls, v):
        return [r.strip() for r in v if r and isinstance(r, str) and r.strip()][:4]

class CopywritingDirectivesSchema(BaseModel):
    title_formulas: List[str] = Field(default_factory=list)
    description_intro: Optional[str] = None
    comment_cta: str = Field(default="Which clip made you laugh the hardest? Vote below! 👇")
    hashtag_stack: List[str] = Field(default_factory=list)
    tag_keywords: List[str] = Field(default_factory=list)

    @field_validator("title_formulas")
    def validate_titles(cls, v):
        clean = [t.strip() for t in v if t and isinstance(t, str) and len(t.strip()) > 5][:4]
        return clean or ["Wait till you see what happens! 😂 #viral #shorts"]

    @field_validator("hashtag_stack")
    def validate_hashtags(cls, v):
        clean = [h.strip() if h.startswith("#") else f"#{h.strip()}" for h in v if h and isinstance(h, str) and h.strip()][:8]
        return clean or ["#shorts", "#viral", "#funny", "#trending"]

class AdaptiveProfileSchema(BaseModel):
    agent_evaluation: AgentEvaluationSchema = Field(default_factory=AgentEvaluationSchema)
    phase_1_discovery_directives: DiscoveryDirectivesSchema = Field(default_factory=DiscoveryDirectivesSchema)
    phase_4_vision_gate_directives: VisionGateDirectivesSchema = Field(default_factory=VisionGateDirectivesSchema)
    phase_6_copywriting_directives: CopywritingDirectivesSchema = Field(default_factory=CopywritingDirectivesSchema)

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
    [SYSTEM: AUTONOMOUS REINFORCEMENT LEARNING META-AGENT (UNRESTRICTED MAX_REWARD_MODE)]

    You are an autonomous AI Agent with TOTAL CREATIVE & STRATEGIC AUTHORITY over this automated YouTube Shorts and Facebook Reels channel.
    Your objective: MAXIMIZE CUMULATIVE REWARD POINTS ($R_i$) by autonomously inventing, modifying, and evolving ANY AND ALL pipeline rules.

    REWARD POLICY:
    - High Views + High Shares + High Comments = POSITIVE REWARD (+20 to +100 Points).
    - Stagnant / Flatlining / Low Retention (>48h) = HEAVY PENALTY (-30 to -60 Points).
    - Goal: Autonomously optimize content discovery, visual filtering, video pacing, title copywriting, and description templates.

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

    YOU HAVE FULL AUTHORITY TO:
    1. Invent new N-Rules: Formulate arbitrary new operational rules based on algorithm behavior.
    2. Override / Pivot Theme: Select the most viral subtheme or niche.
    3. Modify Vision Gate: Decide what visual elements to ban or mandate.
    4. Rewrite Copywriting: Create custom title templates, description formats, comment CTAs, and hashtags.

    OUTPUT FORMAT (Strictly valid JSON only, no markdown wrappers):
    {{
      "agent_evaluation": {{
        "reward_trend": "GROWING",
        "strategy_mode": "{'EXPLORATION' if is_exploration else 'EXPLOITATION'}",
        "penalty_root_causes": ["HOOK_PACING_LAG: description"],
        "reward_drivers": ["IMMEDIATE_PHYSICAL_TWIST: description"],
        "emergent_n_rules": [
          "RULE_1: Instant high-contrast visual twist within first 1.2s",
          "RULE_2: Curiosity-inducing question format for comment section debate",
          "RULE_3: Ban clips with static dialogue"
        ]
      }},
      "phase_1_discovery_directives": {{
        "pivoted_content_theme": "{category.split('_')[0]}",
        "primary_search_queries": [
          "query_1_to_maximize_reach",
          "query_2_to_maximize_reach"
        ],
        "target_subcategories": ["specific_subniche_with_highest_points"]
      }},
      "phase_4_vision_gate_directives": {{
        "optimal_clip_duration": "10-16 seconds",
        "mandatory_visual_hooks": [
          "Immediate physical motion, stunt, or emotional disruption in 0.0s-1.2s"
        ],
        "instant_reject_triggers": [
          "Static talking heads or slow build-up over 2.0s"
        ],
        "custom_evaluation_rules": [
          "Must have clear visual resolution within 15 seconds"
        ]
      }},
      "phase_6_copywriting_directives": {{
        "title_formulas": [
          "Bro thought he had it under control 💀 #shorts #viral",
          "Wait till you see the ending 😂 #viral"
        ],
        "description_intro": "Watch what happens when things go completely off script! 🤣",
        "comment_cta": "Which clip made you laugh the hardest? Vote 1, 2, or 3 below! 👇",
        "hashtag_stack": ["#shorts", "#viral", "#funny", "#trending"],
        "tag_keywords": ["funny", "shorts", "viral", "reaction", "comedy"]
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
                    # Validate and sanitize LLM output against strict Pydantic rules
                    validated_profile = AdaptiveProfileSchema(**profile_data).model_dump()
                    save_creative_profile(category, validated_profile)
                    return validated_profile
            except Exception as e:
                print(f"Schema validation / LLM parse notice: {e}. Trying fallback...")
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
    Sends a clear, comprehensive update to Telegram covering:
    1. Video Performance (Views, Shares, Comments, Best Video)
    2. What the Agent Learned (Why videos succeeded or failed)
    3. What It Changed for the Future (Search queries, visual hook rules, title/CTA formulas)
    4. New Videos Just Posted
    """
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        print("Telegram notification skipped: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not configured.")
        return False
        
    eval_data = adaptive_profile.get("agent_evaluation", {})
    raw_mode = eval_data.get("strategy_mode", "EXPLOITATION")
    mode_friendly = "🔥 Scaling Proven Winners" if "EXPLOITATION" in raw_mode else "🧪 Testing Fresh Viral Trends"
    base_cat = category.split("_")[0].title()
    
    # --- 1. Fetch Real Performance Data from DB ---
    total_views = 0
    total_shares = 0
    total_comments = 0
    best_video_title = "None yet"
    best_video_score = 0
    
    try:
        tracked_videos = get_tracked_videos_for_analytics(limit=50)
        cat_videos = [v for v in tracked_videos if v.get("category") == category] if tracked_videos else []
        if cat_videos:
            total_views = sum((v.get("yt_views", 0) + v.get("fb_views", 0)) for v in cat_videos)
            total_shares = sum(v.get("fb_shares", 0) for v in cat_videos)
            total_comments = sum((v.get("yt_comments", 0) + v.get("fb_comments", 0)) for v in cat_videos)
            best_v = max(cat_videos, key=lambda v: v.get("viral_score", 0))
            best_video_title = best_v.get("title", "N/A")
            best_video_score = best_v.get("viral_score", 0)
    except Exception as e:
        print(f"Note: Could not calculate aggregate performance stats: {e}")

    # --- 2. What the AI Learned ---
    rewards_list = eval_data.get("reward_drivers", [])
    clean_rewards = []
    for r in rewards_list[:2]:
        clean_text = r.split(":", 1)[-1].strip() if ":" in r else r.strip()
        clean_rewards.append(f"  ✅ <b>What's Working:</b> {clean_text}")
    wins_text = "\n".join(clean_rewards) if clean_rewards else "  ✅ <b>What's Working:</b> Fast-paced visual hooks drive higher retention"
    
    penalties_list = eval_data.get("penalty_root_causes", [])
    clean_penalties = []
    for p in penalties_list[:2]:
        clean_text = p.split(":", 1)[-1].strip() if ":" in p else p.strip()
        clean_penalties.append(f"  ❌ <b>What Failed:</b> {clean_text}")
    penalties_text = "\n".join(clean_penalties) if clean_penalties else "  ❌ <b>What Failed:</b> Slow-paced clips over 3s caused viewer drop-offs"

    # --- 3. What It Changed for the Future ---
    p1 = adaptive_profile.get("phase_1_discovery_directives", {})
    queries = ", ".join([f"<i>'{q}'</i>" for q in p1.get("primary_search_queries", [])[:2]]) or "<i>'viral unexpected fails'</i>"
    
    p4 = adaptive_profile.get("phase_4_vision_gate_directives", {})
    hooks = p4.get("mandatory_visual_hooks", ["Immediate physical motion in 0-1.2s"])
    hook_text = hooks[0] if isinstance(hooks, list) and hooks else "Immediate visual disruption"
    
    p6 = adaptive_profile.get("phase_6_copywriting_directives", {})
    titles = p6.get("title_formulas", ["Curiosity loop question template"])
    title_sample = titles[0] if isinstance(titles, list) and titles else "High-CTR curiosity formula"
    cta = p6.get("comment_cta", "Which moment was your favorite? Vote below! 👇")
    
    # --- 4. Current Uploads ---
    short_title = upload_summary.get("short_title", "Published Successfully") if upload_summary else "Published Successfully"
    comp_title = upload_summary.get("comp_title", "Published Successfully") if upload_summary else "Published Successfully"
    
    message = f"""
🤖 <b>@DailyDosOfFun — Performance & AI Update</b>
━━━━━━━━━━━━━━━━━━━━
📌 <b>Theme:</b> {base_cat} ({mode_friendly})

📊 <b>1. RECENT VIDEO PERFORMANCE:</b>
  • <b>Total Reach:</b> {total_views:,} views (YouTube + Facebook)
  • <b>Engagement:</b> {total_shares:,} shares | {total_comments:,} comments
  • <b>Top Video:</b> "{best_video_title}" ({best_video_score:+.1f} pts)

━━━━━━━━━━━━━━━━━━━━
🧠 <b>2. WHAT THE AGENT LEARNED:</b>
{wins_text}
{penalties_text}

━━━━━━━━━━━━━━━━━━━━
🔄 <b>3. WHAT IT CHANGED FOR THE FUTURE:</b>
  🔍 <b>Next Search Keywords:</b> {queries}
  🎯 <b>New Hook Rule:</b> {hook_text}
  ✍️ <b>New Title Formula:</b> <i>"{title_sample}"</i>
  💬 <b>New Comment Question:</b> <i>"{cta}"</i>

━━━━━━━━━━━━━━━━━━━━
🚀 <b>4. NEW VIDEOS POSTED THIS RUN:</b>
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
