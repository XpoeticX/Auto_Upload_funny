import os
import json
import time
import subprocess
import shutil
import re
import math
from typing import Dict, List, Optional
from pydantic import BaseModel, Field
from PIL import Image, ImageDraw, ImageFont
from google import genai
from app.video.ai_diffusion import (
    generate_ai_video_from_prompt,
    generate_ai_video_from_image,
    generate_gemini_omni_video,
    generate_hero_keyframe,
    is_video_empty,
    generate_pan_zoom_fallback,
    reframe_hero_for_scene
)
from app.analytics.engine import get_rlaf_ai_feedback
from app.story.audio_director import build_scene_audio_timeline
from app.database import get_tracked_videos_for_analytics

class FoleyCue(BaseModel):
    timestamp_sec: float
    sfx: str
    volume: float = 2.0

class Protagonist(BaseModel):
    name: str
    visual_identity: str  # Detailed physical description for prompt consistency

class AudioConfig(BaseModel):
    bgm_style: str = "bouncy_comedy_loop"
    bgm_base_volume: float = 0.75
    target_loudnorm_lufs: float = -14.0

class StoryScene(BaseModel):
    scene_index: int = Field(default=1, alias="scene_number")
    arc_phase: str = Field(default="Hook & Rising Action", alias="act_name")
    duration_sec: float = 2.8
    diffusion_prompt: str = Field(default="", alias="visual_prompt")
    negative_prompt: str = "static, blurry, 2D, watermark, text, low quality, distorted"
    dialogue: Optional[str] = None  # Character voice acting line
    foley_cues: Optional[List[FoleyCue]] = None
    # Legacy fields (backward compat)
    foley_sound_type: Optional[str] = None
    foley_description: Optional[str] = None

    class Config:
        populate_by_name = True

class ViralStoryScript(BaseModel):
    story_title: str = Field(default="", alias="title")
    niche: Optional[str] = None
    protagonist: Optional[Protagonist] = None
    environment: Optional[str] = None
    # Legacy fields
    character_name: Optional[str] = None
    character_description: Optional[str] = None
    scenes: List[StoryScene]
    audio_config: Optional[AudioConfig] = None
    music_vibe: Optional[str] = None
    yt_title: str = ""
    fb_title: str = ""
    tags: List[str] = []
    related_queries: Optional[List[str]] = None
    hook_text: Optional[str] = None
    cta_text: Optional[str] = None

