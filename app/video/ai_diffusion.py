import os
import random
import math
import subprocess
import tempfile
import shutil
import numpy as np
from PIL import Image
from gradio_client import Client, handle_file

from dotenv import load_dotenv
load_dotenv()

SPACE_NAME = "Lightricks/ltx-video-distilled"
FLUX_SPACE = "black-forest-labs/FLUX.1-schnell"

# --- Token Pool: Sequential rotation with fallback ---
def get_hf_token_pool() -> list:
    raw = [
        os.getenv("HF_TOKEN"),
        os.getenv("HF_TOKEN_2"),
        os.getenv("HF_TOKEN_3"),
        os.getenv("HUGGINGFACE_TOKEN"),
    ]
    pool = [t.strip() for t in raw if t and t.strip() and t.strip() != "None"]
    return pool or [None]


# ---------------------------------------------------------------------------
# 1. HERO KEYFRAME GENERATION (FLUX.1-schnell, 576x1024 portrait, 9:16)
# ---------------------------------------------------------------------------
def generate_hero_keyframe(
    prompt: str,
    output_path: str = "data/temp/hero_keyframe.png",
    width: int = 576,
    height: int = 1024
) -> str:
    """
    Generates a single 9:16 protagonist reference image using FLUX.1-schnell.
    Dimensions kept divisible by 16 for diffusion model compatibility.
    This hero image locks the art style, character design, and color palette
    across all 5 acts of the story.
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    # Tier 0: Gemini Pro browser generation (Pixar 3D quality, 100% free via user's Pro plan)
    try:
        from app.video.gemini_browser import generate_image_via_browser
        browser_img = generate_image_via_browser(prompt, output_path, timeout_sec=90)
        if browser_img and os.path.exists(browser_img) and os.path.getsize(browser_img) > 10000:
            print(f"[HERO KEYFRAME] Successfully generated protagonist reference via Gemini Pro: {output_path}")
            return output_path
        else:
            print("[HERO KEYFRAME] Gemini Pro browser returned no image. Falling back to FLUX.1...")
    except Exception as e:
        print(f"[HERO KEYFRAME] Gemini Pro browser notice: {e}. Falling back to FLUX.1...")

    tokens = get_hf_token_pool()

    for idx, token in enumerate(tokens):
        try:
            client = Client(FLUX_SPACE, token=token) if token else Client(FLUX_SPACE)
            result = client.predict(
                prompt=prompt,
                seed=random.randint(0, 2**31 - 1),
                randomize_seed=True,
                width=width,
                height=height,
                num_inference_steps=4,
                api_name="/infer"
            )
            # result[0] is the generated image file path
            generated_path = result[0] if isinstance(result[0], str) else result[0].get("path", result[0])
            if generated_path and os.path.exists(generated_path):
                with Image.open(generated_path) as img:
                    img.save(output_path, format="PNG")
                print(f"[HERO KEYFRAME] Generated protagonist reference: {output_path} ({width}x{height})")
                return output_path
        except Exception as e:
            err_str = str(e)
            print(f"[HERO KEYFRAME] Notice with token #{idx+1}: {err_str[:120]}")
            if "ZeroGPU quota" in err_str and idx < len(tokens) - 1:
                print(f"[HERO KEYFRAME] Token #{idx+1} hit cooldown. Rotating to Token #{idx+2}...")
                continue
    print("[HERO KEYFRAME] All tokens exhausted. Hero keyframe generation failed.")
    return None


# ---------------------------------------------------------------------------
# 2. IMAGE-TO-VIDEO: Animate hero keyframe into a scene (protagonist lock)
# ---------------------------------------------------------------------------
def generate_ai_video_from_image(
    image_path: str,
    scene_prompt: str,
    output_path: str,
    duration: int = 3,
    negative_prompt: str = None
) -> str:
    """
    Converts a hero keyframe image + text prompt into an animated scene using
    LTX Video in image-to-video mode. The hero image serves as t=0 (initial frame),
    guaranteeing the same character, style, and color palette across all scenes.
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    tokens = get_hf_token_pool()
    neg = negative_prompt or "blurry, distorted, low quality, static, frozen, deformed hands, watermark, text"

    for idx, token in enumerate(tokens):
        try:
            client = Client(SPACE_NAME, token=token) if token else Client(SPACE_NAME)
            result = client.predict(
                prompt=scene_prompt,
                negative_prompt=neg,
                input_image_filepath=handle_file(image_path),
                input_video_filepath=None,
                height_ui=704,
                width_ui=512,
                mode="image-to-video",
                duration_ui=duration,
                ui_frames_to_use=9,
                seed_ui=random.randint(0, 2**31 - 1),
                randomize_seed=True,
                ui_guidance_scale=1,
                improve_texture_flag=True,
                api_name="/image_to_video"
            )
            temp_vid = result[0].get("video") if isinstance(result[0], dict) else result[0]
            if temp_vid and os.path.exists(temp_vid):
                # Transcode to standard H.264 to avoid container incompatibilities
                cmd = [
                    "ffmpeg", "-y", "-i", temp_vid,
                    "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-crf", "18", output_path
                ]
                subprocess.run(cmd, capture_output=True, check=True)
                print(f"[AI I2V] Scene rendered via image-to-video: {output_path}")
                return output_path
        except Exception as e:
            err_str = str(e)
            print(f"[AI I2V] Notice with token #{idx+1}: {err_str[:120]}")
            if "ZeroGPU quota" in err_str and idx < len(tokens) - 1:
                print(f"[AI I2V] Token #{idx+1} hit cooldown. Rotating to Token #{idx+2}...")
                continue
    return None


