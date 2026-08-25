import os
import requests
import yt_dlp
import re

def extract_youtube_id(url: str) -> str:
    match = re.search(r'(?:v=|\/)([0-9A-Za-z_-]{11}).*', url)
    if match:
        return match.group(1)
    return None

def download_video(url: str, output_path: str) -> str:
    """
    Downloads a video from a URL.
    Implements a Waterfall API Router to maximize limits.
    """
    print(f"Downloading video from {url}...")
    rapidapi_key = os.environ.get("RAPIDAPI_KEY")
    
    # --- RAPIDAPI YOUTUBE WATERFALL ROUTER ---
    if "youtube.com" in url or "youtu.be" in url:
        if rapidapi_key:
            video_id = extract_youtube_id(url)
            
            # 1. Social Media Video Downloader (Primary - tunnels through smvd.xyz proxy to bypass Google IP lock)
            print("Router: Trying Social Media Video Downloader...")
            try:
                r = requests.get("https://social-media-video-downloader.p.rapidapi.com/youtube/v3/video/details",
                                 headers={"x-rapidapi-key": rapidapi_key, "x-rapidapi-host": "social-media-video-downloader.p.rapidapi.com"},
                                 params={"videoId": video_id},
                                 timeout=12)
                if r.status_code == 200:
                    videos = r.json().get("contents", [{}])[0].get("videos", [])
                    best_url = next((v.get("url") for v in videos if v.get("url")), None)
                    if best_url:
                        dl = download_from_url(best_url, output_path)
                        if dl:
                            return dl
            except Exception as e:
                print(f"Social Media Video Downloader Failed: {e}")

            # 2. Cloud Api Hub - Youtube Downloader (Secondary fallback)
            print("Router: Switching to Cloud Api Hub...")
            try:
                r = requests.get("https://cloud-api-hub-youtube-downloader.p.rapidapi.com/download",
                                 headers={"x-rapidapi-key": rapidapi_key, "x-rapidapi-host": "cloud-api-hub-youtube-downloader.p.rapidapi.com"},
                                 params={"url": url},
                                 timeout=12)
                if r.status_code == 200:
                    data = r.json()
                    if isinstance(data, list):
                        best_url = next((item.get("url") for item in data if item.get("ext") == "mp4" and item.get("acodec") != "none" and item.get("url")), None)
                        if best_url:
                            dl = download_from_url(best_url, output_path)
                            if dl:
                                return dl
            except Exception as e:
                print(f"Cloud Api Hub Failed: {e}")

            # 3. YouTube Media Downloader (Tertiary fallback)
            print("Router: Trying YouTube Media Downloader...")
            try:
                r = requests.get("https://youtube-media-downloader.p.rapidapi.com/v2/video/details", 
                                 headers={"x-rapidapi-key": rapidapi_key, "x-rapidapi-host": "youtube-media-downloader.p.rapidapi.com"}, 
                                 params={"videoId": video_id},
                                 timeout=12)
                if r.status_code == 200:
                    items = r.json().get("videos", {}).get("items", [])
                    best_url = next((item.get("url") for item in items if item.get("extension") == "mp4" and item.get("hasAudio")), None)
                    if best_url:
                        dl = download_from_url(best_url, output_path)
                        if dl:
                            return dl
            except Exception as e:
                print(f"YouTube Media Downloader Failed: {e}")

            print("Router: All YouTube APIs exhausted. Falling back to yt-dlp...")
        else:
            print("No RAPIDAPI_KEY found. Using yt-dlp...")
            
    # --- RAPIDAPI TIKTOK ROUTER ---
    elif "tiktok.com" in url:
        if rapidapi_key:
            print("Router: Trying TikTok Downloader...")
            try:
                r = requests.get("https://tiktok-downloader-download-tiktok-videos-without-watermark.p.rapidapi.com/rich_response/index",
                                 headers={"x-rapidapi-key": rapidapi_key, "x-rapidapi-host": "tiktok-downloader-download-tiktok-videos-without-watermark.p.rapidapi.com"},
                                 params={"url": url})
                if r.status_code == 200:
                    video_url = r.json().get("video", [None])[0]
                    if video_url:
                        return download_from_url(video_url, output_path)
            except Exception as e:
                print(f"TikTok API Failed: {e}")
            print("Router: TikTok API exhausted. Falling back to yt-dlp...")

    # --- DEFAULT YT-DLP (Imgur, Fallback) ---
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': output_path,
        'quiet': False,
        'no_warnings': True,
        'socket_timeout': 20,
        'retries': 2,
        'fragment_retries': 2,
        'skip_download': False
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            
        if os.path.exists(output_path):
            print(f"Successfully downloaded to {output_path}")
            return output_path
        else:
            return None
    except Exception as e:
        print(f"Error downloading video: {e}")
        return None

def download_from_url(url: str, output_path: str) -> str:
    print("Got direct MP4 URL from RapidAPI, downloading...")
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    try:
        video_data = requests.get(url, stream=True, headers=headers, timeout=15)
        video_data.raise_for_status()
        
        # Check size to prevent downloading massive infinite streams
        content_length = int(video_data.headers.get('content-length', 0))
        if content_length > 150 * 1024 * 1024:  # 150 MB limit
            print(f"File too large: {content_length} bytes. Skipping.")
            return None
            
        with open(output_path, 'wb') as f:
            for chunk in video_data.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return output_path
    except Exception as e:
        print(f"RapidAPI stream failed: {e}")
        raise e
