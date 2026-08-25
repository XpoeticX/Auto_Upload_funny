import os
import requests

def upload_to_facebook(video_path: str, title: str, description: str, is_compilation: bool = False, thumbnail_path: str = None):
    fb_token = os.environ.get("FB_ACCESS_TOKEN")
    page_id = os.environ.get("FB_PAGE_ID")
    
    if not fb_token or not page_id:
        print("Facebook credentials missing.")
        return False
        
    print(f"Uploading {video_path} to Facebook...")
    
    try:
        # Use standard video API for compilations, Reels API for shorts
        if is_compilation:
            init_url = f"https://graph.facebook.com/v19.0/{page_id}/videos"
            
            # 1. Start Phase
            init_payload = {
                'upload_phase': 'start',
                'file_size': os.path.getsize(video_path),
                'access_token': fb_token
            }
            init_res = requests.post(init_url, data=init_payload).json()
            if 'error' in init_res:
                print(f"Facebook Init Error: {init_res}")
                return False
                
            video_id = init_res.get('video_id')
            upload_session_id = init_res.get('upload_session_id')
            
            # 2. Transfer Phase (Chunked Upload)
            with open(video_path, 'rb') as f:
                start_offset = 0
                chunk_size = 5 * 1024 * 1024 # 5MB chunks
                
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                        
                    transfer_payload = {
                        'upload_phase': 'transfer',
                        'upload_session_id': upload_session_id,
                        'access_token': fb_token,
                        'start_offset': str(start_offset)
                    }
                    
                    files = {'video_file_chunk': chunk}
                    transfer_res = requests.post(init_url, data=transfer_payload, files=files)
                    
                    try:
                        transfer_json = transfer_res.json()
                        if 'error' in transfer_json:
                            print(f"Facebook Transfer Error: {transfer_json}")
                            return False
                    except Exception:
                        print(f"Facebook Transfer crash. Output: {transfer_res.text}")
                        return False
                        
                    start_offset += len(chunk)
                
            # 3. Finish Phase
            finish_payload = {
                'upload_phase': 'finish',
                'upload_session_id': upload_session_id,
                'access_token': fb_token,
                'title': title,
                'description': description
            }
            
            # For standard videos, Facebook accepts `thumb` as a multipart file in finish phase
            finish_files = {}
            if thumbnail_path and os.path.exists(thumbnail_path):
                finish_files['thumb'] = open(thumbnail_path, 'rb')
                
            finish_res = requests.post(init_url, data=finish_payload, files=finish_files if finish_files else None).json()
            
            if 'thumb' in finish_files:
                finish_files['thumb'].close()
            
            if 'success' in finish_res and finish_res['success']:
                print(f"Facebook Video Upload Successful! ID: {video_id}")
                return video_id
            else:
                print(f"Facebook Publish Error: {finish_res}")
                return False
        else:
            # 1. Initialize Reel Upload
            init_url = f"https://graph.facebook.com/v19.0/{page_id}/video_reels"
            init_payload = {
                'upload_phase': 'start',
                'access_token': fb_token
            }
            init_res = requests.post(init_url, data=init_payload).json()
            
            if 'error' in init_res:
                print(f"Facebook Init Error: {init_res}")
                return False
                
            video_id = init_res.get('video_id')
            upload_url = init_res.get('upload_url')
            
            if not video_id or not upload_url:
                print("Failed to start Facebook upload phase.")
                return False
                
            # 2. Upload file
            headers = {
                'Authorization': f'OAuth {fb_token}',
                'offset': '0',
                'file_size': str(os.path.getsize(video_path))
            }
            
            with open(video_path, 'rb') as f:
                upload_res = requests.post(upload_url, headers=headers, data=f).json()
                
            if 'error' in upload_res:
                print(f"Facebook Transfer Error: {upload_res}")
                return False
                
            # 3. Publish
            publish_payload = {
                'upload_phase': 'finish',
                'video_id': video_id,
                'video_state': 'PUBLISHED',
                'description': description,
                'access_token': fb_token
            }
            
            # The Reels API doesn't formally document thumbnail uploads during finish, 
            # but standard videos do. For safety, we skip thumbnail injection for Reels here 
            # (Reels auto-select frames perfectly).
            
            publish_res = requests.post(init_url, data=publish_payload).json()
            
            if 'success' in publish_res and publish_res['success']:
                print(f"Facebook Reels Upload Successful! ID: {video_id}")
                return video_id
            else:
                print(f"Facebook Publish Error: {publish_res}")
                return False
                
    except Exception as e:
        print(f"Facebook upload exception: {e}")
        return False
