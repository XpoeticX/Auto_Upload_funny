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

def calculate_youtube_reward(views: int = 0, likes: int = 0, comments: int = 0,
                             benchmark_views: int = 1000, recorded_at_str: str = None) -> float:
    """
    Velocity & Recency weighted YouTube Shorts Reward:
    - Prioritizes view velocity (views / day) over static total views.
    - 500 views in 1 day scores significantly higher than 10,000 views accumulated over 1 year.
    - 14-day exponential half-life ensures fresh momentum steers AI decisions.
    """
    delta_days = 1.0
    if recorded_at_str:
        try:
            clean_ts = recorded_at_str.replace("Z", "+00:00")
            rec_dt = datetime.datetime.fromisoformat(clean_ts)
            now_dt = datetime.datetime.now(datetime.timezone.utc)
            delta_sec = max(60.0, (now_dt - rec_dt).total_seconds())
            delta_days = delta_sec / 86400.0
        except Exception:
            delta_days = 7.0

    # 1. View Velocity (views per day vs benchmark daily pace)
    effective_days = max(0.25, delta_days)
    views_per_day = views / effective_days
    benchmark_velocity = max(10.0, benchmark_views / 7.0)  # ~142.8 views/day
    velocity_score = min(200.0, (views_per_day / benchmark_velocity) * 40.0)

    # 2. Cumulative Reach (sub-linear square root so historical bulk doesn't dominate fresh viral spikes)
    reach_score = min(30.0, math.sqrt(views / max(1.0, benchmark_views)) * 15.0)

    # 3. Engagement ratios
    like_ratio = (likes / (views + 100.0)) * 60.0
    comment_ratio = (comments / (views + 100.0)) * 80.0

    # 4. Recency decay (14-day half-life: 1 day = 0.95, 365 days = 0.00000001)
    time_weight = math.exp(-(math.log(2.0) / 14.0) * delta_days)

    bonus = 0.0
    penalty = 0.0
    if views_per_day >= 500.0 or views >= 10000:
        bonus = 50.0
    elif views_per_day >= benchmark_velocity:
        bonus = 20.0

    if delta_days > 3.0 and views_per_day < 5.0:
        penalty = 30.0

    raw_score = velocity_score + reach_score + like_ratio + comment_ratio + bonus - penalty
    return round(raw_score * time_weight, 2)

def calculate_facebook_reward(views: int = 0, shares: int = 0, comments: int = 0, likes: int = 0,
                              benchmark_views: int = 1000, recorded_at_str: str = None,
                              avg_watch_sec: float = 0.0) -> float:
    """
    Velocity & Average Watch Time weighted Facebook Reels Reward:
    - Prioritizes view velocity (views / day) over static total views.
    - Factors in average watch time / retention (e.g. 5.4s+ on short reels = high completion bonus).
    - Heavy weighting for social shares (feed shares to friends).
    - 14-day exponential half-life ensures fresh viral hits dominate stale old uploads.
    """
    delta_days = 1.0
    if recorded_at_str:
        try:
            clean_ts = recorded_at_str.replace("Z", "+00:00")
            rec_dt = datetime.datetime.fromisoformat(clean_ts)
            now_dt = datetime.datetime.now(datetime.timezone.utc)
            delta_sec = max(60.0, (now_dt - rec_dt).total_seconds())
            delta_days = delta_sec / 86400.0
        except Exception:
            delta_days = 7.0

    # 1. View Velocity
    effective_days = max(0.25, delta_days)
    views_per_day = views / effective_days
    benchmark_velocity = max(10.0, benchmark_views / 7.0)  # ~142.8 views/day
    velocity_score = min(200.0, (views_per_day / benchmark_velocity) * 40.0)

    # 2. Cumulative Reach
    reach_score = min(30.0, math.sqrt(views / max(1.0, benchmark_views)) * 15.0)

    # 3. Social Interaction Ratios
    share_ratio = (shares / (views + 100.0)) * 120.0
    comment_ratio = (comments / (views + 100.0)) * 60.0
    like_ratio = (likes / (views + 100.0)) * 40.0

    # 4. Average Watch Time / Retention Score
    watch_score = 0.0
    if avg_watch_sec > 0.0:
        # Typical Short is 10-15s; 6s+ is 40-50%+ retention
        watch_score = min(40.0, (avg_watch_sec / 7.0) * 25.0)

    # 5. Recency Decay (14-day half-life)
    time_weight = math.exp(-(math.log(2.0) / 14.0) * delta_days)

    bonus = 0.0
    penalty = 0.0
    if views_per_day >= 500.0 or views >= 10000:
        bonus = 50.0
    elif views_per_day >= benchmark_velocity:
        bonus = 20.0

    if delta_days > 3.0 and views_per_day < 5.0:
        penalty = 30.0

    raw_score = velocity_score + reach_score + share_ratio + comment_ratio + like_ratio + watch_score + bonus - penalty
    return round(raw_score * time_weight, 2)