# ---------------------------------------------------------------------------
# 3. TEXT-TO-VIDEO FALLBACK (original, kept as secondary fallback)
# ---------------------------------------------------------------------------
def generate_ai_video_from_prompt(prompt: str, output_path: str, duration: int = 3, negative_prompt: str = None) -> str:
    """
    Generates a 100% neural AI video clip from text using open cloud video diffusion ( cost).
    Automatically rotates through available HF_TOKENs if one encounters a temporary ZeroGPU quota cooldown.
    Used as fallback when image-to-video fails.
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    tokens = get_hf_token_pool()
    neg = negative_prompt or "worst quality, inconsistent motion, blurry, jittery, distorted, static, 2D, talking, watermark, text, low quality"

    for idx, token in enumerate(tokens):
        try:
            client = Client(SPACE_NAME, token=token) if token else Client(SPACE_NAME)
            result = client.predict(
                prompt=prompt,
                negative_prompt=neg,
                input_image_filepath=None,
                input_video_filepath=None,
                height_ui=704,
                width_ui=512,
                mode="text-to-video",
                duration_ui=duration,
                ui_frames_to_use=9,
                seed_ui=42,
                randomize_seed=True,
                ui_guidance_scale=1,
                improve_texture_flag=True,
                api_name="/text_to_video"
            )
            temp_vid = result[0].get("video")
            if temp_vid and os.path.exists(temp_vid):
                shutil.copy2(temp_vid, output_path)
                return output_path
        except Exception as e:
            err_str = str(e)
            print(f"[AI DIFFUSION] Notice with token #{idx+1}: {err_str[:120]}")
            if "ZeroGPU quota" in err_str and idx < len(tokens) - 1:
                print(f"[AI DIFFUSION] Token #{idx+1} hit cooldown. Rotating to Token #{idx+2}...")
                continue
    return None


# ---------------------------------------------------------------------------
# 4. EMPTY / FROZEN FRAME DETECTION (dual-check)
# ---------------------------------------------------------------------------
def is_video_empty(
    video_path: str,
    variance_threshold: float = 8.0,
    motion_diff_threshold: float = 2.5
) -> bool:
    """
    Detects two failure modes:
    1. Blank / solid color scenes (pixel standard deviation < variance_threshold).
    2. Frozen scenes / dead air (mean frame-to-frame delta between 25% and 75% marks
       < motion_diff_threshold) -- catches textured backgrounds with zero character motion.
    """
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            f1_path = os.path.join(tmp_dir, "frame_25pct.png")
            f2_path = os.path.join(tmp_dir, "frame_75pct.png")

            # Extract frames at 25% and 75% of duration
            for out, pos in [(f1_path, "0.25"), (f2_path, "0.75")]:
                cmd = [
                    "ffmpeg", "-y", "-ss", pos, "-i", video_path,
                    "-vframes", "1", "-q:v", "2", out
                ]
                subprocess.run(cmd, capture_output=True)

            if not os.path.exists(f1_path) or not os.path.exists(f2_path):
                print("[EMPTY CHECK] Could not extract frames. Treating as empty.")
                return True

            img1 = np.array(Image.open(f1_path).convert("L"), dtype=float)
            img2 = np.array(Image.open(f2_path).convert("L"), dtype=float)

            # Check 1: Blank/monochrome frame (low standard deviation)
            std1 = np.std(img1)
            if std1 < variance_threshold:
                print(f"[EMPTY CHECK] Frame is blank/monochrome (std={std1:.1f} < {variance_threshold}). REJECTED.")
                return True

            # Check 2: Frozen/dead-air (no motion between 25% and 75% marks)
            mean_delta = np.mean(np.abs(img1 - img2))
            if mean_delta < motion_diff_threshold:
                print(f"[EMPTY CHECK] Frame is frozen/static (delta={mean_delta:.1f} < {motion_diff_threshold}). REJECTED.")
                return True

            print(f"[EMPTY CHECK] Scene valid (std={std1:.1f}, motion_delta={mean_delta:.1f}). ACCEPTED.")
            return False
    except Exception as e:
        print(f"[EMPTY CHECK] Error during validation: {e}. Passing through.")
        return False


# ---------------------------------------------------------------------------
# 5. KEN BURNS PAN-ZOOM FALLBACK (guaranteed valid video from hero image)
# ---------------------------------------------------------------------------
def generate_pan_zoom_fallback(
    image_path: str,
    output_path: str,
    duration: float = 3.0,
    fps: int = 30
) -> str:
    """
    Creates an animated video from a static hero keyframe using a dynamic
    Ken Burns effect (zoom + slow pan). This is the absolute last-resort
    fallback -- always produces a valid video with motion.
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    total_frames = int(fps * duration)

    # Randomly pick a zoom direction for variety
    zoom_effects = [
        # Slow zoom in from center
        f"zoompan=z='min(zoom+0.002,1.4)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={total_frames}:s=1080x1920:fps={fps}",
        # Pan left to right while zooming
        f"zoompan=z='min(zoom+0.0015,1.3)':x='if(gte(on,1),x+2,0)':y='ih/4':d={total_frames}:s=1080x1920:fps={fps}",
        # Zoom out from top-left
        f"zoompan=z='if(eq(on,1),1.4,max(zoom-0.002,1.0))':x='iw/4':y='ih/4':d={total_frames}:s=1080x1920:fps={fps}",
    ]
    effect = random.choice(zoom_effects)

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", image_path,
        "-vf", f"{effect},format=yuv420p",
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        output_path
    ]
    try:
        subprocess.run(cmd, capture_output=True, check=True)
        if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            print(f"[PAN-ZOOM FALLBACK] Created Ken Burns clip: {output_path}")
            return output_path
    except Exception as e:
        print(f"[PAN-ZOOM FALLBACK] FFmpeg error: {e}")
    return None