FALLBACK_CONCEPTS = [
    {
        "title": "Hamster Chef & The Anti-Gravity Golden Egg",
        "niche": "Animal Slapstick",
        "character_name": "Chester the Hamster Chef",
        "character_description": "Chubby adorable hamster chef wearing a tiny white toque chef hat, fluffy fur, sparkling eyes",
        "protagonist": {
            "name": "Chester",
            "visual_identity": "Chubby adorable hamster chef wearing a tiny white toque chef hat, fluffy fur, sparkling eyes"
        },
        "environment": "Modern sunlit kitchen with bright tiles and wooden countertops",
        "scenes": [
            {
                "scene_index": 1,
                "arc_phase": "Hook & Immediate Action",
                "duration_sec": 2.5,
                "diffusion_prompt": "Chubby adorable hamster chef wearing a tiny white toque chef hat, fluffy fur, sparkling eyes, curiously inspects glowing golden egg on counter in a modern sunlit kitchen. Egg suddenly levitates, hyper-detailed 3d pixar animation style.",
                "negative_prompt": "static, blurry, 2D, talking, watermark, text, low quality",
                "foley_cues": [
                    {"timestamp_sec": 0.5, "sfx": "whoosh", "volume": 1.8},
                    {"timestamp_sec": 1.5, "sfx": "rising_hum", "volume": 2.0}
                ]
            },
            {
                "scene_index": 2,
                "arc_phase": "Conflict Spike",
                "duration_sec": 3.0,
                "diffusion_prompt": "Chubby adorable hamster chef wearing a tiny white toque chef hat tumbling playfully in zero-gravity in a modern sunlit kitchen. Pots, pans, and a flour tornado spinning wildly, golden egg bouncing off walls, hyper-detailed 3d pixar animation style.",
                "negative_prompt": "static, blurry, 2D, talking, watermark, text, low quality",
                "foley_cues": [
                    {"timestamp_sec": 0.5, "sfx": "clatter_multi", "volume": 2.5},
                    {"timestamp_sec": 1.8, "sfx": "whoosh_fast", "volume": 2.2}
                ]
            },
            {
                "scene_index": 3,
                "arc_phase": "The Comeback",
                "duration_sec": 2.5,
                "diffusion_prompt": "Chubby adorable hamster chef wearing a tiny white toque chef hat floating upside down, violently slamming his paw on a glowing red A-GRAV REVERSE button on the wall of the modern sunlit kitchen, hyper-detailed 3d pixar animation style.",
                "negative_prompt": "static, blurry, 2D, talking, watermark, text, low quality",
                "foley_cues": [
                    {"timestamp_sec": 1.0, "sfx": "mechanical_click", "volume": 2.8},
                    {"timestamp_sec": 2.0, "sfx": "boing", "volume": 2.2}
                ]
            },
            {
                "scene_index": 4,
                "arc_phase": "Rising Action 2",
                "duration_sec": 3.0,
                "diffusion_prompt": "Gravity violently snaps back in the modern sunlit kitchen, pots and pans crashing down. Chubby adorable hamster chef wearing a tiny white toque chef hat playfully dives through the air wielding a wire mesh strainer net, hyper-detailed 3d pixar animation style.",
                "negative_prompt": "static, blurry, 2D, talking, watermark, text, low quality",
                "foley_cues": [
                    {"timestamp_sec": 0.5, "sfx": "crash_multi", "volume": 2.8},
                    {"timestamp_sec": 1.5, "sfx": "whoosh", "volume": 2.0}
                ]
            },
            {
                "scene_index": 5,
                "arc_phase": "Climax Payoff",
                "duration_sec": 3.0,
                "diffusion_prompt": "Golden egg caught perfectly in the net. Chubby adorable hamster chef wearing a tiny white toque chef hat smiling triumphantly in the modern sunlit kitchen, magical glowing rings around the egg, hyper-detailed 3d pixar animation style.",
                "negative_prompt": "static, blurry, 2D, talking, watermark, text, low quality",
                "foley_cues": [
                    {"timestamp_sec": 1.0, "sfx": "ding_high_confirm", "volume": 2.5},
                    {"timestamp_sec": 2.0, "sfx": "whoosh_high", "volume": 1.8}
                ]
            }
        ],
        "audio_config": {"bgm_style": "bouncy_comedy_loop", "bgm_base_volume": 0.75, "target_loudnorm_lufs": -14.0},
        "music_vibe": "bouncy_comedy",
        "yt_title": "Hamster Chef vs The Anti-Gravity Golden Egg! 🐹🥚✨ #shorts #animation #viral #funny",
        "fb_title": "He was NOT expecting the egg to do THAT! 😱🍳 Look at his reaction at the end! 😂 Tag a friend!",
        "tags": ["shorts", "hamster", "animation", "3danimation", "pixar", "comedy", "viral", "funny", "goldenegg"]
    },
    {
        "title": "Shark Chef's Sneaker Recipe",
        "niche": "Surreal Animal Comedy",
        "character_name": "Chef Jaws",
        "character_description": "Muscular anthropomorphic shark wearing a chef apron, sharp teeth",
        "protagonist": {
            "name": "Chef Jaws",
            "visual_identity": "Muscular anthropomorphic shark wearing a chef apron, sharp teeth"
        },
        "environment": "Luxury kitchen with dark marble counters and neon accents",
        "scenes": [
            {
                "scene_index": 1,
                "arc_phase": "Hook & Immediate Action",
                "duration_sec": 2.5,
                "diffusion_prompt": "Muscular anthropomorphic shark wearing a chef apron chopping a colorful Nike sneaker on cutting board in a luxury kitchen. Laces suddenly snap back knocking his hat into a flaming stove, hyper-detailed 3d pixar animation style.",
                "negative_prompt": "static, blurry, 2D, talking, watermark, text, low quality",
                "foley_cues": [
                    {"timestamp_sec": 0.5, "sfx": "knife_chop", "volume": 2.0},
                    {"timestamp_sec": 1.5, "sfx": "boing", "volume": 1.8}
                ]
            },
            {
                "scene_index": 2,
                "arc_phase": "Conflict Spike",
                "duration_sec": 3.0,
                "diffusion_prompt": "Luxury kitchen filling with smoke. Sneaker pieces flying through the air, muscular anthropomorphic shark wearing a chef apron panicking and waving his fins wildly, hyper-detailed 3d pixar animation style.",
                "negative_prompt": "static, blurry, 2D, talking, watermark, text, low quality",
                "foley_cues": [
                    {"timestamp_sec": 0.5, "sfx": "sizzle", "volume": 2.5},
                    {"timestamp_sec": 1.5, "sfx": "whoosh", "volume": 1.8}
                ]
            },
            {
                "scene_index": 3,
                "arc_phase": "The Comeback",
                "duration_sec": 2.5,
                "diffusion_prompt": "Muscular anthropomorphic shark wearing a chef apron grins fiercely, dramatically pulling out dual glowing cleavers amidst the smoke in the luxury kitchen, hyper-detailed 3d pixar animation style.",
                "negative_prompt": "static, blurry, 2D, talking, watermark, text, low quality",
                "foley_cues": [
                    {"timestamp_sec": 0.5, "sfx": "whoosh_fast", "volume": 2.2},
                    {"timestamp_sec": 1.5, "sfx": "ding", "volume": 1.5}
                ]
            },
            {
                "scene_index": 4,
                "arc_phase": "Rising Action 2",
                "duration_sec": 3.0,
                "diffusion_prompt": "Muscular anthropomorphic shark wearing a chef apron performing a lightning-speed dicing chain reaction mid-air in the luxury kitchen. Sneaker ingredients flying into perfect formation, hyper-detailed 3d pixar animation style.",
                "negative_prompt": "static, blurry, 2D, talking, watermark, text, low quality",
                "foley_cues": [
                    {"timestamp_sec": 0.5, "sfx": "knife_chop", "volume": 2.5},
                    {"timestamp_sec": 1.2, "sfx": "whoosh_fast", "volume": 2.0},
                    {"timestamp_sec": 2.2, "sfx": "whoosh_high", "volume": 2.0}
                ]
            },
            {
                "scene_index": 5,
                "arc_phase": "Climax Payoff",
                "duration_sec": 3.0,
                "diffusion_prompt": "Muscular anthropomorphic shark wearing a chef apron proudly presents a gourmet sneaker burger on a golden platter in a sparkling clean luxury kitchen. Boss triumph pose, hyper-detailed 3d pixar animation style.",
                "negative_prompt": "static, blurry, 2D, talking, watermark, text, low quality",
                "foley_cues": [
                    {"timestamp_sec": 1.0, "sfx": "ding_high_confirm", "volume": 2.5},
                    {"timestamp_sec": 2.0, "sfx": "whoosh", "volume": 1.5}
                ]
            }
        ],
        "audio_config": {"bgm_style": "bouncy_comedy_loop", "bgm_base_volume": 0.75, "target_loudnorm_lufs": -14.0},
        "music_vibe": "bouncy_comedy",
        "yt_title": "Who Let The Shark In The Kitchen?! 🦈👟 #shorts #viral #funny",
        "fb_title": "His cooking skills are 10/10 but the recipe is questionable! 😂🦈 Tag a friend who would eat this!",
        "tags": ["shorts", "shark", "animation", "3danimation", "food", "viral", "comedy", "funny"]
    },
    {
        "title": "Baby & The Dancing Mini Cow",
        "niche": "Cute Baby & Animal",
        "character_name": "Baby Leo & Daisy the Cow",
        "character_description": "Chubby laughing cute baby in diaper, rosy cheeks, joyful expression",
        "protagonist": {
            "name": "Baby Leo",
            "visual_identity": "Chubby laughing cute baby in diaper, rosy cheeks, joyful expression"
        },
        "environment": "Soft warm sunlit garden with flower path and a giant mud puddle",
        "scenes": [
            {
                "scene_index": 1,
                "arc_phase": "Hook & Immediate Action",
                "duration_sec": 2.5,
                "diffusion_prompt": "Chubby laughing cute baby in diaper riding a tiny spotted miniature dairy cow on a flower path in a sunlit garden. Cow suddenly skids towards a giant mud puddle, baby eyes wide in shock, hyper-detailed 3d pixar animation style.",
                "negative_prompt": "static, blurry, 2D, talking, watermark, text, low quality",
                "foley_cues": [
                    {"timestamp_sec": 0.5, "sfx": "whoosh", "volume": 1.8},
                    {"timestamp_sec": 1.5, "sfx": "slide_whistle_down", "volume": 2.0}
                ]
            },
            {
                "scene_index": 2,
                "arc_phase": "Conflict Spike",
                "duration_sec": 3.0,
                "diffusion_prompt": "Cow sliding sideways in the sunlit garden, mud splashing violently. Chubby laughing cute baby in diaper screaming with absolute joy as they drift, hyper-detailed 3d pixar animation style.",
                "negative_prompt": "static, blurry, 2D, talking, watermark, text, low quality",
                "foley_cues": [
                    {"timestamp_sec": 0.5, "sfx": "clatter_thump", "volume": 2.2},
                    {"timestamp_sec": 2.0, "sfx": "whoosh_fast", "volume": 1.8}
                ]
            },
            {
                "scene_index": 3,
                "arc_phase": "The Comeback",
                "duration_sec": 2.5,
                "diffusion_prompt": "Chubby laughing cute baby in diaper playfully twists the cow's ear like a motorcycle throttle. The miniature cow pops a heroic wheelie in the sunlit garden, hyper-detailed 3d pixar animation style.",
                "negative_prompt": "static, blurry, 2D, talking, watermark, text, low quality",
                "foley_cues": [
                    {"timestamp_sec": 0.5, "sfx": "mechanical_click", "volume": 2.0},
                    {"timestamp_sec": 1.5, "sfx": "boing", "volume": 2.5}
                ]
            },
            {
                "scene_index": 4,
                "arc_phase": "Rising Action 2",
                "duration_sec": 3.0,
                "diffusion_prompt": "Miniature cow doing aerial tricks and a backflip completely over the mud puddle in the sunlit garden. Chubby laughing cute baby in diaper holding on tight as flowers scatter in the wind, hyper-detailed 3d pixar animation style.",
                "negative_prompt": "static, blurry, 2D, talking, watermark, text, low quality",
                "foley_cues": [
                    {"timestamp_sec": 0.5, "sfx": "whoosh_high", "volume": 2.2},
                    {"timestamp_sec": 1.5, "sfx": "whoosh", "volume": 2.0}
                ]
            },
            {
                "scene_index": 5,
                "arc_phase": "Climax Payoff",
                "duration_sec": 3.0,
                "diffusion_prompt": "Epic superhero landing on the blooming flower bed in the sunlit garden. Chubby laughing cute baby in diaper and mini cow wearing matching tiny sunglasses, giving high-fives with huge smiles, hyper-detailed 3d pixar animation style.",
                "negative_prompt": "static, blurry, 2D, talking, watermark, text, low quality",
                "foley_cues": [
                    {"timestamp_sec": 1.0, "sfx": "bonk", "volume": 2.0},
                    {"timestamp_sec": 2.0, "sfx": "ding_high_confirm", "volume": 2.5}
                ]
            }
        ],
        "audio_config": {"bgm_style": "bouncy_comedy_loop", "bgm_base_volume": 0.75, "target_loudnorm_lufs": -14.0},
        "music_vibe": "bouncy_comedy",
        "yt_title": "The Cutest Duo In History! 👶🐮❤️ #shorts #viral #cutebaby",
        "fb_title": "I cannot stop smiling at this! 😭🐮 Tag someone who needs cuteness today! 👇",
        "tags": ["shorts", "cutebaby", "cow", "animation", "3danimation", "viral", "cute"]
    },
    {
        "title": "The Cockroach Family Dinner",
        "niche": "Role Reversal",
        "character_name": "Papa Cockroach",
        "character_description": "Anthropomorphic cartoon cockroach father wearing striped pajamas, small glasses",
        "protagonist": {
            "name": "Papa Cockroach",
            "visual_identity": "Anthropomorphic cartoon cockroach father wearing striped pajamas, small glasses"
        },
        "environment": "Cozy dining room inside a miniature wooden dollhouse",
        "scenes": [
            {
                "scene_index": 1,
                "arc_phase": "Hook & Immediate Action",
                "duration_sec": 2.5,
                "diffusion_prompt": "Anthropomorphic cartoon cockroach father wearing striped pajamas enjoying tiny pie at dinner table inside a miniature wooden dollhouse. Suddenly a giant cartoon human foot steps outside shaking the room, hyper-detailed 3d pixar animation style.",
                "negative_prompt": "static, blurry, 2D, talking, watermark, text, low quality",
                "foley_cues": [
                    {"timestamp_sec": 1.0, "sfx": "bonk", "volume": 2.8}
                ]
            },
            {
                "scene_index": 2,
                "arc_phase": "Conflict Spike",
                "duration_sec": 3.0,
                "diffusion_prompt": "Dollhouse dining room shaking violently. Tiny chandelier swinging, plates smashing on the floor. Anthropomorphic cartoon cockroach father wearing striped pajamas and family screaming in panic, hyper-detailed 3d pixar animation style.",
                "negative_prompt": "static, blurry, 2D, talking, watermark, text, low quality",
                "foley_cues": [
                    {"timestamp_sec": 0.5, "sfx": "crash_multi", "volume": 2.8},
                    {"timestamp_sec": 2.0, "sfx": "clatter_multi", "volume": 2.5}
                ]
            },
            {
                "scene_index": 3,
                "arc_phase": "The Comeback",
                "duration_sec": 2.5,
                "diffusion_prompt": "Anthropomorphic cartoon cockroach father wearing striped pajamas calmly taps a tiny remote control inside the dollhouse. A cool miniature red sports car zooms directly into the dining room, hyper-detailed 3d pixar animation style.",
                "negative_prompt": "static, blurry, 2D, talking, watermark, text, low quality",
                "foley_cues": [
                    {"timestamp_sec": 0.5, "sfx": "mechanical_click", "volume": 2.0},
                    {"timestamp_sec": 1.5, "sfx": "whoosh_fast", "volume": 2.5}
                ]
            },
            {
                "scene_index": 4,
                "arc_phase": "Rising Action 2",
                "duration_sec": 3.0,
                "diffusion_prompt": "Wild chase through the wooden dollhouse hallways. The red sports car driven by anthropomorphic cartoon cockroach father wearing striped pajamas dodges giant falling household objects, hyper-detailed 3d pixar animation style.",
                "negative_prompt": "static, blurry, 2D, talking, watermark, text, low quality",
                "foley_cues": [
                    {"timestamp_sec": 0.5, "sfx": "whoosh", "volume": 2.2},
                    {"timestamp_sec": 1.8, "sfx": "object_drop", "volume": 2.5}
                ]
            },
            {
                "scene_index": 5,
                "arc_phase": "Climax Payoff",
                "duration_sec": 3.0,
                "diffusion_prompt": "Anthropomorphic cartoon cockroach father wearing striped pajamas and family speed away safely in the tiny convertible waving happily, leaving the dollhouse behind in a cool exit, hyper-detailed 3d pixar animation style.",
                "negative_prompt": "static, blurry, 2D, talking, watermark, text, low quality",
                "foley_cues": [
                    {"timestamp_sec": 0.5, "sfx": "whoosh_high", "volume": 2.0},
                    {"timestamp_sec": 1.5, "sfx": "ding_high_confirm", "volume": 2.5}
                ]
            }
        ],
        "audio_config": {"bgm_style": "bouncy_comedy_loop", "bgm_base_volume": 0.75, "target_loudnorm_lufs": -14.0},
        "music_vibe": "bouncy_comedy",
        "yt_title": "Inside A Cockroach's Emotional Dinner 😂🪳 #shorts #viral #animation",
        "fb_title": "When you realize cockroaches have family drama too! 😂🪳 Tag a friend who hates bugs!",
        "tags": ["shorts", "ultiduniya", "animation", "3danimation", "comedy", "viral", "funny"]
    },
    {
        "title": "Princess Tomato's Kitchen Escape",
        "niche": "Living Food",
        "character_name": "Princess Tomato",
        "character_description": "Giant glossy cute red tomato with big sparkling anime Pixar eyes, rosy blushing cheeks, wearing a red ribbon bow",
        "protagonist": {
            "name": "Princess Tomato",
            "visual_identity": "Giant glossy cute red tomato with big sparkling anime Pixar eyes, rosy blushing cheeks, wearing a red ribbon bow"
        },
        "environment": "Wooden cutting board on a granite kitchen counter",
        "scenes": [
            {
                "scene_index": 1,
                "arc_phase": "Hook & Immediate Action",
                "duration_sec": 2.5,
                "diffusion_prompt": "Giant glossy cute red tomato with big sparkling anime Pixar eyes, wearing a red ribbon bow sitting on a wooden cutting board on a granite kitchen counter. A heavy chef's cleaver suddenly slams down inches away, hyper-detailed 3d pixar animation style.",
                "negative_prompt": "static, blurry, 2D, talking, watermark, text, low quality",
                "foley_cues": [
                    {"timestamp_sec": 1.5, "sfx": "bonk", "volume": 2.8}
                ]
            },
            {
                "scene_index": 2,
                "arc_phase": "Conflict Spike",
                "duration_sec": 3.0,
                "diffusion_prompt": "Chef desperately chasing with the cleaver on the granite kitchen counter. Giant glossy cute red tomato with big sparkling anime Pixar eyes, wearing a red ribbon bow agilely dodging knives raining down, hyper-detailed 3d pixar animation style.",
                "negative_prompt": "static, blurry, 2D, talking, watermark, text, low quality",
                "foley_cues": [
                    {"timestamp_sec": 0.5, "sfx": "whoosh_fast", "volume": 2.0},
                    {"timestamp_sec": 1.5, "sfx": "knife_chop", "volume": 2.5},
                    {"timestamp_sec": 2.5, "sfx": "knife_chop", "volume": 2.5}
                ]
            },
            {
                "scene_index": 3,
                "arc_phase": "The Comeback",
                "duration_sec": 2.5,
                "diffusion_prompt": "Giant glossy cute red tomato with big sparkling anime Pixar eyes, wearing a red ribbon bow confidently puts on tiny black sunglasses and hops onto a wooden butter knife to surf, hyper-detailed 3d pixar animation style.",
                "negative_prompt": "static, blurry, 2D, talking, watermark, text, low quality",
                "foley_cues": [
                    {"timestamp_sec": 1.0, "sfx": "ding", "volume": 2.0},
                    {"timestamp_sec": 1.8, "sfx": "whoosh", "volume": 2.2}
                ]
            },
            {
                "scene_index": 4,
                "arc_phase": "Rising Action 2",
                "duration_sec": 3.0,
                "diffusion_prompt": "The butter knife grinding along the granite counter edge sending bright sparks. Giant glossy cute red tomato with big sparkling anime Pixar eyes, wearing a red ribbon bow jumping over kitchen obstacles like a pro skater, hyper-detailed 3d pixar animation style.",
                "negative_prompt": "static, blurry, 2D, talking, watermark, text, low quality",
                "foley_cues": [
                    {"timestamp_sec": 0.5, "sfx": "sizzle", "volume": 2.0},
                    {"timestamp_sec": 2.0, "sfx": "whoosh_high", "volume": 2.2}
                ]
            },
            {
                "scene_index": 5,
                "arc_phase": "Climax Payoff",
                "duration_sec": 3.0,
                "diffusion_prompt": "Giant glossy cute red tomato with big sparkling anime Pixar eyes, wearing a red ribbon bow ollies perfectly into a soft fruit basket, making a tiny peace sign with a green stem leaf, hyper-detailed 3d pixar animation style.",
                "negative_prompt": "static, blurry, 2D, talking, watermark, text, low quality",
                "foley_cues": [
                    {"timestamp_sec": 1.0, "sfx": "boing", "volume": 1.8},
                    {"timestamp_sec": 2.0, "sfx": "ding_high_confirm", "volume": 2.8}
                ]
            }
        ],
        "audio_config": {"bgm_style": "bouncy_comedy_loop", "bgm_base_volume": 0.75, "target_loudnorm_lufs": -14.0},
        "music_vibe": "bouncy_comedy",
        "yt_title": "Do NOT Slice The Princess! 🍅🎀😂 #shorts #viral #animation",
        "fb_title": "She was NOT going to become ketchup today! 😎🍅 Tag someone who loves cute things!",
        "tags": ["shorts", "tomato", "cute", "animation", "3danimation", "viral", "comedy"]
    },
    {
        "title": "Chef Leo's Crispy Chicken",
        "niche": "Cat Comedy",
        "character_name": "Chef Leo",
        "character_description": "Chubby ginger cat wearing a white chef toque and headphones",
        "protagonist": {
            "name": "Chef Leo",
            "visual_identity": "Chubby ginger cat wearing a white chef toque and headphones"
        },
        "environment": "Professional stainless steel restaurant kitchen",
        "scenes": [
            {
                "scene_index": 1,
                "arc_phase": "Hook & Immediate Action",
                "duration_sec": 2.5,
                "diffusion_prompt": "Chubby ginger cat wearing a white chef toque and headphones rapidly dicing chicken in a professional stainless steel restaurant kitchen. The cooking pan suddenly catches giant fire, flames shooting up, hyper-detailed 3d pixar animation style.",
                "negative_prompt": "static, blurry, 2D, talking, watermark, text, low quality",
                "foley_cues": [
                    {"timestamp_sec": 0.5, "sfx": "knife_chop", "volume": 2.0},
                    {"timestamp_sec": 1.5, "sfx": "sizzle", "volume": 2.8}
                ]
            },
            {
                "scene_index": 2,
                "arc_phase": "Conflict Spike",
                "duration_sec": 3.0,
                "diffusion_prompt": "Fire spreading to curtains in the professional stainless steel restaurant kitchen, ceiling sprinklers going off raining water. Chubby ginger cat wearing a white chef toque and headphones slipping comically on the wet floor, hyper-detailed 3d pixar animation style.",
                "negative_prompt": "static, blurry, 2D, talking, watermark, text, low quality",
                "foley_cues": [
                    {"timestamp_sec": 0.5, "sfx": "rising_hum", "volume": 2.0},
                    {"timestamp_sec": 2.0, "sfx": "clatter_thump", "volume": 2.5}
                ]
            },
            {
                "scene_index": 3,
                "arc_phase": "The Comeback",
                "duration_sec": 2.5,
                "diffusion_prompt": "Chubby ginger cat wearing a white chef toque and headphones suddenly snaps on cool dark welding goggles and powerfully flips the fiery wok into the air, splashing water everywhere, hyper-detailed 3d pixar animation style.",
                "negative_prompt": "static, blurry, 2D, talking, watermark, text, low quality",
                "foley_cues": [
                    {"timestamp_sec": 0.5, "sfx": "mechanical_click", "volume": 2.5},
                    {"timestamp_sec": 1.5, "sfx": "whoosh_fast", "volume": 2.5}
                ]
            },
            {
                "scene_index": 4,
                "arc_phase": "Rising Action 2",
                "duration_sec": 3.0,
                "diffusion_prompt": "Crispy chicken tenders flying in a glorious slow-motion arc through the professional stainless steel restaurant kitchen. Chubby ginger cat wearing a white chef toque and headphones expertly catching each one mid-air with tongs, hyper-detailed 3d pixar animation style.",
                "negative_prompt": "static, blurry, 2D, talking, watermark, text, low quality",
                "foley_cues": [
                    {"timestamp_sec": 0.5, "sfx": "whoosh", "volume": 1.8},
                    {"timestamp_sec": 1.5, "sfx": "whoosh", "volume": 1.8},
                    {"timestamp_sec": 2.5, "sfx": "ding", "volume": 2.0}
                ]
            },
            {
                "scene_index": 5,
                "arc_phase": "Climax Payoff",
                "duration_sec": 3.0,
                "diffusion_prompt": "Chubby ginger cat wearing a white chef toque and headphones munches on a giant golden crispy fried chicken drumstick with supreme joyful swagger in the professional stainless steel restaurant kitchen. Crumbs flying, triumph smile, hyper-detailed 3d pixar animation style.",
                "negative_prompt": "static, blurry, 2D, talking, watermark, text, low quality",
                "foley_cues": [
                    {"timestamp_sec": 1.0, "sfx": "crunch", "volume": 2.8},
                    {"timestamp_sec": 2.0, "sfx": "ding_high_confirm", "volume": 2.5}
                ]
            }
        ],
        "audio_config": {"bgm_style": "bouncy_comedy_loop", "bgm_base_volume": 0.75, "target_loudnorm_lufs": -14.0},
        "music_vibe": "bouncy_comedy",
        "yt_title": "Chef Leo Cooks A Masterpiece! 🍗🐾 #shorts #viral #funnycats",
        "fb_title": "He took his cooking shift WAY too seriously! 😂🍗 Tag someone who loves fried chicken!",
        "tags": ["shorts", "funnycats", "animation", "3danimation", "food", "viral", "comedy"]
    }
]