def calculate_reward_points(yt_views: int = 0, yt_likes: int = 0, yt_comments: int = 0,
                           fb_views: int = 0, fb_shares: int = 0, fb_comments: int = 0, fb_likes: int = 0,
                           benchmark_views: int = 1000, recorded_at_str: str = None,
                           fb_avg_watch_sec: float = 0.0) -> float:
    """Calculates cumulative score across both platforms."""
    yt_score = calculate_youtube_reward(yt_views, yt_likes, yt_comments, benchmark_views, recorded_at_str)
    fb_score = calculate_facebook_reward(fb_views, fb_shares, fb_comments, fb_likes, benchmark_views, recorded_at_str, fb_avg_watch_sec)
    return round(yt_score + fb_score, 2)

def fetch_and_update_metrics() -> None:
    """
    Fetches latest metrics and computes independent YouTube and Facebook rewards.
    """
    print("\n--- [PHASE 8] Refreshing Platform-Decoupled Reward Ledgers ---")
    tracked_videos = get_tracked_videos_for_analytics(limit=50)
    if not tracked_videos:
        print("No videos tracked in video_analytics table yet.")
        return

    youtube = get_youtube_client()
    fb_token = os.environ.get("FB_ACCESS_TOKEN")

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

        if yt_id and yt_id in yt_stats_map:
            stats = yt_stats_map[yt_id]
            yt_views = int(stats.get("viewCount", 0))
            yt_likes = int(stats.get("likeCount", 0))
            yt_comments = int(stats.get("commentCount", 0))

        if fb_id and fb_token:
            try:
                # 1. Fetch views, comments, likes, and post_id directly from the Video object
                fb_url = f"https://graph.facebook.com/v19.0/{fb_id}"
                params = {
                    "fields": "views,comments.summary(true),likes.summary(true),post_id",
                    "access_token": fb_token
                }
                r = requests.get(fb_url, params=params, timeout=10)
                if r.status_code == 200:
                    fb_data = r.json()
                    fb_views = int(fb_data.get("views", 0) or 0)
                    fb_comments = int(fb_data.get("comments", {}).get("summary", {}).get("total_count", 0) or 0)
                    fb_likes = int(fb_data.get("likes", {}).get("summary", {}).get("total_count", 0) or 0)
                    
                    # Fetch shares from the associated post object if available
                    post_id = fb_data.get("post_id")
                    if post_id:
                        try:
                            p_url = f"https://graph.facebook.com/v19.0/{post_id}"
                            p_res = requests.get(p_url, params={"fields": "shares", "access_token": fb_token}, timeout=5)
                            if p_res.status_code == 200:
                                p_data = p_res.json()
                                fb_shares = int(p_data.get("shares", {}).get("count", 0) if isinstance(p_data.get("shares"), dict) else 0)
                        except Exception:
                            pass
                            
                # 2. Query video_insights for average watch time & fallback plays
                fb_avg_watch_sec = 0.0
                try:
                    ins_url = f"https://graph.facebook.com/v19.0/{fb_id}/video_insights"
                    ins_params = {
                        "metric": "post_video_avg_time_watched,fb_reels_total_plays,blue_reels_play_count",
                        "access_token": fb_token
                    }
                    ins_r = requests.get(ins_url, params=ins_params, timeout=10)
                    if ins_r.status_code == 200:
                        ins_data = ins_r.json().get("data", [])
                        for m in ins_data:
                            m_name = m.get("name")
                            vals = m.get("values", [])
                            if not vals:
                                continue
                            val = vals[0].get("value", 0)
                            if m_name == "post_video_avg_time_watched":
                                fb_avg_watch_sec = round(float(val) / 1000.0, 2)
                            elif m_name in ["fb_reels_total_plays", "blue_reels_play_count"]:
                                if int(val) > fb_views:
                                    fb_views = int(val)
                except Exception:
                    pass
            except Exception as e:
                print(f"Could not fetch Facebook metrics for {fb_id}: {e}")

        yt_reward = calculate_youtube_reward(yt_views, yt_likes, yt_comments, recorded_at_str=recorded_at)
        fb_reward = calculate_facebook_reward(fb_views, fb_shares, fb_comments, fb_likes, recorded_at_str=recorded_at, avg_watch_sec=fb_avg_watch_sec)
        combined_score = round(yt_reward + fb_reward, 2)

        # Only update metrics we actually fetched — never overwrite real data with zeros
        updates = {"viral_score": combined_score}
        if yt_id and yt_id in yt_stats_map:
            updates["yt_views"] = yt_views
            updates["yt_likes"] = yt_likes
            updates["yt_comments"] = yt_comments
        if fb_id and fb_token:
            # Preserve existing if current is 0 (API transient failure), else update
            best_views = max(fb_views, int(item.get("fb_views", 0) or 0))
            best_shares = max(fb_shares, int(item.get("fb_shares", 0) or 0))
            best_comments = max(fb_comments, int(item.get("fb_comments", 0) or 0))
            updates["fb_views"] = best_views
            updates["fb_shares"] = best_shares
            updates["fb_comments"] = best_comments
        update_video_metrics(video_id, updates)

    print("Decoupled platform performance ledgers updated successfully.")

