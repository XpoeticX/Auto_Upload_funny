import os
import math
import wave
import struct
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
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"
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

def wrap_text(text: str, font, max_width: int, draw: ImageDraw.ImageDraw) -> list:
    words = text.split()
    lines = []
    curr = []
    for word in words:
        test_line = " ".join(curr + [word])
        bbox = draw.textbbox((0, 0), test_line, font=font)
        if (bbox[2] - bbox[0]) <= max_width:
            curr.append(word)
        else:
            if curr:
                lines.append(" ".join(curr))
            curr = [word]
    if curr:
        lines.append(" ".join(curr))
    return lines

def synthesize_audio_sfx(output_path: str, freq: int = 800, duration: float = 0.12, volume: float = 0.5):
    """Synthesizes clean audio tones (ticks, chimes) without external asset dependencies."""
    sample_rate = 44100
    n_samples = int(sample_rate * duration)
    with wave.open(output_path, 'w') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        data = bytearray()
        for i in range(n_samples):
            fade = 1.0 - (i / n_samples)
            sample = int(32767 * volume * fade * math.sin(2 * math.pi * freq * (i / sample_rate)))
            data.extend(struct.pack('<h', sample))
        w.writeframes(data)

async def synthesize_voiceover(text: str, output_path: str, voice: str = "en-US-ChristopherNeural") -> float:
    """Generates neural voiceover using edge-tts and returns exact duration."""
    communicate = edge_tts.Communicate(text, voice, rate="+5%")
    await communicate.save(output_path)
    try:
        probe = ffmpeg.probe(output_path)
        return float(probe['format']['duration'])
    except Exception:
        return 8.0

