import os
import ffmpeg

def generate_thumbnail(video_path: str, output_path: str) -> bool:
    """
    Extracts a frame from the video to serve as a thumbnail.
    For best organic results, we extract a frame roughly 15% into the video.
    """
    try:
        if not os.path.exists(video_path):
            print(f"Cannot generate thumbnail, video not found: {video_path}")
            return False
            
        probe = ffmpeg.probe(video_path)
        duration = float(probe['format']['duration'])
        
        # Capture frame at peak action hook (between 1.2s and 1.8s, or 18% of duration)
        target_time = min(1.8, max(1.0, duration * 0.18))
        
        print(f"Extracting enhanced thumbnail from {video_path} at {target_time:.2f}s...")
        filter_str = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,eq=contrast=1.12:saturation=1.25,unsharp=5:5:0.7:5:5:0.0"
        (
            ffmpeg
            .input(video_path, ss=target_time)
            .filter_('scale', 1080, 1920)
            .filter_('eq', contrast=1.12, saturation=1.25)
            .filter_('unsharp', luma_msize_x=5, luma_msize_y=5, luma_amount=0.7)
            .output(output_path, vframes=1, q=2)
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
        print(f"Enhanced thumbnail successfully saved to {output_path}")
        return True
    except ffmpeg.Error as e:
        error_message = e.stderr.decode() if e.stderr else str(e)
        print(f"FFmpeg thumbnail extraction error: {error_message}")
        return False
    except Exception as e:
        print(f"Unexpected error during thumbnail generation: {e}")
        return False
