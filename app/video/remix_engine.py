import os
import asyncio
import ffmpeg
import edge_tts
from PIL import Image, ImageDraw, ImageFont

def get_font(size: int = 40):
    candidates = [
        "impact.ttf",
        "arialbd.ttf",
        "arial.ttf",
        "segoeuib.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
    ]
    for font_path in candidates:
        try:
            return ImageFont.truetype(font_path, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None

def create_meme_overlay(headline: str, output_png_path: str, watermark: str = "@DailyDosOfFun"):
    """
    Creates a transparent 1080x1920 PNG overlay with:
    - Top Meme Banner Pill (with border and drop shadow)
    - Bottom Safe-zone Watermark
    """
    img = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 1. Top Meme Headline Pill (Y: 90 -> 230)
    headline_clean = headline.upper().strip()
    draw.rounded_rectangle([60, 90, 1020, 230], radius=35, fill=(15, 23, 42, 235), outline=(245, 158, 11), width=5)

    f_headline = get_font(52)
    bbox = draw.textbbox((0, 0), headline_clean, font=f_headline)
    text_w = bbox[2] - bbox[0]
    
    # Auto-adjust font size if text is too wide
    if text_w > 900:
        f_headline = get_font(42)
        bbox = draw.textbbox((0, 0), headline_clean, font=f_headline)
        text_w = bbox[2] - bbox[0]

    draw.text(((1080 - text_w) // 2, 130), headline_clean, font=f_headline, fill=(251, 191, 36))

    # 2. Bottom Watermark Pill (Y: 1780 -> 1850)
    draw.rounded_rectangle([330, 1780, 750, 1850], radius=25, fill=(15, 23, 42, 210), outline=(255, 255, 255, 90), width=2)
    f_wm = get_font(32)
    bbox_wm = draw.textbbox((0, 0), watermark, font=f_wm)
    wm_w = bbox_wm[2] - bbox_wm[0]
    draw.text(((1080 - wm_w) // 2, 1795), watermark, font=f_wm, fill=(255, 255, 255))

    os.makedirs(os.path.dirname(output_png_path), exist_ok=True)
    img.save(output_png_path, format="PNG")
    return output_png_path

def transform_video_with_ai(input_video_path: str, ai_data: dict, output_video_path: str) -> str:
    """
    Transforms a raw viral video into a 100% original AI Short:
    - Synthesizes character AI voiceover with edge-tts.
    - Centers and crops to 1080x1920 (9:16), cropping out any watermarks.
    - Alters speed (+3%) and saturation to generate a completely unique digital hash.
    - Burns in top meme banner and watermark.
    - Mixes boosted AI voiceover over lowered original audio.
    """
    os.makedirs("data/temp", exist_ok=True)
    os.makedirs(os.path.dirname(output_video_path), exist_ok=True)

    # 1. Voiceover Synthesis
    vo_script = ai_data.get("voiceover_script", "Wait for it... you will not believe what happens next!")
    voice_name = ai_data.get("voice_name", "en-US-ChristopherNeural")
    vo_path = os.path.join("data", "temp", "remix_vo.mp3")

    async def _synth():
        comm = edge_tts.Communicate(vo_script, voice_name, rate="+6%")
        await comm.save(vo_path)

    try:
        asyncio.run(_synth())
    except Exception as e:
        print(f"[REMIX ENGINE] Voiceover synthesis notice: {e}")
        return None

    # Probe durations and video dimensions
    try:
        probe_v = ffmpeg.probe(input_video_path)
        v_stream = next(s for s in probe_v['streams'] if s['codec_type'] == 'video')
        orig_w = int(v_stream['width'])
        orig_h = int(v_stream['height'])
        orig_dur = float(probe_v['format']['duration'])

        probe_a = ffmpeg.probe(vo_path)
        vo_dur = float(probe_a['format']['duration'])
    except Exception as e:
        print(f"[REMIX ENGINE] Probe error: {e}")
        return None

    target_duration = max(vo_dur + 1.0, min(orig_dur, 28.0))

    # 2. Create Transparent Meme Overlay PNG
    headline = ai_data.get("top_meme_headline") or "WAIT FOR THE END 😂💀"
    overlay_png = os.path.join("data", "temp", "remix_overlay.png")
    create_meme_overlay(headline, overlay_png)

    # 3. Construct FFmpeg Transformation Filtergraph
    try:
        in_vid = ffmpeg.input(input_video_path, t=target_duration)
        in_vo = ffmpeg.input(vo_path)
        in_overlay = ffmpeg.input(overlay_png)

        # Check if original video has audio
        has_orig_audio = any(s['codec_type'] == 'audio' for s in probe_v['streams'])

        # Aspect ratio adaptation:
        # If already vertical (in_h > in_w), scale to fill 1080x1920 with slight crop.
        # If landscape (in_w >= in_h), use blurred background + sharp centered foreground.
        if orig_h > orig_w:
            video_base = (
                in_vid.video
                .filter('scale', 1080, 1920, force_original_aspect_ratio='increase')
                .filter('crop', 1080, 1920)
            )
        else:
            # Blur background + centered foreground for landscape clips
            bg = (
                in_vid.video
                .filter('scale', 1080, 1920, force_original_aspect_ratio='increase')
                .filter('crop', 1080, 1920)
                .filter('boxblur', 25, 5)
            )
            fg = in_vid.video.filter('scale', 1080, -1)
            video_base = ffmpeg.overlay(bg, fg, x='(W-w)/2', y='(H-h)/2')

        # Speed adjustment (+3%) and slight saturation boost to alter hash
        video_filtered = (
            video_base
            .filter('setpts', '0.97*PTS')
            .filter('eq', saturation=1.06)
        )

        # Overlay top banner and watermark
        video_with_overlay = ffmpeg.overlay(video_filtered, in_overlay, x=0, y=0)

        # Audio Mixing: Boost AI Voiceover (volume 1.25), lower original sound (volume 0.15)
        vo_audio = in_vo.filter('volume', 1.25)
        if has_orig_audio:
            orig_audio = in_vid.audio.filter('volume', 0.15).filter('atempo', 1.03)
            mixed_audio = ffmpeg.filter([vo_audio, orig_audio], 'amix', inputs=2, duration='first')
        else:
            mixed_audio = vo_audio

        # Output encoding
        (
            ffmpeg
            .output(
                video_with_overlay, mixed_audio, output_video_path,
                vcodec='libx264', preset='veryfast', crf=22, pix_fmt='yuv420p',
                acodec='aac', audio_bitrate='192k', ar=44100,
                t=target_duration / 1.03, r=30
            )
            .overwrite_output()
            .run(quiet=True)
        )

        if os.path.exists(output_video_path) and os.path.getsize(output_video_path) > 1000:
            print(f"[REMIX ENGINE] Rendered transformed AI Short: {output_video_path} (Duration: {target_duration/1.03:.1f}s)")
            return output_video_path
        return None
    except Exception as e:
        print(f"[REMIX ENGINE] Transformation error: {e}")
        return None