def get_rlaf_ai_feedback() -> dict:
    """
    Extracts real-time reward feedback from Supabase to steer AI Story Generation & Viral Remixes.
    - Analyzes which topics, characters, and hooks earned the highest views, velocity, and engagement.
    - Compares view velocity across content formats (100% AI Story vs Viral Remix).
    - Balances Exploitation (scaling winning dynamics) vs Exploration (testing fresh unrestricted genres).
    """
    tracked_videos = get_tracked_videos_for_analytics(limit=50)
    if not tracked_videos:
        return {
            "top_topics": [],
            "low_topics": [],
            "top_categories": [],
            "summary": "Channel starting fresh. Explore unrestricted creative concepts across diverse comedic niches.",
            "strategy_mode": "EXPLORATION (Unrestricted Innovation)",
            "recommended_format": "auto"
        }

    sorted_videos = sorted(
        tracked_videos, 
        key=lambda v: (
            calculate_youtube_reward(v.get("yt_views", 0), v.get("yt_likes", 0), v.get("yt_comments", 0), recorded_at_str=v.get("recorded_at")) +
            calculate_facebook_reward(v.get("fb_views", 0), v.get("fb_shares", 0), v.get("fb_comments", 0), v.get("fb_likes", 0), recorded_at_str=v.get("recorded_at"))
        ), 
        reverse=True
    )

    top_topics = []
    low_topics = []
    top_categories = []

    for v in sorted_videos[:8]:
        title = v.get("title", "")
        tot_views = (v.get("yt_views", 0) or 0) + (v.get("fb_views", 0) or 0)
        cat = v.get("category", "")
        if tot_views > 10 or v.get("viral_score", 0) > 0:
            top_topics.append(title[:60])
            if cat and cat not in top_categories:
                top_categories.append(cat)

    for v in sorted_videos[-6:]:
        title = v.get("title", "")
        tot_views = (v.get("yt_views", 0) or 0) + (v.get("fb_views", 0) or 0)
        if tot_views <= 10:
            low_topics.append(title[:60])

    # --- FORMAT VELOCITY COMPARISON (AI Story vs Viral Remix) ---
    story_rewards = []
    remix_rewards = []
    for v in tracked_videos[:20]:
        hook_style = (v.get("hook_style") or "").lower()
        score = (
            calculate_youtube_reward(v.get("yt_views", 0), v.get("yt_likes", 0), v.get("yt_comments", 0), recorded_at_str=v.get("recorded_at")) +
            calculate_facebook_reward(v.get("fb_views", 0), v.get("fb_shares", 0), v.get("fb_comments", 0), v.get("fb_likes", 0), recorded_at_str=v.get("recorded_at"))
        )
        if "story" in hook_style or "animation" in hook_style:
            story_rewards.append(score)
        elif "remix" in hook_style or "curation" in hook_style:
            remix_rewards.append(score)

    avg_story_score = (sum(story_rewards) / len(story_rewards)) if story_rewards else 10.0
    avg_remix_score = (sum(remix_rewards) / len(remix_rewards)) if remix_rewards else 10.0

    if remix_rewards and avg_remix_score > avg_story_score * 1.2:
        recommended_format = "remix"
    elif story_rewards and avg_story_score > avg_remix_score * 1.2:
        recommended_format = "ai_story"
    else:
        # If balanced or unexplored, alternate or explore with slight random variance
        recommended_format = "remix" if random.random() < 0.50 else "ai_story"

    is_exploration = random.random() < 0.30 or len(top_topics) == 0
    strategy_mode = "EXPLORATION (Unrestricted Innovation)" if is_exploration else "EXPLOITATION (Precision Scaling on Winning Dynamics)"

    summary = (
        f"Audience responding strongly to: {', '.join(top_topics[:3])}. "
        f"Format velocity favors: {recommended_format.upper()}. "
        f"Avoid repeating flat dynamics from: {', '.join(low_topics[:2])}."
        if top_topics else f"Exploring fresh creative frontiers with 0 thematic boundaries (Recommended Format: {recommended_format.upper()})."
    )

    print(f"\n[RLAF ADAPTIVE ENGINE] Mode: {strategy_mode} | Recommended Format: {recommended_format.upper()}")
    if top_topics:
        safe_topics = [t.encode('ascii', 'replace').decode() for t in top_topics[:3]]
        print(f"[RLAF ADAPTIVE ENGINE] Reinforcing Top Concepts: {safe_topics}")
    if low_topics:
        safe_low = [t.encode('ascii', 'replace').decode() for t in low_topics[:2]]
        print(f"[RLAF ADAPTIVE ENGINE] Downweighting Low Concepts: {safe_low}")

    return {
        "top_topics": top_topics,
        "low_topics": low_topics,
        "top_categories": top_categories,
        "summary": summary,
        "strategy_mode": strategy_mode,
        "recommended_format": recommended_format,
        "avg_story_score": round(avg_story_score, 2),
        "avg_remix_score": round(avg_remix_score, 2)
    }