def render_dilemma_card(dilemma: dict, state: str = "question", countdown: int = 0) -> str:
    """
    Renders 1080x1920 high-contrast split-screen graphic card:
    - Top: Option A (Deep Indigo/Blue)
    - Bottom: Option B (Deep Crimson/Red)
    - Center: 'VS' badge + Countdown or Reveal Percentage
    """
    img = Image.new("RGB", (1080, 1920), color=(15, 23, 42)) # Slate 900 background
    draw = ImageDraw.Draw(img)

    # 1. Header Banner
    draw.rounded_rectangle([60, 60, 1020, 160], radius=30, fill=(30, 41, 59), outline=(245, 158, 11), width=4)
    header_font = get_font(52)
    header_text = "⚡ WOULD YOU RATHER ⚡"
    h_bbox = draw.textbbox((0, 0), header_text, font=header_font)
    draw.text(((1080 - (h_bbox[2] - h_bbox[0])) // 2, 78), header_text, font=header_font, fill=(251, 191, 36))

    topic_text = dilemma.get("topic", "CHOOSE YOUR SIDE").upper()
    topic_font = get_font(32)
    t_bbox = draw.textbbox((0, 0), topic_text, font=topic_font)
    draw.text(((1080 - (t_bbox[2] - t_bbox[0])) // 2, 175), topic_text, font=topic_font, fill=(148, 163, 184))

    # 2. Option A Card (Top Half: Y 230 -> 930)
    opt_a = dilemma.get("option_a", {})
    draw.rounded_rectangle([50, 230, 1030, 930], radius=40, fill=(30, 27, 75), outline=(99, 102, 241), width=5)
    
    # Emoji / Icon badge
    draw.rounded_rectangle([480, 260, 600, 360], radius=20, fill=(49, 46, 129))
    emoji_font = get_font(56)
    draw.text((515, 275), opt_a.get("emoji", "🔥"), font=emoji_font, fill=(255, 255, 255))
    
    # Option A Text
    text_font = get_font(50)
    lines_a = wrap_text(opt_a.get("text", "Option A").upper(), text_font, 880, draw)
    curr_y = 420
    for line in lines_a[:3]:
        l_bbox = draw.textbbox((0, 0), line, font=text_font)
        draw.text(((1080 - (l_bbox[2] - l_bbox[0])) // 2, curr_y), line, font=text_font, fill=(255, 255, 255))
        curr_y += 65

    # 3. Option B Card (Bottom Half: Y 990 -> 1690)
    opt_b = dilemma.get("option_b", {})
    draw.rounded_rectangle([50, 990, 1030, 1690], radius=40, fill=(136, 19, 55), outline=(244, 63, 94), width=5)
    
    # Emoji / Icon badge
    draw.rounded_rectangle([480, 1020, 600, 1120], radius=20, fill=(159, 18, 57))
    draw.text((515, 1035), opt_b.get("emoji", "❄️"), font=emoji_font, fill=(255, 255, 255))
    
    # Option B Text
    lines_b = wrap_text(opt_b.get("text", "Option B").upper(), text_font, 880, draw)
    curr_y = 1180
    for line in lines_b[:3]:
        l_bbox = draw.textbbox((0, 0), line, font=text_font)
        draw.text(((1080 - (l_bbox[2] - l_bbox[0])) // 2, curr_y), line, font=text_font, fill=(255, 255, 255))
        curr_y += 65

    # 4. Center Divider & Badges
    center_y = 960
    if state == "question":
        # VS Circular Badge
        draw.ellipse([465, center_y - 75, 615, center_y + 75], fill=(251, 191, 36), outline=(255, 255, 255), width=6)
        vs_font = get_font(60)
        v_bbox = draw.textbbox((0, 0), "VS", font=vs_font)
        draw.text(((1080 - (v_bbox[2] - v_bbox[0])) // 2, center_y - 45), "VS", font=vs_font, fill=(15, 23, 42))

    elif state == "countdown":
        # Countdown Timer Circle
        draw.ellipse([465, center_y - 75, 615, center_y + 75], fill=(239, 68, 68), outline=(255, 255, 255), width=6)
        cd_font = get_font(72)
        c_text = str(countdown)
        c_bbox = draw.textbbox((0, 0), c_text, font=cd_font)
        draw.text(((1080 - (c_bbox[2] - c_bbox[0])) // 2, center_y - 52), c_text, font=cd_font, fill=(255, 255, 255))

    elif state == "reveal":
        # Reveal State: Display giant percentage split on cards!
        draw.ellipse([465, center_y - 75, 615, center_y + 75], fill=(34, 197, 94), outline=(255, 255, 255), width=6)
        chk_font = get_font(52)
        chk_bbox = draw.textbbox((0, 0), "PICK", font=chk_font)
        draw.text(((1080 - (chk_bbox[2] - chk_bbox[0])) // 2, center_y - 38), "PICK", font=chk_font, fill=(255, 255, 255))

        # Big Glowing Percentages
        pct_font = get_font(110)
        pct_a = f"{opt_a.get('percentage', 50)}%"
        pct_b = f"{opt_b.get('percentage', 50)}%"

        pa_bbox = draw.textbbox((0, 0), pct_a, font=pct_font)
        draw.rounded_rectangle([290, 710, 790, 890], radius=30, fill=(49, 46, 129, 230), outline=(251, 191, 36), width=6)
        draw.text(((1080 - (pa_bbox[2] - pa_bbox[0])) // 2, 730), pct_a, font=pct_font, fill=(251, 191, 36))

        pb_bbox = draw.textbbox((0, 0), pct_b, font=pct_font)
        draw.rounded_rectangle([290, 1470, 790, 1650], radius=30, fill=(159, 18, 57, 230), outline=(251, 191, 36), width=6)
        draw.text(((1080 - (pb_bbox[2] - pb_bbox[0])) // 2, 1490), pct_b, font=pct_font, fill=(251, 191, 36))

    # 5. Footer Safe-Zone Watermark & Call To Action
    cta_font = get_font(34)
    cta_text = "COMMENT YOUR CHOICE BELOW! 👇"
    cta_bbox = draw.textbbox((0, 0), cta_text, font=cta_font)
    draw.text(((1080 - (cta_bbox[2] - cta_bbox[0])) // 2, 1735), cta_text, font=cta_font, fill=(241, 245, 249))

    wm_font = get_font(30)
    wm_text = "@DailyDosOfFun"
    wm_bbox = draw.textbbox((0, 0), wm_text, font=wm_font)
    draw.text(((1080 - (wm_bbox[2] - wm_bbox[0])) // 2, 1800), wm_text, font=wm_font, fill=(148, 163, 184, 180))

    card_path = os.path.join("data", "temp", f"card_{state}_{countdown}.jpg")
    os.makedirs(os.path.dirname(card_path), exist_ok=True)
    img.save(card_path, quality=95)
    return card_path

def create_dilemma_video(dilemma: dict, output_video_path: str) -> str:
    """
    Assembles a complete, broadcast-ready 1080x1920 MP4 AI dilemma video:
    - Phase 1: Question Presentation + Voiceover (Duration = VO length)
    - Phase 2: Countdown Timer (3s tick... tick... tick...)
    - Phase 3: Reveal percentages (3.5s ding!)
    Total Duration: ~14 to 18 seconds.
    """
    os.makedirs("data/temp", exist_ok=True)
    os.makedirs(os.path.dirname(output_video_path), exist_ok=True)

    # 1. Voiceover Synthesis
    vo_script = dilemma.get("voiceover_script") or "Would you rather pick Option A or Option B? Decide before the timer ends!"
    vo_path = os.path.join("data", "temp", "dilemma_vo.mp3")
    vo_duration = asyncio.run(synthesize_voiceover(vo_script, vo_path))
    vo_duration = max(5.0, min(14.0, vo_duration))

    # 2. Synthesize Countdown and Reveal SFX
    tick_path = os.path.join("data", "temp", "tick.wav")
    ding_path = os.path.join("data", "temp", "ding.wav")
    synthesize_audio_sfx(tick_path, freq=850, duration=0.10, volume=0.5)
    synthesize_audio_sfx(ding_path, freq=1174, duration=0.60, volume=0.7)

    # 3. Render Graphic Cards
    img_question = render_dilemma_card(dilemma, state="question")
    img_cd3 = render_dilemma_card(dilemma, state="countdown", countdown=3)
    img_cd2 = render_dilemma_card(dilemma, state="countdown", countdown=2)
    img_cd1 = render_dilemma_card(dilemma, state="countdown", countdown=1)
    img_reveal = render_dilemma_card(dilemma, state="reveal")

    # 4. Generate Visual Slides Concat File
    concat_txt = os.path.join("data", "temp", "slides_concat.txt")
    with open(concat_txt, "w", encoding="utf-8") as f:
        f.write(f"file '{os.path.abspath(img_question)}'\n")
        f.write(f"duration {vo_duration:.2f}\n")
        f.write(f"file '{os.path.abspath(img_cd3)}'\n")
        f.write(f"duration 1.0\n")
        f.write(f"file '{os.path.abspath(img_cd2)}'\n")
        f.write(f"duration 1.0\n")
        f.write(f"file '{os.path.abspath(img_cd1)}'\n")
        f.write(f"duration 1.0\n")
        f.write(f"file '{os.path.abspath(img_reveal)}'\n")
        f.write(f"duration 3.5\n")
        f.write(f"file '{os.path.abspath(img_reveal)}'\n")

    total_duration = vo_duration + 3.0 + 3.5

    # 5. Composite Video and Audio Mix with FFmpeg
    # Audio Track Layout:
    # 0s to vo_duration: Voiceover
    # vo_duration: tick
    # vo_duration + 1: tick
    # vo_duration + 2: tick
    # vo_duration + 3: ding
    try:
        t0 = vo_duration
        t1 = vo_duration + 1.0
        t2 = vo_duration + 2.0
        t3 = vo_duration + 3.0

        # Construct filter complex to mix VO + ticks + ding into one audio stream
        in_vo = ffmpeg.input(vo_path)
        in_tick0 = ffmpeg.input(tick_path).filter('adelay', f"{int(t0*1000)}|{int(t0*1000)}")
        in_tick1 = ffmpeg.input(tick_path).filter('adelay', f"{int(t1*1000)}|{int(t1*1000)}")
        in_tick2 = ffmpeg.input(tick_path).filter('adelay', f"{int(t2*1000)}|{int(t2*1000)}")
        in_ding = ffmpeg.input(ding_path).filter('adelay', f"{int(t3*1000)}|{int(t3*1000)}")

        mixed_audio = ffmpeg.filter([in_vo, in_tick0, in_tick1, in_tick2, in_ding], 'amix', inputs=5, duration='longest')

        in_video = ffmpeg.input(concat_txt, format='concat', safe=0)

        (
            ffmpeg
            .output(
                in_video, mixed_audio, output_video_path,
                vcodec='libx264', preset='veryfast', crf=22, pix_fmt='yuv420p',
                acodec='aac', audio_bitrate='192k', ar=44100,
                t=total_duration, r=30
            )
            .overwrite_output()
            .run(quiet=True)
        )

        if os.path.exists(output_video_path):
            print(f"[AI VIDEO ENGINE] Rendered 1080x1920 video: {output_video_path} (Duration: {total_duration:.1f}s)")
            return output_video_path
        return None
    except Exception as e:
        print(f"[AI VIDEO ENGINE] Video render error: {e}")
        return None

def create_dilemma_compilation(dilemmas: list, output_video_path: str) -> str:
    """
    Renders 3 unique dilemmas and concatenates them into a 45-60s compilation video.
    """
    segment_paths = []
    for idx, dilemma in enumerate(dilemmas[:3]):
        seg_path = os.path.join("data", "temp", f"ai_seg_{idx}.mp4")
        rendered = create_dilemma_video(dilemma, seg_path)
        if rendered and os.path.exists(rendered):
            segment_paths.append(rendered)

    if not segment_paths:
        return None

    if len(segment_paths) == 1:
        import shutil
        shutil.copy(segment_paths[0], output_video_path)
        return output_video_path

    concat_file = os.path.join("data", "temp", "comp_concat.txt")
    with open(concat_file, "w", encoding="utf-8") as f:
        for p in segment_paths:
            f.write(f"file '{os.path.abspath(p)}'\n")

    try:
        (
            ffmpeg
            .input(concat_file, format='concat', safe=0)
            .output(output_video_path, c='copy')
            .overwrite_output()
            .run(quiet=True)
        )
        if os.path.exists(output_video_path):
            print(f"[AI VIDEO ENGINE] Compilation assembled successfully: {output_video_path}")
            return output_video_path
        return None
    except Exception as e:
        print(f"[AI VIDEO ENGINE] Compilation merge error: {e}")
        return None