# ---------------------------------------------------------------------------
# DEFAULT FOLEY CUE INJECTION (for Qwen/Gemini stories missing foley_cues)
# ---------------------------------------------------------------------------
# Maps action keywords in diffusion_prompt to appropriate SFX
_KEYWORD_SFX_MAP = [
    (["knife", "chop", "slice", "cut"], [
        {"timestamp_sec": 0.2, "sfx": "whoosh_fast", "volume": 2.5},
        {"timestamp_sec": 1.2, "sfx": "bonk", "volume": 2.0},
    ]),
    (["escape", "run", "roll", "dodge", "scramble"], [
        {"timestamp_sec": 0.3, "sfx": "whoosh", "volume": 2.0},
        {"timestamp_sec": 1.5, "sfx": "slide_whistle_down", "volume": 2.2},
    ]),
    (["crash", "smash", "destroy", "explode", "collide"], [
        {"timestamp_sec": 0.5, "sfx": "crash_multi", "volume": 2.8},
        {"timestamp_sec": 1.0, "sfx": "clatter_multi", "volume": 2.0},
    ]),
    (["jump", "leap", "bounce", "fly", "launch"], [
        {"timestamp_sec": 0.3, "sfx": "boing", "volume": 2.5},
        {"timestamp_sec": 1.5, "sfx": "whoosh_high", "volume": 2.0},
    ]),
    (["gasp", "shock", "scare", "surprise", "recoil"], [
        {"timestamp_sec": 0.2, "sfx": "rising_hum", "volume": 2.0},
        {"timestamp_sec": 1.0, "sfx": "ding_high_confirm", "volume": 2.5},
    ]),
    (["victory", "win", "celebrate", "triumph", "cheer", "safe"], [
        {"timestamp_sec": 0.5, "sfx": "ding", "volume": 2.5},
        {"timestamp_sec": 1.5, "sfx": "boing", "volume": 2.0},
    ]),
    (["cook", "sizzle", "fry", "grill", "bake"], [
        {"timestamp_sec": 0.3, "sfx": "sizzle", "volume": 2.2},
        {"timestamp_sec": 1.2, "sfx": "knife_chop", "volume": 2.0},
    ]),
]