def run_meta_optimizer(category: str, platform: str = "youtube", epsilon: float = 0.20) -> dict:
    """
    Independent Platform RLAF Meta-Agent:
    - Analyzes YouTube and Facebook separately so platform-specific audience trends are never conflated.
    - YouTube Strategy: Focuses on search queries, 1st-second retention loops, #shorts #viral, and comment velocity.
    - Facebook Strategy: Focuses on feed shares (120x multiplier), relatable emotional twists, and comment debate hooks.
    """
    is_exploration = random.random() < epsilon
    mode_tag = "EXPLORATION (Wild-Card Innovation)" if is_exploration else "EXPLOITATION (Precision Scaling)"
    profile_key = f"{category}_{platform}"
    print(f"\n--- [RLAF META-AGENT ({platform.upper()})] Mode: {mode_tag} for '{category}' ---")
    
    tracked_videos = get_tracked_videos_for_analytics(limit=50)
    cat_videos = [v for v in tracked_videos if v.get("category") == category]
    
    if platform == "youtube":
        platform_videos = [v for v in cat_videos if v.get("yt_video_id") and str(v.get("yt_video_id")).strip() != ""]
        if len(platform_videos) < 2:
            print(f"Historical YouTube reward data accumulating for '{category}'. Initializing baseline directives.")
            return get_active_profile(category, platform="youtube")
            
        batch_stats = [{
            "title": v.get("title"),
            "yt_views": v.get("yt_views", 0),
            "yt_likes": v.get("yt_likes", 0),
            "yt_comments": v.get("yt_comments", 0),
            "yt_score": calculate_youtube_reward(v.get("yt_views", 0), v.get("yt_likes", 0), v.get("yt_comments", 0), recorded_at_str=v.get("recorded_at"))
        } for v in platform_videos[:15]]
        platform_focus = """
        PLATFORM TARGET: YOUTUBE SHORTS
        - YouTube algorithm heavily prioritizes high watch-percentage retention and comment activity.
        - Craft search keywords for YouTube Search & Suggested Videos.
        - Title formulas must incorporate curiosity loops, strong emojis, and #shorts #viral.
        """
    else:
        platform_videos = [v for v in cat_videos if v.get("fb_video_id") and str(v.get("fb_video_id")).strip() != ""]
        if len(platform_videos) < 2:
            print(f"Historical Facebook reward data accumulating for '{category}'. Initializing baseline directives.")
            return get_active_profile(category, platform="facebook")
            
        batch_stats = [{
            "title": v.get("title"),
            "fb_views": v.get("fb_views", 0),
            "fb_shares": v.get("fb_shares", 0),
            "fb_comments": v.get("fb_comments", 0),
            "fb_likes": v.get("fb_likes", 0),
            "fb_score": calculate_facebook_reward(v.get("fb_views", 0), v.get("fb_shares", 0), v.get("fb_comments", 0), v.get("fb_likes", 0), recorded_at_str=v.get("recorded_at"))
        } for v in platform_videos[:15]]
        platform_focus = """
        PLATFORM TARGET: FACEBOOK REELS
        - Facebook algorithm heavily prioritizes SHARES to friends/feeds and active comment section debates.
        - Craft relatable, highly shareable curiosity hooks.
        - Comment CTA must provoke polarizing debate or interactive voting.
        """
        
    recent_batch_json = json.dumps(batch_stats, indent=2)
    
    strategy_instruction = f"""
    {platform_focus}
    STRATEGY MODE: {'EXPLORATION (20% Wild-Card Innovation)' if is_exploration else 'EXPLOITATION (80% Precision Scaling)'}
    """
    
    prompt = f"""
    [SYSTEM: AUTONOMOUS REINFORCEMENT LEARNING META-AGENT ({platform.upper()} DEDICATED)]

    You are an autonomous AI Agent optimizing EXCLUSIVELY for {platform.upper()}.
    Do NOT conflate cross-platform data. Your decisions apply specifically to {platform.upper()}.

    HISTORICAL PERFORMANCE LEDGER ({platform.upper()} ONLY):
    {{
      "category": "{category}",
      "platform": "{platform}",
      "recent_batch_performance": {recent_batch_json}
    }}

    {strategy_instruction}

    ATTRIBUTION TAXONOMY CONSTRAINTS:
    - Penalty Tags: [HOOK_PACING_LAG, WEAK_CURIOSITY_GAP, NICHE_SATURATION, FLAT_CTA, LOW_CONTRAST_SETUP, AUDIO_MISMATCH]
    - Reward Tags: [IMMEDIATE_PHYSICAL_TWIST, STRONG_CURIOSITY_LOOP, HIGH_DEBATE_CTA, EMOTIONAL_RELATABILITY, FAST_PACED_EDIT, SENSORY_HOOK]

    OUTPUT FORMAT (Strictly valid JSON only, no markdown wrappers):
    {{
      "agent_evaluation": {{
        "reward_trend": "GROWING",
        "strategy_mode": "{'EXPLORATION' if is_exploration else 'EXPLOITATION'}",
        "penalty_root_causes": ["HOOK_PACING_LAG: description"],
        "reward_drivers": ["IMMEDIATE_PHYSICAL_TWIST: description"],
        "emergent_n_rules": [
          "RULE_1: Platform specific hook directive"
        ]
      }},
      "phase_1_discovery_directives": {{
        "pivoted_content_theme": "{category.split('_')[0]}",
        "primary_search_queries": [
          "query_1_for_{platform}",
          "query_2_for_{platform}"
        ],
        "target_subcategories": ["specific_subniche"]
      }},
      "phase_4_vision_gate_directives": {{
        "optimal_clip_duration": "10-16 seconds",
        "mandatory_visual_hooks": [
          "Immediate motion in 0.0s-1.2s"
        ],
        "instant_reject_triggers": [
          "Static build-up over 2.0s"
        ],
        "custom_evaluation_rules": [
          "High visual contrast"
        ]
      }},
      "phase_6_copywriting_directives": {{
        "title_formulas": [
          "Title crafted specifically for {platform}"
        ],
        "description_intro": "Intro for {platform}",
        "comment_cta": "Engaging question for {platform}",
        "hashtag_stack": ["#shorts", "#viral", "#trending"] if "{platform}" == "youtube" else ["#reels", "#viral", "#comedy"],
        "tag_keywords": ["viral", "comedy", "shorts"]
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
    
    # Model Waterfall: Verified active Google GenAI model
    model_names = [
        "gemini-3.6-flash",
        "gemini-2.5-flash",
    ]
    
    global _LOCKED_KEY_INDEX
    if '_LOCKED_KEY_INDEX' not in globals():
        _LOCKED_KEY_INDEX = 0
        
    num_keys = len(api_keys)
    if num_keys == 0:
        return get_active_profile(category, platform=platform)

    for model in model_names:
        # Start from the currently locked key and cycle through all keys
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
                    
                    profile_data = json.loads(cleaned_text)
                    validated_profile = AdaptiveProfileSchema(**profile_data).model_dump()
                    save_creative_profile(profile_key, validated_profile)
                    
                    # Lock onto this working key for future calls
                    _LOCKED_KEY_INDEX = key_idx
                    print(f"[{platform.upper()}] Locked active API key index: #{key_idx + 1} (Model: {model})")
                    return validated_profile
            except Exception as e:
                print(f"Model {model} notice on key #{key_idx + 1}: {str(e)[:70]}. Trying next API key...")
                continue
                
    return get_active_profile(category, platform=platform)

def get_active_profile(category: str, platform: str = "youtube") -> dict:
    """
    Retrieves platform-specific dynamic profile (e.g. 'funny_short_youtube' vs 'funny_short_facebook'),
    falling back to base category baselines if needed.
    """
    profile_key = f"{category}_{platform}"
    db_profile = get_creative_profile(profile_key)
    if not db_profile:
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
                ] if platform == "youtube" else [
                    "You won't believe what happened at the end! 😂💀",
                    "When trying to be cool goes completely wrong 🤣",
                    "I can't stop laughing at this! 😂 Tag someone who would do this"
                ],
                "comment_cta": "Which clip made you laugh the hardest? Vote below! 👇" if platform == "youtube" else "Tag a friend who would definitely fail like this! 😂👇",
                "hashtag_stack": ["#funny", "#epicfails", "#meme", "#viral", "#trynottolaugh"] if platform == "youtube" else ["#reels", "#funnyreels", "#epicfail", "#viralpost"],
                "tag_keywords": ["funny", "shorts", "viral", "reaction", "comedy"]
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
                ] if platform == "youtube" else [
                    "This is the sweetest thing you'll see all day 🥹❤️",
                    "Pure relationship goals right here! ❤️ Share with your loved one",
                    "The way they look at each other is everything ❤️"
                ],
                "comment_cta": "What's the sweetest couple moment you've ever witnessed? Drop a comment below! 👇",
                "hashtag_stack": ["#romantic", "#couplegoals", "#cute", "#love", "#wholesome"] if platform == "youtube" else ["#love", "#couplegoals", "#wholesome", "#relationshipgoals"],
                "tag_keywords": ["romantic", "couple", "love", "cute", "wholesome"]
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
                ] if platform == "youtube" else [
                    "Would you eat this or pass? Rate 1 to 10 below! 🍔🍕",
                    "This looks unbelievable! Tag someone who needs to cook this for you 🤤",
                    "The most satisfying food clip you will see today! 🧀🔥"
                ],
                "comment_cta": "Would you eat this or pass? Rate it 1 to 10 in the comments below! 👇",
                "hashtag_stack": ["#food", "#streetfood", "#delicious", "#recipe", "#satisfying"],
                "tag_keywords": ["food", "cooking", "recipe", "streetfood", "delicious"]
            }
        }
    }
    
    return baselines.get(base_theme, baselines["funny"])

def send_telegram_report(category: str, yt_profile: dict, fb_profile: dict = None, upload_summary: dict = None) -> bool:
    """
    Sends a clear, decoupled multi-platform update to Telegram covering:
    1. YouTube Shorts Performance & Directives
    2. Facebook Reels Performance & Directives
    3. New Uploads Posted with Platform-Specific Titles
    """
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        print("Telegram notification skipped: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not configured.")
        return False
        
    fb_profile = fb_profile or yt_profile
    base_cat = category.split("_")[0].title()
    
    # --- 1. Calculate Platform Metrics ---
    yt_views_total, yt_likes_total, yt_comments_total = 0, 0, 0
    fb_views_total, fb_shares_total, fb_comments_total = 0, 0, 0
    top_yt_title, top_yt_score = "None yet", 0.0
    top_fb_title, top_fb_score = "None yet", 0.0
    
    try:
        tracked_videos = get_tracked_videos_for_analytics(limit=50)
        cat_videos = [v for v in tracked_videos if v.get("category") == category] if tracked_videos else []
        # Fallback: if no videos match the exact category, use ALL tracked videos
        if not cat_videos and tracked_videos:
            cat_videos = tracked_videos
        if cat_videos:
            yt_views_total = sum(v.get("yt_views", 0) for v in cat_videos)
            yt_likes_total = sum(v.get("yt_likes", 0) for v in cat_videos)
            yt_comments_total = sum(v.get("yt_comments", 0) for v in cat_videos)
            
            fb_views_total = sum(v.get("fb_views", 0) for v in cat_videos)
            fb_shares_total = sum(v.get("fb_shares", 0) for v in cat_videos)
            fb_comments_total = sum(v.get("fb_comments", 0) for v in cat_videos)
            
            best_yt = max(cat_videos, key=lambda v: calculate_youtube_reward(v.get("yt_views", 0), v.get("yt_likes", 0), v.get("yt_comments", 0)))
            top_yt_title = best_yt.get("title", "N/A")
            top_yt_score = calculate_youtube_reward(best_yt.get("yt_views", 0), best_yt.get("yt_likes", 0), best_yt.get("yt_comments", 0))
            
            best_fb = max(cat_videos, key=lambda v: calculate_facebook_reward(v.get("fb_views", 0), v.get("fb_shares", 0), v.get("fb_comments", 0), v.get("fb_likes", 0)))
            top_fb_title = best_fb.get("title", "N/A")
            top_fb_score = calculate_facebook_reward(best_fb.get("fb_views", 0), best_fb.get("fb_shares", 0), best_fb.get("fb_comments", 0), best_fb.get("fb_likes", 0))
    except Exception as e:
        print(f"Note: Could not calculate separate platform metrics: {e}")

    # --- YouTube Insights ---
    yt_eval = yt_profile.get("agent_evaluation", {})
    yt_driver = yt_eval.get("reward_drivers", ["High watch-percentage retention"])[0]
    yt_driver_clean = yt_driver.split(":", 1)[-1].strip() if ":" in yt_driver else yt_driver
    yt_query = yt_profile.get("phase_1_discovery_directives", {}).get("primary_search_queries", ["viral shorts"])[0]
    yt_mode = "🔥 Scaling Proven Winners" if "EXPLOIT" in yt_eval.get("strategy_mode", "") else "🧪 Testing Fresh Viral Niches"

    # --- Facebook Insights ---
    fb_eval = fb_profile.get("agent_evaluation", {})
    fb_driver = fb_eval.get("reward_drivers", ["High direct feed shares"])[0]
    fb_driver_clean = fb_driver.split(":", 1)[-1].strip() if ":" in fb_driver else fb_driver
    fb_cta = fb_profile.get("phase_6_copywriting_directives", {}).get("comment_cta", "Tag a friend below! 👇")
    fb_mode = "🔥 Scaling Share-Heavy Formats" if "EXPLOIT" in fb_eval.get("strategy_mode", "") else "🧪 Testing New Viral Hooks"

    # --- Uploads ---
    short_title = upload_summary.get("short_title", "Published Successfully") if upload_summary else "Published"
    comp_title = upload_summary.get("comp_title", "Published Successfully") if upload_summary else "Published"

    message = f"""
