import ffmpeg
import os



def extract_frame(video_path: str, output_image_path: str, timestamp: float = 1.0) -> bool:
    """Extracts a single frame from video at given timestamp to use in transition posters."""
    try:
        if not os.path.exists(video_path):
            return False
        (
            ffmpeg
            .input(video_path, ss=timestamp)
            .filter('scale', 1080, 1920)
            .output(output_image_path, vframes=1, q=2)
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
        return os.path.exists(output_image_path)
    except Exception as e:
        print(f"Error extracting frame: {e}")
        return False

def create_watermark_image(width: int = 1080, height: int = 1920, channel_handle: str = "@DailyDosOfFun") -> str:
    """
    Generates a crisp, transparent PNG watermark with subtle drop shadow
    positioned in the vertical safe zone (260px from bottom).
    """
    wm_path = os.path.join("data", "temp", f"watermark_{width}x{height}.png")
    os.makedirs(os.path.dirname(wm_path), exist_ok=True)
    if os.path.exists(wm_path):
        return wm_path
        
    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        font_size = 36 if width >= 1080 else 24
        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()
            
        bbox = draw.textbbox((0, 0), channel_handle, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        tx = (width - tw) // 2
        ty = height - th - (260 if height >= 1920 else 120)
        
        # Soft shadow + 65% opacity white text
        draw.text((tx + 2, ty + 2), channel_handle, font=font, fill=(0, 0, 0, 130))
        draw.text((tx, ty), channel_handle, font=font, fill=(255, 255, 255, 170))
        
        img.save(wm_path)
        return wm_path
    except Exception as e:
        print(f"Failed to generate watermark overlay: {e}")
        return None

def normalize_video(input_path: str, output_path: str, is_short: bool = True, max_duration: float = None, 
                    watermark_text: str = "@DailyDosOfFun", start_time: float = 0.0, end_time: float = None) -> str:
    """
    Standardizes video to 30fps with standard AAC audio without altering aspect ratio.
    - If video is 9:16 (vertical), keeps it 9:16 vertical (1080x1920).
    - If video is 16:9 (horizontal), keeps it 16:9 horizontal (1920x1080).
    - Precise Timestamp Trimming: If start_time / end_time provided by Gemini Vision, trims directly to peak hook.
    - If max_duration is specified, cleanly trims the video to maintain fast pacing (15-20s).
    - Audio Dynamics: Applies dynaudnorm filter for balanced, punchy audio volume.
    - Bakes in a permanent, semi-transparent watermark for originality & branding.
    """
    print(f"Normalizing clip: {output_path} (Hook Window: {start_time}s -> {end_time if end_time else max_duration}s)")
    
    try:
        probe = ffmpeg.probe(input_path)
        video_info = next((s for s in probe['streams'] if s['codec_type'] == 'video'), None)
        
        in_w = int(video_info['width']) if video_info and 'width' in video_info else 1080
        in_h = int(video_info['height']) if video_info and 'height' in video_info else 1920
        aspect_ratio = in_w / in_h if in_h > 0 else 0.5625
        
        input_kwargs = {}
        if start_time and start_time > 0.0:
            input_kwargs['ss'] = start_time
            
        vid_in = ffmpeg.input(input_path, **input_kwargs)
        
        # Check if the video is vertical (9:16)
        if 0.50 <= aspect_ratio <= 0.65 or in_w < in_h:
            target_w, target_h = 1080, 1920
        else:
            target_w, target_h = 1920, 1080
            
        v_stream = (
            vid_in.video
            .filter('scale', target_w, target_h, force_original_aspect_ratio='decrease')
            .filter('pad', target_w, target_h, '(ow-iw)/2', '(oh-ih)/2', color='black')
            .filter('setsar', 1)
            .filter('fps', fps=30)
        )
        
        # Apply permanent semi-transparent watermark branding
        wm_file = create_watermark_image(target_w, target_h, watermark_text)
        if wm_file and os.path.exists(wm_file):
            wm_in = ffmpeg.input(wm_file)
            v_stream = ffmpeg.filter([v_stream, wm_in], 'overlay', 0, 0)
        
        # Standardize audio to 44.1kHz stereo with dynamic audio leveling
        try:
            a_stream = (
                vid_in.audio
                .filter('dynaudnorm', f=150, g=15)
                .filter('aformat', sample_rates='44100', channel_layouts='stereo')
            )
        except Exception:
            a_stream = None
            
        out_streams = [v_stream]
        if a_stream is not None:
            out_streams.append(a_stream)
            
        out_kwargs = {
            'vcodec': 'libx264',
            'preset': 'fast',
            'crf': 23,
            'acodec': 'aac',
            'audio_bitrate': '128k',
            'ar': '44100'
        }
        
        # Calculate duration
        if end_time and end_time > start_time:
            trim_duration = end_time - start_time
            if max_duration:
                trim_duration = min(trim_duration, max_duration)
            out_kwargs['t'] = trim_duration
        elif max_duration and max_duration > 0:
            out_kwargs['t'] = max_duration
            
        (
            ffmpeg
            .output(*out_streams, output_path, **out_kwargs)
            .overwrite_output()
            .run(quiet=True)
        )
        
        if os.path.exists(output_path):
            return output_path
        return None
    except Exception as e:
        print(f"Error normalizing video: {e}")
        return None

from PIL import Image, ImageDraw, ImageFont, ImageFilter

def create_meme_transition_clip(caption: str, output_path: str, duration: float = 1.5, previous_frame_path: str = None) -> str:
    """
    Generates a 1080x1920 meme transition poster video clip (duration ~1.5s)
    to cleanly separate consecutive compilation videos with engaging viral meme commentary.
    """
    print(f"Generating meme transition poster clip: {output_path} (Caption: {caption})")
    
    W, H = 1080, 1920
    poster_img_path = output_path.replace(".mp4", "_poster.jpg")
    
    try:
        if previous_frame_path and os.path.exists(previous_frame_path):
            base = Image.open(previous_frame_path).convert("RGB")
            # Create a stylized blurred background
            bg = base.resize((W, H)).filter(ImageFilter.GaussianBlur(radius=25))
            # Dim the background slightly
            overlay = Image.new("RGBA", (W, H), (0, 0, 0, 140))
            bg.paste(overlay, (0, 0), overlay)
            
            # Place a clean framed snapshot card in the upper-middle
            card_w, card_h = 760, 760
            snapshot = base.resize((card_w, card_h), Image.Resampling.LANCZOS)
            card_x = (W - card_w) // 2
            card_y = 360
            
            # Draw white border for the card
            draw = ImageDraw.Draw(bg)
            draw.rectangle([card_x - 6, card_y - 6, card_x + card_w + 6, card_y + card_h + 6], fill=(255, 255, 255))
            bg.paste(snapshot, (card_x, card_y))
        else:
            # Create sleek dark background
            bg = Image.new("RGB", (W, H), color=(18, 18, 22))
            draw = ImageDraw.Draw(bg)
            draw.rectangle([40, 40, W - 40, H - 40], outline=(255, 204, 0), width=6)
            
        draw = ImageDraw.Draw(bg)
        
        # Load standard fonts or use default
        try:
            font_banner = ImageFont.truetype("arialbd.ttf", 52)
            font_caption = ImageFont.truetype("arialbd.ttf", 56)
            font_footer = ImageFont.truetype("arialbd.ttf", 44)
        except Exception:
            try:
                font_banner = ImageFont.truetype("arial.ttf", 52)
                font_caption = ImageFont.truetype("arial.ttf", 56)
                font_footer = ImageFont.truetype("arial.ttf", 44)
            except Exception:
                font_banner = ImageFont.load_default()
                font_caption = ImageFont.load_default()
                font_footer = ImageFont.load_default()
                
        # Draw Top Banner Badge
        banner_text = "🔥 NEXT CLIP IN 3.. 2.. 1.. 🔥"
        banner_bg = [80, 160, W - 80, 270]
        draw.rectangle(banner_bg, fill=(255, 204, 0))
        
        # Center banner text
        bbox = draw.textbbox((0, 0), banner_text, font=font_banner)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.text(((W - tw) // 2, 215 - th // 2), banner_text, fill=(0, 0, 0), font=font_banner)
        
        # Draw Meme Caption (Wrapped)
        caption_text = caption if caption else "Wait till you see what happens next! 😂"
        words = caption_text.split()
        lines = []
        cur_line = []
        for word in words:
            cur_line.append(word)
            test_line = " ".join(cur_line)
            t_bbox = draw.textbbox((0, 0), test_line, font=font_caption)
            if (t_bbox[2] - t_bbox[0]) > (W - 160):
                cur_line.pop()
                lines.append(" ".join(cur_line))
                cur_line = [word]
        if cur_line:
            lines.append(" ".join(cur_line))
            
        start_y = 1220
        for line in lines:
            l_bbox = draw.textbbox((0, 0), line, font=font_caption)
            lw = l_bbox[2] - l_bbox[0]
            lh = l_bbox[3] - l_bbox[1]
            lx = (W - lw) // 2
            # Draw bold black shadow
            for off in [(-3, -3), (3, -3), (-3, 3), (3, 3), (0, 4)]:
                draw.text((lx + off[0], start_y + off[1]), line, fill=(0, 0, 0), font=font_caption)
            draw.text((lx, start_y), line, fill=(255, 255, 255), font=font_caption)
            start_y += lh + 20
            
        # Draw Footer Callout
        footer_text = "👉 GET READY! 👈"
        f_bbox = draw.textbbox((0, 0), footer_text, font=font_footer)
        fw = f_bbox[2] - f_bbox[0]
        draw.text(((W - fw) // 2, 1680), footer_text, fill=(255, 204, 0), font=font_footer)
        
        bg.save(poster_img_path, quality=95)
        
        # Render image into 1.5s MP4 video with silent stereo audio using ffmpeg
        (
            ffmpeg
            .input(poster_img_path, loop=1, t=duration)
            .output(
                ffmpeg.input('anullsrc=r=44100:cl=stereo', f='lavfi').audio,
                output_path,
                vcodec='libx264',
                pix_fmt='yuv420p',
                r=30,
                t=duration,
                acodec='aac',
                audio_bitrate='128k',
                preset='fast'
            )
            .overwrite_output()
            .run(quiet=True)
        )
        
        if os.path.exists(output_path):
            return output_path
        return None
    except Exception as e:
        print(f"Error creating meme transition clip: {e}")
        return None
    finally:
        if os.path.exists(poster_img_path):
            try:
                os.remove(poster_img_path)
            except Exception:
                pass

def merge_compilation(video_paths: list, output_path: str) -> str:
    """
    Takes a list of identical format videos and quickly concatenates them together.
    """
    if not video_paths:
        return None
        
    print(f"Merging {len(video_paths)} videos into a compilation...")
    
    concat_file = "concat_list.txt"
    try:
        with open(concat_file, "w", encoding="utf-8") as f:
            for path in video_paths:
                # ffmpeg requires absolute paths or relative paths in quotes
                f.write(f"file '{os.path.abspath(path)}'\n")
                
        (
            ffmpeg
            .input(concat_file, format='concat', safe=0)
            .output(output_path, c='copy') # stream copy, incredibly fast
            .overwrite_output()
            .run(quiet=True)
        )
        
        if os.path.exists(output_path):
            print("Compilation rendering successful!")
            return output_path
    except ffmpeg.Error as e:
        print("FFmpeg concat error:", e.stderr.decode('utf8') if e.stderr else str(e))
    except Exception as e:
        print(f"Error compiling videos: {e}")
    finally:
        if os.path.exists(concat_file):
            os.remove(concat_file)
            
    return None
