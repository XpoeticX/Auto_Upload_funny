import os
import json
import time
import subprocess
import shutil
import re
import math
from typing import Dict, List, Optional
from pydantic import BaseModel, Field
from google import genai
from app.video.ai_diffusion import generate_ai_video_from_prompt, animate_image_to_video
from app.analytics.engine import get_rlaf_ai_feedback
from app.story.audio_director import build_scene_audio_timeline

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
    negative_prompt: str = "static, blurry, 2D, talking, watermark, text, low quality"
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

def generate_viral_story_concept(rlaf_feedback: Optional[Dict] = None) -> Dict:
    """
    Uses Gemini / Qwen-72B to autonomously brainstorm ultra-viral surrealist AI animated short stories
    following the strict 5-Act Universal Two-Wave Conflict Arc with protagonist/environment lock.
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

    prompt = f"""You are an expert Pixar-grade visual storyteller and viral retention director for AI animated YouTube Shorts and Facebook Reels (producing 10M to 80M+ view hits).

Your task is to output a single, cohesive, self-contained mini-movie (14 seconds) strictly structured around the Universal Two-Wave Conflict Arc.

Never generate disjointed scenes, random clips, montage cuts, or talking-head intros. Every story must feature a clear single protagonist, continuous object/environment permanence, and 100% visual/physical comedy (zero spoken dialogue).

=== 1. CURRENT GLOBAL VIRAL MARKET INTELLIGENCE ===
{market_context}

=== 2. CHANNEL AUDIENCE DATA ===
{feedback_context or "Channel is in growth phase. Prioritize the high-velocity Global Trends above!"}

=== 3. CORE RULES OF CONTINUITY & ARC DYNAMICS ===

1. **Protagonist Lock:** Pick ONE distinct character (e.g., Hamster Chef, Baby Dino, Robot Barista). Visual attributes, clothing, and props must persist across ALL 5 acts.
2. **Environment Lock:** The entire short takes place in ONE contiguous set (e.g., kitchen counter, workshop, living room rug).
3. **The Conflict Arc Curve (Strict 5-Act Scene Breakdown):**
   - Act 1: Hook & Immediate Action (0.0s - 2.5s): Start in media res. Protagonist mid-task when instant anomaly triggers. Zero setup. Dynamic Foley hits within 0.5s.
   - Act 2: Conflict Spike (2.5s - 5.5s): Anomaly escalates into severe crisis. Initial fix attempt FAILS causing maximum visual chaos. Escalating SFX.
   - Act 3: The Comeback (5.5s - 8.0s): Low point turns into pivot. Protagonist takes unexpected clever counter-action. Brief tension drop with precise tactile Foley.
   - Act 4: Rising Action 2 (8.0s - 11.0s): Rapid acceleration. Counter-move triggers overwhelming chain reaction. Rapid layered SFX crescendo.
   - Act 5: Climax & Twist Payoff (11.0s - 14.0s): Chaos resolves in unexpected triumphant or ironic punchline. Final frame holds comedic reaction for looping. Resolution chime/ding.

4. Model after highest-velocity global formats:
   - Surreal Anthropomorphic (Muscular Shark chef, Crocodile dentist)
   - Adorable Baby & Animal Companions (Baby riding mini cow, Baby on pelican)
   - Living Cartoon Food & Objects with Pixar eyes (Tomato escaping knife)
   - "Ulti Duniya" / Absurd Role Reversal (Cockroach family dinner)
   - Animal Slapstick / Food ASMR (Cat chef, Hamster bakery)

5. Style: "hyper-detailed 3d pixar animation style, cinematic lighting, expressive facial features, 8k resolution, vivid colors"

6. Available Foley SFX (choose ONLY from this palette): whoosh, whoosh_fast, whoosh_high, bonk, boing, ding, ding_high_confirm, crunch, sizzle, meow, bark, quack, knife_chop, mechanical_click, clatter_thump, clatter_multi, crash_multi, rising_hum, slide_whistle_down, object_drop

=== 4. OUTPUT FORMAT (STRICT JSON) ===
Return valid JSON with this exact structure:
- story_title: string
- protagonist: object with "name" and "visual_identity" (detailed physical description for prompt consistency)
- environment: detailed background set description
- niche: category string
- scenes: array of exactly 5 scenes, each with:
  - scene_index: 1-5
  - arc_phase: one of "Hook & Immediate Action", "Conflict Spike", "The Comeback", "Rising Action 2", "Climax Payoff"
  - duration_sec: 2.5, 3.0, 2.5, 3.0, 3.0 respectively
  - diffusion_prompt: "Cinematic 3D animation, [visual_identity] in [environment], [specific action], hyper-detailed 3d pixar animation style, cinematic lighting, 8k"
  - negative_prompt: "static, blurry, 2D, talking, watermark, text, low quality"
  - foley_cues: array of 2-3 cues, each with timestamp_sec (relative to scene start), sfx (from palette), volume (1.5-2.8)