# Fallback cues per act if no keyword matches
_DEFAULT_ACT_CUES = [
    [{"timestamp_sec": 0.5, "sfx": "whoosh", "volume": 2.0}, {"timestamp_sec": 1.5, "sfx": "bonk", "volume": 2.2}],
    [{"timestamp_sec": 0.3, "sfx": "whoosh_fast", "volume": 2.5}, {"timestamp_sec": 1.8, "sfx": "crash_multi", "volume": 2.0}],
    [{"timestamp_sec": 0.5, "sfx": "boing", "volume": 2.5}, {"timestamp_sec": 1.2, "sfx": "whoosh_high", "volume": 2.0}],
    [{"timestamp_sec": 0.3, "sfx": "rising_hum", "volume": 2.0}, {"timestamp_sec": 1.5, "sfx": "clatter_thump", "volume": 2.5}],
    [{"timestamp_sec": 0.5, "sfx": "ding", "volume": 2.8}, {"timestamp_sec": 1.5, "sfx": "boing", "volume": 2.0}],
]

def _inject_default_foley_cues(story_data: Dict):
    """
    Scans each scene in a story concept for missing foley_cues.
    If absent, keyword-matches the diffusion_prompt to inject
    appropriate SFX. Ensures audio director always has cues to work with.
    """
    scenes = story_data.get("scenes", [])
    for idx, sc in enumerate(scenes):
        if sc.get("foley_cues"):
            continue  # Already has cues

        prompt_text = (sc.get("diffusion_prompt", "") + " " + sc.get("visual_prompt", "")).lower()
        matched = False
        for keywords, cues in _KEYWORD_SFX_MAP:
            if any(kw in prompt_text for kw in keywords):
                sc["foley_cues"] = cues
                matched = True
                break

        if not matched:
            # Use positional default cues for this act
            sc["foley_cues"] = _DEFAULT_ACT_CUES[min(idx, len(_DEFAULT_ACT_CUES) - 1)]

    # Ensure audio_config exists
    if "audio_config" not in story_data or not story_data["audio_config"]:
        story_data["audio_config"] = {
            "bgm_style": "bouncy_comedy_loop",
            "bgm_base_volume": 0.75,
            "target_loudnorm_lufs": -14.0
        }

def sanitize_viral_title(title: Optional[str], default: str = "Funny AI Animation Short 😂 #shorts #viral") -> str:
    """
    Sanitizes YouTube and Facebook titles:
    - Purges Chinese, Japanese, Korean (CJK), Cyrillic, Arabic, and non-Latin foreign scripts.
    - Preserves standard ASCII English, numbers, punctuation, and emoji symbols.
    - If the cleaned string has fewer than 5 alphanumeric characters, falls back to default.
    - Ensures mandatory #shorts and #viral hashtags are present for YouTube titles.
    """
    if not title or not isinstance(title, str):
        return default

    # Remove CJK characters, full-width punctuation, Cyrillic, Arabic glyphs
    cjk_pattern = re.compile(
        r'[\u4e00-\u9fff\u3400-\u4dbf\u3000-\u303f\u3040-\u309f\u30a0-\u30ff\uff00-\uffef\uac00-\ud7af\u0400-\u04ff\u0600-\u06ff]'
    )
    cleaned = cjk_pattern.sub('', title).strip()
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    alpha_chars = re.findall(r'[a-zA-Z0-9]', cleaned)
    if len(alpha_chars) < 5:
        return default

    # If this looks like a YouTube title, ensure standard viral tags
    if "#" in default:
        if "#shorts" not in cleaned.lower():
            cleaned += " #shorts"
        if "#viral" not in cleaned.lower():
            cleaned += " #viral"

    return cleaned

