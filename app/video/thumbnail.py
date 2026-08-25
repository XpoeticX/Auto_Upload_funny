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
        
        # Capture frame at 15% of the video duration (usually peak action or past intros)
        target_time = duration * 0.15
        
        print(f"Extracting thumbnail from {video_path} at {target_time:.2f}s...")
        (
            ffmpeg
            .input(video_path, ss=target_time)
            .filter('scale', 1080, 1920)
            .output(output_path, vframes=1, q=2)
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
        print(f"Thumbnail successfully saved to {output_path}")
        return True
    except ffmpeg.Error as e:
        error_message = e.stderr.decode() if e.stderr else str(e)
        print(f"FFmpeg thumbnail extraction error: {error_message}")
        return False
    except Exception as e:
        print(f"Unexpected error during thumbnail generation: {e}")
        return False
