import os
import asyncio
import subprocess
import edge_tts
from gradio_client import Client, handle_file

from dotenv import load_dotenv
load_dotenv()

SPACE_NAME = "Lightricks/ltx-video-distilled"

def get_gradio_client():
    token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")
    if token and str(token).strip():
        return Client(SPACE_NAME, token=str(token).strip())
    return Client(SPACE_NAME)

def generate_ai_video_from_prompt(prompt: str, output_path: str, duration: int = 3) -> str:
    """
    Generates a 100% neural AI video clip from text using open cloud video diffusion ($0 cost).
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    try:
        client = get_gradio_client()
        result = client.predict(
            prompt=prompt,
            negative_prompt="worst quality, inconsistent motion, blurry, jittery, distorted, static",
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
            import shutil
            shutil.copy2(temp_vid, output_path)
            return output_path
        return None
    except Exception as e:
        print(f"[AI DIFFUSION] Error generating text-to-video: {e}")
        return None

def animate_image_to_video(image_path: str, prompt: str, output_path: str, duration: int = 3) -> str:
    """
    Animates a static AI image into real physical neural motion using Image-to-Video diffusion ($0 cost).
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    try:
        client = get_gradio_client()
        result = client.predict(
            prompt=prompt,
            negative_prompt="worst quality, inconsistent motion, blurry, jittery, distorted, static, motionless",
            input_image_filepath=handle_file(image_path),
            input_video_filepath=None,
            height_ui=704,
            width_ui=512,
            mode="image-to-video",
            duration_ui=duration,
            ui_frames_to_use=9,
            seed_ui=42,
            randomize_seed=True,
            ui_guidance_scale=1,
            improve_texture_flag=True,
            api_name="/image_to_video"
        )
        temp_vid = result[0].get("video")
        if temp_vid and os.path.exists(temp_vid):
            import shutil
            shutil.copy2(temp_vid, output_path)
            return output_path
        return None
    except Exception as e:
        print(f"[AI DIFFUSION] Error animating image-to-video: {e}")
        return None

def build_full_ai_short(raw_ai_video: str, voiceover_text: str, output_path: str, loops: int = 3) -> str:
    """
    Converts a raw AI video diffusion clip into a complete 1080x1920 vertical Short:
    - Scales and crops to 1080x1920 (9:16).
    - Loops seamlessly to match the voiceover duration.
    - Generates and mixes hyper-realistic voiceover via edge-tts.
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    temp_vo = os.path.join("data", "temp", "diffusion_vo.mp3")

    async def _synth():
        comm = edge_tts.Communicate(voiceover_text, "en-US-ChristopherNeural", rate="+8%")
        await comm.save(temp_vo)

    try:
        asyncio.run(_synth())
    except Exception as e:
        print(f"[AI DIFFUSION] Voiceover error: {e}")
        return None

    filter_complex = (
        f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,loop=loop={loops-1}:size=90:start=0,setpts=PTS-STARTPTS[v];"
        "[1:a]volume=1.35[vo]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", str(loops), "-i", raw_ai_video,
        "-i", temp_vo,
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[vo]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        output_path
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0 and os.path.exists(output_path):
        return output_path
    return None

def build_sfx_ai_short(raw_ai_video: str, audio_sfx_track: str, output_path: str, loops: int = 3) -> str:
    """
    Creates a pure Sound Effect + Cartoon Music AI Short (NO AI VOICE / NO NARRATOR),
    matching viral channels like Manoranjan Tales (236M views).
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    filter_complex = (
        f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,loop=loop={loops-1}:size=90:start=0,setpts=PTS-STARTPTS[v]"
    )
    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", str(loops), "-i", raw_ai_video,
        "-i", audio_sfx_track,
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "1:a",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        output_path
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0 and os.path.exists(output_path):
        return output_path
    return None