def strip_emojis(text: str) -> str:
    """
    Removes emoji characters and symbols from text before passing to Pillow
    to avoid missing glyph square boxes [] in standard system fonts.
    """
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F680-\U0001F6FF"  # transport & map symbols
        "\U0001F1E0-\U0001F1FF"  # flags
        "\U00002702-\U000027B0"
        "\U000024C2-\U0001F251"
        "\U0001F900-\U0001F9FF"  # Supplemental Symbols
        "\U0001FA00-\U0001FA6F"
        "\U0001FA70-\U0001FAFF"
        "\U00002600-\U000026FF"  # Misc symbols
        "]+",
        flags=re.UNICODE
    )
    clean = emoji_pattern.sub("", text)
    clean = re.sub(r"[^\x20-\x7E]", "", clean)
    return re.sub(r"\s+", " ", clean).strip()

def _fit_banner_font(draw: ImageDraw.ImageDraw, text: str, max_width: int = 940, initial_size: int = 54) -> ImageFont.ImageFont:
    """Finds the best bold font and fits it within max_width."""
    size = initial_size
    candidates = [
        "C:/Windows/Fonts/impact.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"
    ]
    font_path = None
    for c in candidates:
        if os.path.exists(c):
            font_path = c
            break

    while size >= 24:
        if font_path:
            try:
                font = ImageFont.truetype(font_path, size)
            except Exception:
                try:
                    font = ImageFont.truetype("arial.ttf", size)
                except Exception:
                    font = ImageFont.load_default()
                    return font
        else:
            try:
                font = ImageFont.truetype("arial.ttf", size)
            except Exception:
                font = ImageFont.load_default()
                return font

        bbox = draw.textbbox((0, 0), text, font=font)
        if (bbox[2] - bbox[0]) <= max_width:
            return font
        size -= 4
    return font

def create_hook_banner(text: str, output_path: str, width: int = 1080, height: int = 180) -> Optional[str]:
    """
    Renders a punchy, high-contrast on-screen text hook pill banner (Pillow PNG with transparency).
    Positioned in the upper safe zone to capture silent scrollers within the first 2.8 seconds.
    """
    try:
        clean_text = strip_emojis(text).upper()
        if not clean_text:
            clean_text = "WAIT FOR IT... DON'T BLINK!"

        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        font = _fit_banner_font(draw, clean_text, max_width=width - 100, initial_size=54)

        bbox = draw.textbbox((0, 0), clean_text, font=font)
        t_w = bbox[2] - bbox[0]
        t_h = bbox[3] - bbox[1]

        pad_x, pad_y = 36, 18
        rect_w = min(width - 60, t_w + pad_x * 2)
        rect_h = t_h + pad_y * 2
        r_x0 = (width - rect_w) / 2
        r_y0 = (height - rect_h) / 2
        r_x1 = r_x0 + rect_w
        r_y1 = r_y0 + rect_h

        # Dark translucent pill with crisp white/gold border
        draw.rounded_rectangle([r_x0, r_y0, r_x1, r_y1], radius=22, fill=(0, 0, 0, 205), outline=(255, 255, 255, 220), width=3)

        tx = (width - t_w) / 2
        ty = (height - t_h) / 2 - bbox[1]

        # Bold vivid yellow text with heavy black stroke for instant readability
        draw.text((tx, ty), clean_text, font=font, fill=(255, 225, 0, 255), stroke_width=3, stroke_fill=(0, 0, 0, 255))

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        img.save(output_path)
        print(f"[STORY DIRECTOR] Hook banner generated: '{clean_text}' -> {output_path}")
        return output_path
    except Exception as e:
        print(f"[STORY DIRECTOR] Hook banner generation notice: {e}")
        return None

def create_cta_banner(text: str, output_path: str, width: int = 1080, height: int = 160) -> Optional[str]:
    """
    Renders a high-contrast on-screen CTA pill banner for the final climax/ending.
    Positioned in the lower safe zone (above mobile player controls).
    """
    try:
        clean_text = strip_emojis(text).upper()
        if not clean_text:
            clean_text = "SUBSCRIBE FOR PART 2!"

        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        font = _fit_banner_font(draw, clean_text, max_width=width - 100, initial_size=48)

        bbox = draw.textbbox((0, 0), clean_text, font=font)
        t_w = bbox[2] - bbox[0]
        t_h = bbox[3] - bbox[1]

        pad_x, pad_y = 32, 16
        rect_w = min(width - 60, t_w + pad_x * 2)
        rect_h = t_h + pad_y * 2
        r_x0 = (width - rect_w) / 2
        r_y0 = (height - rect_h) / 2
        r_x1 = r_x0 + rect_w
        r_y1 = r_y0 + rect_h

        # Dark translucent pill with vibrant red/coral outline
        draw.rounded_rectangle([r_x0, r_y0, r_x1, r_y1], radius=20, fill=(0, 0, 0, 205), outline=(255, 80, 80, 230), width=3)

        tx = (width - t_w) / 2
        ty = (height - t_h) / 2 - bbox[1]

        # Bold white text with black stroke
        draw.text((tx, ty), clean_text, font=font, fill=(255, 255, 255, 255), stroke_width=3, stroke_fill=(0, 0, 0, 255))

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        img.save(output_path)
        print(f"[STORY DIRECTOR] CTA banner generated: '{clean_text}' -> {output_path}")
        return output_path
    except Exception as e:
        print(f"[STORY DIRECTOR] CTA banner generation notice: {e}")
        return None