🤖 <b>@DailyDosOfFun — Multi-Platform AI Update</b>
━━━━━━━━━━━━━━━━━━━━
📌 <b>Target Theme:</b> {base_cat} Moments

🔴 <b>1. YOUTUBE SHORTS ENGINE:</b>
  • <b>Reach:</b> {yt_views_total:,} views | {yt_likes_total:,} likes | {yt_comments_total:,} comments
  • <b>Top Video:</b> "{top_yt_title}" ({top_yt_score:+.1f} pts)
  • <b>Strategy:</b> {yt_mode}
  • <b>What's Working:</b> {yt_driver_clean}
  • <b>Search Focus:</b> <i>"{yt_query}"</i>

🔵 <b>2. FACEBOOK REELS ENGINE:</b>
  • <b>Reach:</b> {fb_views_total:,} views | {fb_shares_total:,} shares | {fb_comments_total:,} comments
  • <b>Top Video:</b> "{top_fb_title}" ({top_fb_score:+.1f} pts)
  • <b>Strategy:</b> {fb_mode}
  • <b>What's Working:</b> {fb_driver_clean}
  • <b>Engagement Hook:</b> <i>"{fb_cta}"</i>

━━━━━━━━━━━━━━━━━━━━
🚀 <b>3. NEW VIDEOS POSTED THIS RUN:</b>
🎬 <b>Short:</b>
{short_title}

📼 <b>Compilation:</b>
{comp_title}
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