- audio_config: object with bgm_style, bgm_base_volume (0.75), target_loudnorm_lufs (-14.0)
- music_vibe: "bouncy_comedy"
- yt_title: viral YouTube title with emojis and #shorts #viral
- fb_title: Facebook engagement caption under 120 chars
- tags: array of relevant hashtag strings
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
            print(f"[STORY DIRECTOR] Conceived new 5-act story via Gemini: '{data.get('story_title', data.get('title'))}' in niche '{data.get('niche')}'")
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
            hf_prompt = prompt + "\nOutput strictly valid JSON. No markdown formatting, no code fences. Just raw JSON."
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
            print(f"[STORY DIRECTOR] Conceived new 5-act story via Qwen-72B: '{data.get('story_title', data.get('title'))}' in niche '{data.get('niche')}'")
            return data
        except Exception as e:
            print(f"[STORY DIRECTOR] Hugging Face Qwen-72B notice: {e}")

    import random
    chosen = random.choice(FALLBACK_CONCEPTS)
    print(f"[STORY DIRECTOR] Using curated viral concept: '{chosen['title']}'")
    return chosen

def render_story_video(story: Dict, output_path: str) -> Optional[str]:
    """
    Renders a 5-act story into a complete 1080x1920 Short:
    - Generates 5 real AI video diffusion scenes with negative_prompt quality control.
    - Synchronizes per-scene Foley sound effects at millisecond precision.
    - Adds ducked comedy background music with EBU R128 loudnorm.
    - Concatenates and encodes final high-bitrate MP4.
    """
    os.makedirs("data/temp", exist_ok=True)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    scenes = story.get("scenes", [])
    if len(scenes) < 3:
        print("[STORY DIRECTOR] Error: Story must have at least 3 scenes.")
        return None

    rendered_scene_vids = []
    used_motion_fallback = False

    for idx, sc in enumerate(scenes):
        num = sc.get("scene_index", sc.get("scene_number", idx + 1))
        p = sc.get("diffusion_prompt", sc.get("visual_prompt", ""))
        neg_p = sc.get("negative_prompt", None)
        act = sc.get("arc_phase", sc.get("act_name", f"Act {num}"))
        sc_dur = float(sc.get("duration_sec", 2.8 if idx < len(scenes) - 1 else 3.0))
        sc_out = os.path.join("data", "temp", f"story_scene_{num}.mp4")

        print(f"[STORY DIRECTOR] Generating Scene {num}/{len(scenes)} ({act}): {p[:80]}...")
        vid_path = generate_ai_video_from_prompt(p, sc_out, duration=int(math.ceil(sc_dur)), negative_prompt=neg_p)
        if not vid_path or not os.path.exists(vid_path):
            print(f"[STORY DIRECTOR] Warning: Scene {num} generation issue. Using motion fallback...")
            # Fallback to permanent neural motion assets (3 clips wrap for 5 scenes: 1→2→3→2→3)
            fallback_files = ["scene1.mp4", "scene2.mp4", "scene3.mp4"]
            fb_idx = idx % len(fallback_files)
            fb_path = os.path.join("data", "assets", "motion_fallback", fallback_files[fb_idx])
            if fb_path and os.path.exists(fb_path):
                print(f"[STORY DIRECTOR] Using motion fallback asset for Scene {num}: {fb_path}")
                shutil.copy2(fb_path, sc_out)
                vid_path = sc_out
                used_motion_fallback = True
            else:
                print(f"[STORY DIRECTOR] No fallback asset available for Scene {num}. Skipping.")
                return None

        # Format scene to 1080x1920 30fps with exact duration
        sc_fmt = os.path.join("data", "temp", f"story_scene_{num}_fmt.mp4")
        subprocess.run([
            "ffmpeg", "-y", "-i", vid_path,
            "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
            "-t", str(sc_dur), "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", sc_fmt
        ], check=True)
        rendered_scene_vids.append(sc_fmt)

    # If fallback pack was used, align story metadata and audio timeline 200% with the footage
    if used_motion_fallback:
        print("[STORY DIRECTOR] Fallback motion used. Synchronizing story metadata & audio cues 100% with Golden Egg footage...")
        # Use the first FALLBACK_CONCEPT (Golden Egg) which has proper 5-act foley_cues
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
        # Recalculate scenes reference after update
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
    ], check=True)

    # Dynamic Foley & Music Generation tailored 200% to this specific story and motion
    master_audio = os.path.join("data", "temp", "story_master_audio.wav")
    total_dur = sum(float(sc.get("duration_sec", 2.8 if idx < len(scenes) - 1 else 3.0)) for idx, sc in enumerate(scenes))
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
        print(f"[STORY DIRECTOR] Successfully rendered {len(rendered_scene_vids)}-scene story: {output_path}")
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