# ---------------------------------------------------------------------------
# 6. PER-SCENE HERO IMAGE REFRAMING (break dead-center snapback)
# ---------------------------------------------------------------------------
# Scene composition presets: (crop_box_ratio, description)
# crop_box is (left%, top%, right%, bottom%) of the original image
SCENE_FRAMINGS = [
    # Act 1: Full body establishing shot (original, no crop)
    {"crop": (0.0, 0.0, 1.0, 1.0), "desc": "full body establishing"},
    # Act 2: Character shifted left, slight zoom
    {"crop": (0.0, 0.05, 0.75, 0.85), "desc": "left-shifted medium"},
    # Act 3: Close-up face/upper body (emotional reaction)
    {"crop": (0.1, 0.0, 0.9, 0.5), "desc": "close-up upper body"},
    # Act 4: Character shifted right, action framing
    {"crop": (0.25, 0.1, 1.0, 0.9), "desc": "right-shifted action"},
    # Act 5: Wide pull-back with character in lower third
    {"crop": (0.0, 0.15, 1.0, 1.0), "desc": "wide resolution shot"},
]

def reframe_hero_for_scene(
    hero_path: str,
    scene_index: int,
    output_path: str,
    target_width: int = 576,
    target_height: int = 1024
) -> str:
    """
    Creates a per-scene crop/reframe of the hero keyframe to vary
    composition across acts. Prevents the dead-center snapback where
    every scene looks identical because the same centered portrait
    is used as the I2V starting frame.
    """
    try:
        framing = SCENE_FRAMINGS[min(scene_index, len(SCENE_FRAMINGS) - 1)]
        crop = framing["crop"]

        with Image.open(hero_path) as img:
            w, h = img.size
            left = int(w * crop[0])
            top = int(h * crop[1])
            right = int(w * crop[2])
            bottom = int(h * crop[3])

            cropped = img.crop((left, top, right, bottom))
            # Resize back to target dimensions for I2V model
            resized = cropped.resize((target_width, target_height), Image.LANCZOS)
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            resized.save(output_path, format="PNG")

        print(f"[REFRAME] Act {scene_index+1}: {framing['desc']} → {output_path}")
        return output_path
    except Exception as e:
        print(f"[REFRAME] Error: {e}. Using original hero image.")
        return hero_path