def generate_viral_story_concept(
    rlaf_feedback: Optional[Dict] = None,
    yt_profile: Optional[Dict] = None,
    fb_profile: Optional[Dict] = None
) -> Dict:
    """
    Autonomously brainstorms 5-act animated short stories with REAL-TIME AUTO-LEARNING & ADAPTATION:
    - Learns from real audience data (views, shares, retention, velocity).
    - Ingests emergent reinforcement rules and reward drivers from YouTube & Facebook meta-optimizers.
    - Zero thematic restrictions: complete creative freedom across any universe, character, or comedic scenario.
    - Strictly preserves protagonist lock, environment lock, 5-act conflict curve, and clean English titles.
    """
    api_keys = [
        os.environ.get("GEMINI_API_KEY"),
        os.environ.get("GEMINI_API_KEY_2"),
        os.environ.get("GEMINI_API_KEY_3"),
        os.environ.get("GEMINI_API_KEY_4"),
    ]
    api_keys = [k for k in api_keys if k and str(k).strip() != "None"]

    from app.story.trend_radar import get_global_viral_intelligence
    global_intel = get_global_viral_intelligence()
    market_context = global_intel.get("market_summary", "")

    # --- 1. DYNAMIC AUDIENCE REINFORCEMENT LEARNING DIRECTIVES ---
    feedback_parts = []
    if rlaf_feedback:
        strat = rlaf_feedback.get("strategy_mode", "EXPLORATION (Unrestricted Innovation)")
        feedback_parts.append(f"• Dynamic Learning Mode: {strat}")
        top_t = rlaf_feedback.get("top_topics", [])
        if top_t:
            feedback_parts.append(f"• Top Performing Audience Hits (Learn & reverse-engineer their pacing/stakes): {', '.join(top_t[:4])}")
        low_t = rlaf_feedback.get("low_topics", [])
        if low_t:
            feedback_parts.append(f"• Low Retention Concepts (DO NOT repeat flat/boring setups like these): {', '.join(low_t[:3])}")
        summary = rlaf_feedback.get("summary")
        if summary:
            feedback_parts.append(f"• Audience Behavior Insight: {summary}")

    # Emergent Directives & Rules from Platform Meta-Agents
    emergent_rules = []
    reward_drivers = []
    penalty_causes = []
    mandatory_hooks = []
    title_formulas = []
    fb_cta_hint = ""

    if yt_profile:
        yt_eval = yt_profile.get("agent_evaluation", {})
        emergent_rules.extend(yt_eval.get("emergent_n_rules", []))
        reward_drivers.extend(yt_eval.get("reward_drivers", []))
        penalty_causes.extend(yt_eval.get("penalty_root_causes", []))
        mandatory_hooks.extend(yt_profile.get("phase_4_vision_gate_directives", {}).get("mandatory_visual_hooks", []))
        title_formulas.extend(yt_profile.get("phase_6_copywriting_directives", {}).get("title_formulas", []))

    if fb_profile:
        fb_eval = fb_profile.get("agent_evaluation", {})
        for r in fb_eval.get("emergent_n_rules", []):
            if r not in emergent_rules:
                emergent_rules.append(r)
        for d in fb_eval.get("reward_drivers", []):
            if d not in reward_drivers:
                reward_drivers.append(d)
        fb_cta_hint = fb_profile.get("phase_6_copywriting_directives", {}).get("comment_cta", "")

    if emergent_rules:
        feedback_parts.append("• Active Emergent Rules from Audience Performance:\n  " + "\n  ".join([f"→ {r}" for r in emergent_rules[:4]]))
    if reward_drivers:
        feedback_parts.append("• Proven Reward Drivers to Double-Down On:\n  " + "\n  ".join([f"✓ {d}" for d in reward_drivers[:3]]))
    if penalty_causes:
        feedback_parts.append("• Identified Penalty Root Causes to Eliminate:\n  " + "\n  ".join([f"✗ {c}" for c in penalty_causes[:3]]))
    if mandatory_hooks:
        feedback_parts.append("• Mandatory Hook Requirements:\n  " + "\n  ".join([f"★ {h}" for h in mandatory_hooks[:2]]))

    feedback_context = "\n".join(feedback_parts) if feedback_parts else "Channel in rapid growth. Prioritize high-velocity Global Trends!"

    # Query recent video history to prevent concept repetition
    recent_videos = get_tracked_videos_for_analytics(limit=8)
    recent_titles = [v.get("title", "") for v in recent_videos if v.get("title")]
    recent_summary = "\n".join([f"- {t}" for t in recent_titles[:6]]) if recent_titles else "None"

    title_formula_hint = f"Inspiration: '{title_formulas[0]}'" if title_formulas else "Use curiosity loops + strong emojis"
    cta_hint = f"Inspiration: '{fb_cta_hint}'" if fb_cta_hint else "Ask an interactive, polarizing question"

    prompt = f"""You are an elite Pixar-grade visual storyteller and viral retention director for AI animated YouTube Shorts and Facebook Reels (producing 10M to 80M+ view hits).

Your task is to output a single, cohesive, self-contained mini-movie (14 seconds) strictly structured around the Universal Two-Wave Conflict Arc.

Never generate disjointed scenes, random clips, montage cuts, or talking-head intros. Every story must feature a clear single protagonist, continuous object/environment permanence, and 100% visual/physical comedy.

=== 1. CURRENT GLOBAL VIRAL MARKET INTELLIGENCE ===
{market_context}

=== 2. REAL-TIME AUDIENCE ADAPTATION & REINFORCEMENT LEARNING DIRECTIVES ===
{feedback_context}

=== 3. STRICT ANTI-REPETITION CONSTRAINT (CRITICAL) ===
The following characters and stories were posted recently on our channel:
{recent_summary}
DO NOT repeat any of these characters, animals, food items, or storylines!
Invent a completely FRESH protagonist, setting, and premise!

=== 4. UNRESTRICTED CREATIVE INNOVATION (ZERO THEMATIC BOUNDARIES) ===
You have COMPLETE, 100% UNRESTRICTED CREATIVE FREEDOM across all comedy themes, premises, and genres.
Do NOT limit yourself to kitchens, pets, or food. Invent ANY imaginative, hilarious, surreal, absurd, or high-concept idea:
- Wild & Exotic Animals in Bizarre Human Roles (Capybara detective, Sloth Formula-1 pit crew, Kangaroo bouncer, Pelican dentist)
- Mythical & Fantasy Slapstick (Baby dragon sneezing ice cubes, Goblin barista brewing lava, Yeti hair salon disaster)
- Living Objects & Toys (Rubber duckie escaping whirlpool, sentient toaster on trampoline, garden gnome parkour)
- Chaotic Sci-Fi & Cosmic Adventures (Astronaut squirrel fixing a moon satellite, alien grandma driving flying tractor)
- Miniature Worlds & Absurd Scale (Ant weightlifter benching a strawberry, bee air-traffic controller)
- Extreme Everyday Situations Amplified to Absurdity

THE ONLY 5 STRUCTURAL FOUNDATIONS:
1. **Protagonist Lock:** Pick ONE distinct, lovable protagonist. Same character, props, and design across ALL 5 acts.
2. **Environment Lock:** One contiguous single-location set across all 5 acts for unbroken continuity.
3. **Universal 5-Act Conflict Arc:**
   - Act 1: Hook & Instant Anomaly (0.0s - 2.5s): Zero setup. Protagonist mid-action when crisis strikes. Instant Foley within 0.5s.
   - Act 2: Conflict Spike (2.5s - 5.5s): Fix attempt fails spectacularly, triggering visual chaos.
   - Act 3: The Clever Comeback (5.5s - 8.0s): Unexpected clever pivot.
   - Act 4: Rising Action & Acceleration (8.0s - 11.0s): Counter-move snowballs into crazy chain reaction.
   - Act 5: Climax & Twist Punchline (11.0s - 14.0s): Ironic, funny, triumphant payoff for infinite looping.
4. **100% Kinetic Visual Comedy:** Rich facial expressions, dynamic physical slapstick, zero slow talking heads.
5. **Audience Safe:** Suitable for all ages on YouTube Shorts and Facebook Reels.

Style: "hyper-detailed 3d pixar animation style, cinematic lighting, expressive facial features, 8k resolution, vivid colors"
Available Foley SFX (choose ONLY from this palette): whoosh, whoosh_fast, whoosh_high, bonk, boing, ding, ding_high_confirm, crunch, sizzle, meow, bark, quack, knife_chop, mechanical_click, clatter_thump, clatter_multi, crash_multi, rising_hum, slide_whistle_down, object_drop

=== 5. OUTPUT FORMAT (STRICT JSON) ===
Return valid JSON with this exact structure:
- story_title: string in clean English
- protagonist: object with "name" and "visual_identity" (detailed physical description for prompt consistency)
- environment: detailed background set description
- niche: category string
- scenes: array of exactly 5 scenes, each with:
  - scene_index: 1-5
  - arc_phase: one of "Hook & Immediate Action", "Conflict Spike", "The Comeback", "Rising Action 2", "Climax Payoff"
  - duration_sec: 2.5, 3.0, 2.5, 3.0, 3.0 respectively
  - dialogue: 1 short, funny cartoon dialogue line spoken by the character in this scene (e.g. "Wait... what was that?!")
  - diffusion_prompt: "Cinematic 3D animation, [visual_identity] in [environment], [specific action], hyper-detailed 3d pixar animation style, cinematic lighting, 8k"
  - negative_prompt: "static, blurry, 2D, watermark, text, low quality"
  - foley_cues: array of 2-3 cues, each with timestamp_sec (relative to scene start), sfx (from palette), volume (1.5-2.8)
- audio_config: object with bgm_style, bgm_base_volume (0.75), target_loudnorm_lufs (-14.0)
- music_vibe: "bouncy_comedy"
- yt_title: viral YouTube title strictly in English with emojis and #shorts #viral ({title_formula_hint})
- fb_title: Facebook engagement caption under 120 chars strictly in English ({cta_hint})
- hook_text: punchy 3-5 word on-screen text hook in ALL CAPS (e.g. "DON'T BLINK!", "WAIT TILL THE END!")
- cta_text: punchy 3-5 word on-screen call to action in ALL CAPS (e.g. "SUBSCRIBE FOR PART 2! 🔔")
- tags: array of relevant hashtag strings
"""

    for k in api_keys:
        try:
            client = genai.Client(api_key=k)
            response = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "response_schema": ViralStoryScript
                }
            )
            data = json.loads(response.text)
            # Strict title and hook sanitization
            data["yt_title"] = sanitize_viral_title(data.get("yt_title"), default=f"{data.get('story_title', data.get('title', 'Funny Moment'))} 😂 #shorts #viral")
            data["fb_title"] = sanitize_viral_title(data.get("fb_title"), default="Wait till you see what happens! 😂 Tag a friend!")
            if not data.get("hook_text"):
                t_clean = strip_emojis(re.sub(r'#\w+', '', data["yt_title"]).strip())
                data["hook_text"] = (t_clean[:32] if t_clean else "WAIT FOR IT... DON'T BLINK!").upper()
            if not data.get("cta_text"):
                data["cta_text"] = "SUBSCRIBE FOR PART 2! 🔔"
            print(f"[STORY DIRECTOR] Conceived new adaptive 5-act story via Gemini 3.6 Flash: '{data.get('story_title', data.get('title'))}' in niche '{data.get('niche')}'")
            return data
        except Exception as e:
            print(f"[STORY DIRECTOR] Gemini notice: {e}")
            time.sleep(1.0)

    # Fallback to Hugging Face Qwen-72B Autonomous Brainstorming
    hf_token = os.environ.get("HF_TOKEN")
    if hf_token:
        try:
            from huggingface_hub import InferenceClient
            hf_client = InferenceClient(api_key=hf_token)
            hf_prompt = prompt + "\nOutput strictly valid JSON. No markdown formatting, no code fences. Output strictly in English."
            res = hf_client.chat.completions.create(
                messages=[{"role": "user", "content": hf_prompt}],
                model="Qwen/Qwen2.5-72B-Instruct",
                max_tokens=2500,
                temperature=0.85
            )
            raw = res.choices[0].message.content.strip()
            raw = re.sub(r"^```json\s*", "", raw)
            raw = re.sub(r"^```\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
            data = json.loads(raw.strip())
            # Normalize title field
            if "title" not in data and "story_title" in data:
                data["title"] = data["story_title"]
            elif "story_title" not in data and "title" in data:
                data["story_title"] = data["title"]
            _inject_default_foley_cues(data)
            # Strict title and hook sanitization
            data["yt_title"] = sanitize_viral_title(data.get("yt_title"), default=f"{data.get('story_title', data.get('title', 'Funny Moment'))} 😂 #shorts #viral")
            data["fb_title"] = sanitize_viral_title(data.get("fb_title"), default="Wait till you see what happens! 😂 Tag a friend!")
            if not data.get("hook_text"):
                t_clean = strip_emojis(re.sub(r'#\w+', '', data["yt_title"]).strip())
                data["hook_text"] = (t_clean[:32] if t_clean else "WAIT FOR IT... DON'T BLINK!").upper()
            if not data.get("cta_text"):
                data["cta_text"] = "SUBSCRIBE FOR PART 2! 🔔"
            print(f"[STORY DIRECTOR] Conceived new adaptive 5-act story via Qwen-72B: '{data.get('story_title', data.get('title'))}' in niche '{data.get('niche')}'")
            return data
        except Exception as e:
            print(f"[STORY DIRECTOR] Hugging Face Qwen-72B notice: {e}")

    # Fallback to Curated Concepts (Filtered to avoid recent repetitions)
    import random
    recent_keywords = [t.lower() for t in recent_titles[:6]]
    candidate_fallbacks = []
    for c in FALLBACK_CONCEPTS:
        c_name = (c.get("character_name") or c.get("title", "")).lower()
        first_word = c_name.split()[0] if c_name else ""
        if not any(first_word in r for r in recent_keywords if first_word and len(first_word) > 3):
            candidate_fallbacks.append(c)

    chosen_pool = candidate_fallbacks if candidate_fallbacks else FALLBACK_CONCEPTS
    chosen = random.choice(chosen_pool).copy()
    chosen["yt_title"] = sanitize_viral_title(chosen.get("yt_title"))
    chosen["fb_title"] = sanitize_viral_title(chosen.get("fb_title"))
    if not chosen.get("hook_text"):
        t_clean = strip_emojis(re.sub(r'#\w+', '', chosen["yt_title"]).strip())
        chosen["hook_text"] = (t_clean[:32] if t_clean else "WAIT FOR IT... DON'T BLINK!").upper()
    if not chosen.get("cta_text"):
        chosen["cta_text"] = "SUBSCRIBE FOR PART 2! 🔔"
    print(f"[STORY DIRECTOR] Using curated viral concept (anti-repetition filtered): '{chosen['title']}'")
    return chosen

def render_story_video(story: Dict, output_path: str) -> Optional[str]:
    """
    Renders a 5-act story into a complete 1080x1920 Short using the
    Image-to-Video (I2V) protagonist-lock pipeline:

    1. Generates a FLUX.1-schnell hero keyframe (576x1024, 9:16) from protagonist
       visual_identity + environment — locking art style across all scenes.
    2. For each scene, uses LTX Video image-to-video mode with the hero keyframe
       as t=0 reference frame + scene action prompt.
    3. Validates each scene with dual empty/frozen detection.
    4. Falls back through: I2V → text-to-video → Ken Burns pan-zoom → motion assets.
    5. Concatenates, mixes dynamic Foley audio, and encodes final MP4.
    """
    os.makedirs("data/temp", exist_ok=True)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    scenes = story.get("scenes", [])
    if len(scenes) < 3:
        print("[STORY DIRECTOR] Error: Story must have at least 3 scenes.")
        return None

    # --- STEP 1: Generate Hero Reference Keyframe ---
    protagonist = story.get("protagonist", {})
    if isinstance(protagonist, dict):
        visual_identity = protagonist.get("visual_identity", story.get("character_name", "cute cartoon animal character"))
    else:
        visual_identity = str(protagonist) if protagonist else story.get("character_name", "cute cartoon animal character")

    environment = story.get("environment", "colorful cartoon kitchen")
    art_style = "Pixar 3D animation style, vibrant colors, soft lighting, sharp focus, cinematic"

    # --- STEP 0: TIER 0 — GEMINI OMNI NATIVE 3D VIDEO (Gemini Pro Studio) ---
    # Produces full 9:16 vertical Pixar 3D animation with native character speech and sound effects
    try:
        dialogues = [sc.get("dialogue") or sc.get("voice_line") for sc in scenes if sc.get("dialogue") or sc.get("voice_line")]
        first_voice = dialogues[0] if dialogues else "The character speaks excitedly in a cute cartoon voice"

        action_parts = []
        for sc in scenes[:3]:
            dp = sc.get("diffusion_prompt", "").replace("hyper-detailed 3d pixar animation style.", "").replace("Pixar 3D style, sharp focus, 8k", "").strip()
            if dp:
                action_parts.append(dp[:100])
        action_str = ". ".join(action_parts)

        omni_prompt = (
            f"Cinematic Pixar 3D animation, vertical 9:16 portrait. "
            f"{visual_identity} in {environment}. {action_str}. "
            f"The character speaks excitedly in a cute cartoon voice: '{first_voice}'. "
            f"Vibrant colors, cinematic lighting, sharp focus, no watermark, no text"
        )

        omni_temp_raw = os.path.join("data", "temp", "omni_episode_raw.mp4")
        omni_video = generate_gemini_omni_video(omni_prompt, omni_temp_raw, aspect_ratio="9:16", timeout_sec=240)
        if omni_video and os.path.exists(omni_video) and os.path.getsize(omni_video) > 100_000:
            print("[STORY DIRECTOR] Successfully rendered complete episode via Gemini Omni Studio! Removing watermark & burning on-screen hooks...")
            hook_text = story.get("hook_text") or "WAIT FOR IT... DON'T BLINK!"
            cta_text = story.get("cta_text") or "SUBSCRIBE FOR PART 2! 🔔"
            hook_banner_path = os.path.join("data", "temp", "omni_hook_banner.png")
            cta_banner_path = os.path.join("data", "temp", "omni_cta_banner.png")
            create_hook_banner(hook_text, hook_banner_path)
            create_cta_banner(cta_text, cta_banner_path)

            filter_complex = (
                "[0:v]delogo=x=570:y=1130:w=70:h=70,scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920[v_base];"
                "[v_base][1:v]overlay=0:280:enable='between(t,0,2.8)'[v_hook];"
                "[v_hook][2:v]overlay=0:1400:enable='gte(t,11.5)'[v_out]"
            )
            subprocess.run([
                "ffmpeg", "-y",
                "-i", omni_video,
                "-i", hook_banner_path,
                "-i", cta_banner_path,
                "-filter_complex", filter_complex,
                "-map", "[v_out]", "-map", "0:a?",
                "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "256k", output_path
            ], capture_output=True, check=True)
            if os.path.exists(output_path) and os.path.getsize(output_path) > 100_000:
                return output_path
    except Exception as e:
        print(f"[STORY DIRECTOR] Gemini Omni tier notice: {e}. Proceeding to multi-scene pipeline...")

    # --- STEP 1: Generate Hero Reference Keyframe ---
    hero_prompt = (
        f"{visual_identity}, {environment}, full body character pose, centered composition, "
        f"{art_style}, 9:16 vertical portrait, detailed character design sheet"
    )

    hero_keyframe_path = os.path.join("data", "temp", "hero_keyframe.png")
    hero_image = generate_hero_keyframe(
        prompt=hero_prompt,
        output_path=hero_keyframe_path,
        width=576,
        height=1024
    )

    use_i2v = hero_image is not None and os.path.exists(hero_keyframe_path)
    if use_i2v:
        print(f"[STORY DIRECTOR] Hero keyframe generated. Using I2V pipeline for protagonist lock.")
    else:
        print(f"[STORY DIRECTOR] Hero keyframe failed. Falling back to text-to-video pipeline.")

    # --- High-displacement camera/physics verbs to force real motion (not idle loops) ---
    # Scene 1 gets no prefix (establishing shot). Scenes 2-5 get aggressive velocity cues
    # that push the I2V latent space away from the static reference anchor.
    DISPLACEMENT_PREFIXES = [
        "",  # Act 1: establishing shot from hero pose
        "fast zoom-in, extreme motion, character rapidly dodges sideways, ",
        "low angle dynamic shot, character leaps off the surface into the air, ",
        "extreme motion, character rolls rapidly across the surface, camera tracking fast, ",
        "cinematic slow-motion, character slides and lands in a new position, triumphant pose, ",
    ]

    rendered_scene_vids = []
    used_motion_fallback = False

    for idx, sc in enumerate(scenes):
        num = sc.get("scene_index", sc.get("scene_number", idx + 1))
        p = sc.get("diffusion_prompt", sc.get("visual_prompt", ""))
        neg_p = sc.get("negative_prompt", None)
        act = sc.get("arc_phase", sc.get("act_name", f"Act {num}"))
        sc_dur = float(sc.get("duration_sec", 2.8 if idx < len(scenes) - 1 else 3.0))
        sc_out = os.path.join("data", "temp", f"story_scene_{num}.mp4")

        # Build high-displacement scene prompt
        motion_prefix = DISPLACEMENT_PREFIXES[min(idx, len(DISPLACEMENT_PREFIXES) - 1)]
        scene_prompt = f"{motion_prefix}{p}, {art_style}, consistent character appearance"

        print(f"[STORY DIRECTOR] Generating Scene {num}/{len(scenes)} ({act}): {p[:80]}...")

        vid_path = None
        scene_valid = False

        # --- TIER 1: Image-to-Video with per-scene reframed hero (protagonist lock) ---
        if use_i2v:
            # Reframe hero image per act to vary composition (prevent dead-center staging)
            reframed_path = os.path.join("data", "temp", f"hero_act_{num}.png")
            scene_hero = reframe_hero_for_scene(hero_keyframe_path, idx, reframed_path)

            for attempt in range(2):
                vid_path = generate_ai_video_from_image(
                    image_path=scene_hero,
                    scene_prompt=scene_prompt,
                    output_path=sc_out,
                    duration=int(math.ceil(sc_dur)),
                    negative_prompt=neg_p
                )
                if vid_path and os.path.exists(vid_path):
                    if not is_video_empty(vid_path):
                        scene_valid = True
                        break
                    else:
                        print(f"[STORY DIRECTOR] Scene {num} I2V produced blank/frozen frame (attempt {attempt+1}). Retrying...")
                else:
                    break  # I2V completely failed, move to next tier

        # --- TIER 2: Text-to-Video fallback ---
        if not scene_valid:
            print(f"[STORY DIRECTOR] Scene {num}: I2V failed. Trying text-to-video fallback...")
            vid_path = generate_ai_video_from_prompt(p, sc_out, duration=int(math.ceil(sc_dur)), negative_prompt=neg_p)
            if vid_path and os.path.exists(vid_path) and not is_video_empty(vid_path):
                scene_valid = True

        # --- TIER 3: Ken Burns pan-zoom on hero keyframe ---
        if not scene_valid and use_i2v:
            print(f"[STORY DIRECTOR] Scene {num}: T2V failed. Using Ken Burns on hero keyframe...")
            vid_path = generate_pan_zoom_fallback(hero_keyframe_path, sc_out, duration=sc_dur)
            if vid_path and os.path.exists(vid_path):
                scene_valid = True

        # --- TIER 4: Pre-rendered motion fallback assets ---
        if not scene_valid:
            print(f"[STORY DIRECTOR] Scene {num}: All AI tiers failed. Using pre-rendered motion fallback...")
            fallback_files = ["scene1.mp4", "scene2.mp4", "scene3.mp4"]
            fb_idx = idx % len(fallback_files)
            fb_path = os.path.join("data", "assets", "motion_fallback", fallback_files[fb_idx])
            if fb_path and os.path.exists(fb_path):
                shutil.copy2(fb_path, sc_out)
                vid_path = sc_out
                used_motion_fallback = True
                scene_valid = True
            else:
                print(f"[STORY DIRECTOR] No fallback asset available for Scene {num}. Skipping.")
                return None

        # Format scene to 1080x1920 30fps with exact duration
        sc_fmt = os.path.join("data", "temp", f"story_scene_{num}_fmt.mp4")
        subprocess.run([
            "ffmpeg", "-y", "-i", vid_path,
            "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
            "-t", str(sc_dur), "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", sc_fmt
        ], capture_output=True, check=True)
        rendered_scene_vids.append(sc_fmt)

    # If fallback pack was used, align story metadata and audio timeline with the footage
    if used_motion_fallback:
        print("[STORY DIRECTOR] Fallback motion used. Synchronizing story metadata & audio cues with Golden Egg footage...")
        golden_egg = FALLBACK_CONCEPTS[0]
        story.update({
            "title": golden_egg["title"],
            "character_name": golden_egg["character_name"],
            "niche": golden_egg["niche"],
            "protagonist": golden_egg["protagonist"],
            "environment": golden_egg["environment"],
            "music_vibe": golden_egg["music_vibe"],
            "scenes": golden_egg["scenes"],
            "audio_config": golden_egg["audio_config"],
            "yt_title": golden_egg["yt_title"],
            "fb_title": golden_egg["fb_title"],
            "tags": golden_egg["tags"]
        })
        scenes = story.get("scenes", [])

    # Concatenate video scenes
    concat_txt = "data/temp/director_concat.txt"
    with open(concat_txt, "w") as f:
        for v in rendered_scene_vids:
            f.write(f"file '{os.path.abspath(v).replace(chr(92), '/')}'\n")

    visual_only = "data/temp/director_visual.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_txt,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", visual_only
    ], capture_output=True, check=True)

    # Dynamic Foley & Music Generation
    master_audio = os.path.join("data", "temp", "story_master_audio.wav")
    total_dur = sum(float(sc.get("duration_sec", 2.8 if idx < len(scenes) - 1 else 3.0)) for idx, sc in enumerate(scenes))
    build_scene_audio_timeline(story, total_duration=total_dur, output_wav=master_audio)

    # Prepare on-screen hook and CTA banners
    hook_text = story.get("hook_text")
    if not hook_text:
        t_clean = strip_emojis(re.sub(r'#\w+', '', story.get("yt_title", "")).strip())
        hook_text = (t_clean[:32] if t_clean else "WAIT FOR IT... DON'T BLINK!").upper()
    cta_text = story.get("cta_text") or "SUBSCRIBE FOR PART 2! 🔔"

    hook_banner_path = os.path.join("data", "temp", "story_hook_banner.png")
    cta_banner_path = os.path.join("data", "temp", "story_cta_banner.png")
    create_hook_banner(hook_text, hook_banner_path)
    create_cta_banner(cta_text, cta_banner_path)

    cta_start_t = max(0.0, total_dur - 2.8)
    filter_complex = (
        "[0:v][1:v]overlay=0:280:enable='between(t,0,2.8)'[v_hook];"
        f"[v_hook][2:v]overlay=0:1400:enable='gte(t,{cta_start_t:.1f})'[vout]"
    )

    cmd_mux = [
        "ffmpeg", "-y",
        "-i", visual_only,
        "-i", hook_banner_path,
        "-i", cta_banner_path,
        "-i", master_audio,
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "3:a",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "256k",
        "-shortest",
        output_path
    ]
    subprocess.run(cmd_mux, capture_output=True, check=True)

    if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
        print(f"[STORY DIRECTOR] Successfully rendered {len(rendered_scene_vids)}-scene story with on-screen hook & CTA overlays: {output_path}")
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
    yt_title = sanitize_viral_title(story.get("yt_title"), default="Funny AI Animation Short 😂 #shorts #viral")
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
    fb_title = sanitize_viral_title(story.get("fb_title"), default="Wait till you see what happens! 😂 Tag a friend!")
    tags = story.get("tags", ["funny", "animation", "viral", "comedy"])
    
    clean_tags = [f"#{re.sub(r'[^a-zA-Z0-9]', '', t.lower())}" for t in tags if t.lower() not in ["shorts", "ytshorts"]]
    fb_tags = " ".join(clean_tags[:4])
    
    desc = f"""{fb_title}

Rate this 1-10 in the comments! 😂👇 Tag a friend who needs a laugh!

{fb_tags} #reels #funnyreels #viralreels #reelsfb #comedy"""
    return desc.strip()
