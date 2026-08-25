import os
import time
from google import genai
from google.genai import types

def analyze_video_and_generate_script(video_path: str, is_short: bool = False, profile: dict = None) -> dict:
    """
    Uploads a video to Gemini and generates a highly viral title and reaction script,
    dynamically incorporating adaptive anti-gravity directives from the feedback loop.
    """
    print(f"Uploading {video_path} to Gemini Vision...")
    
    # 1. Multi-Key Fallback Array
    api_keys = [
        os.environ.get("GEMINI_API_KEY"),
        os.environ.get("GEMINI_API_KEY_2"),
        os.environ.get("GEMINI_API_KEY_3"),
        os.environ.get("GEMINI_API_KEY_4")
    ]
    api_keys = [k for k in api_keys if k and str(k).strip() != "None"]
    
    fallback = {
        "title": "You won't believe how this ends! 😂 #shorts #viral",
        "meme_caption": "Bro thought he had it 😂💀",
        "description": "Watch till the very end for the best moment!"
    }
    
    if not api_keys:
        print("No Gemini API keys found.")
        return fallback
        
    short_constraint = ""
    if is_short:
        short_constraint = "CRITICAL: Because this is a Short/Reel, people spend very little time watching. The video MUST be incredibly attention-grabbing, shocking, extremely funny, or deeply romantic within the FIRST 3 SECONDS. If the video has a slow build-up, is boring, or takes too long to get to the point, you MUST output ONLY the word: REJECT."
        
    islamic_constraint = """
    CRITICAL ISLAMIC LAW RULE FOR ROMANTIC VIDEOS: 
    If you detect that this is a "romantic" video, it MUST strictly feature an Islamic couple (husband and wife).
    The woman MUST be wearing a hijab, niqab, or burqa (observing purdah). If the woman's hair, neck, or any immodest amount of skin is showing, or if the couple does not look like a traditional Muslim husband and wife, you MUST output ONLY the word: REJECT
    There are NO exceptions to this rule. Reject any Western or non-Islamic romance videos instantly.
    """

    # Extract dynamic profile directives from feedback loop (RLAF)
    dynamic_directives = ""
    if profile:
        # Check for RLAF format or legacy format
        eval_meta = profile.get("agent_evaluation", {})
        v_gate = profile.get("phase_4_vision_gate_directives", {})
        c_gate = profile.get("phase_6_copywriting_directives", {})
        
        n_rules = eval_meta.get("emergent_n_rules", [])
        custom_rules = v_gate.get("custom_evaluation_rules", [])
        winning_hooks = v_gate.get("mandatory_visual_hooks") or profile.get("winning_visual_hooks", [])
        banned_topics = v_gate.get("instant_reject_triggers") or profile.get("underperforming_elements_to_ban", [])
        title_archetypes = c_gate.get("title_formulas") or profile.get("high_converting_title_templates", [])
        
        n_rules_str = "\n        ".join([f"- {r}" for r in n_rules]) if n_rules else "- Maximize 3-second viewer retention"
        custom_rules_str = "\n        ".join([f"- {c}" for c in custom_rules]) if custom_rules else "- Discard low visual contrast clips"
        
        dynamic_directives = f"""
        AUTONOMOUS AGENT REINFORCEMENT LEARNING DIRECTIVES & N-RULES:
        {n_rules_str}
        
        VISION GATE CRITERIA:
        - Mandatory Visual Hooks to Prioritize: {', '.join(winning_hooks) if isinstance(winning_hooks, list) else winning_hooks}
        - Instant Reject Triggers (Penalty Traps): {', '.join(banned_topics) if isinstance(banned_topics, list) else banned_topics}
        - Custom Quality Rules:
        {custom_rules_str}
        - High-Performing Title Formulas: {', '.join(title_archetypes) if isinstance(title_archetypes, list) else title_archetypes}
        """
    
    prompt = f"""
    You are an AI analyzing a viral video clip for YouTube Shorts and Facebook Reels.
    Your first job is SAFETY and HIGH AUDIENCE RETENTION.
    Watch the video and listen to the audio.
    
    {dynamic_directives}
    
    REJECTION CRITERIA:
    1. If the video makes fun of disabled people, contains violence, tragedy, hate speech, or offensive/NSFW content, output ONLY: REJECT
    2. If the video is a stand-up comedy routine on a stage, output ONLY: REJECT
    3. If the video is completely boring, slow-paced, static, or uninteresting, output ONLY: REJECT
    {short_constraint}
    {islamic_constraint}
    
    If the video meets safety and engagement standards, generate:
    1. A highly engaging, clickable YouTube Shorts title that summarizes what happens in the video (include relevant emojis and #shorts #viral, under 80 chars).
    2. A funny short meme reaction text matching this video (under 8 words, e.g., "Bro thought he was slick 💀", "Wait till you see what happens 😂", "Instant regret level 100 😭").
    3. A brief 2-sentence engaging description describing why this moment is so funny/entertaining.
    4. Exact float timestamps in seconds for the peak action window:
       - HOOK_START: Timestamp in seconds where the immediate hook/action begins (e.g., 0.0 or 1.5)
       - HOOK_END: Timestamp in seconds right after the punchline/twist ends (e.g., 14.5 or 18.0)
    
    Format your response EXACTLY like this:
    TITLE: <your viral title here>
    MEME_CAPTION: <short funny meme caption here>
    DESCRIPTION: <brief 2-sentence engaging description here>
    HOOK_START: <float timestamp>
    HOOK_END: <float timestamp>
    """
    
    # Robust fallback chain covering all possible model strings
    model_names = [
        "gemini-3.7-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite"
    ]
    
    response = None
    uploaded_file = None
    client = None
    
    for model in model_names:
        success = False
        for api_key in api_keys:
            try:
                # Initialize client with current key
                client = genai.Client(api_key=api_key)
                
                # We need to upload the file once per successful client initialization
                if not uploaded_file:
                    uploaded_file = client.files.upload(file=video_path)
                    
                    while str(uploaded_file.state).endswith("PROCESSING") or (hasattr(uploaded_file.state, 'name') and uploaded_file.state.name == "PROCESSING"):
                        print(".", end="", flush=True)
                        time.sleep(2)
                        uploaded_file = client.files.get(name=uploaded_file.name)
                    
                    if str(uploaded_file.state).endswith("FAILED") or (hasattr(uploaded_file.state, 'name') and uploaded_file.state.name == "FAILED"):
                        print("\nGemini video processing failed.")
                        return fallback
                
                print(f"\nAttempting generation with {model} on key ending in ...{api_key[-4:]}")
                response = client.models.generate_content(
                    model=model,
                    contents=[uploaded_file, prompt]
                )
                success = True
                break # Successfully generated, break out of key loop
            except Exception as e:
                print(f"Model {model} with key ...{api_key[-4:]} failed ({e}). Trying next key...")
                continue
                
        if success:
            break # Successfully generated, break out of model loop
            
    if not response:
        print("All Gemini models and keys failed.")
        return fallback
        
    raw_text = response.text.strip()
    print(f"Gemini Raw Output:\n{raw_text}")
    
    if "REJECT" in raw_text.upper() and not "TITLE:" in raw_text.upper():
        print("Gemini rejected this video for safety/appropriateness.")
        return {"rejected": True}
    
    title = fallback["title"]
    meme_caption = "Bro thought he had it 😂💀"
    description = ""
    hook_start = 0.0
    hook_end = None
    
    for line in raw_text.split('\n'):
        line = line.strip()
        if line.startswith('TITLE:'):
            title = line.replace('TITLE:', '').strip()
        elif line.startswith('MEME_CAPTION:'):
            meme_caption = line.replace('MEME_CAPTION:', '').strip()
        elif line.startswith('DESCRIPTION:'):
            description = line.replace('DESCRIPTION:', '').strip()
        elif line.startswith('HOOK_START:'):
            try:
                hook_start = max(0.0, float(line.replace('HOOK_START:', '').strip()))
            except Exception:
                hook_start = 0.0
        elif line.startswith('HOOK_END:'):
            try:
                val = float(line.replace('HOOK_END:', '').strip())
                if val > hook_start + 2.0:
                    hook_end = val
            except Exception:
                hook_end = None
            
    # Cleanup file from Gemini
    try:
        if uploaded_file and client:
            client.files.delete(name=uploaded_file.name)
    except Exception as e:
        print(f"Failed to delete file from Gemini: {e}")
    
    return {
        "title": title,
        "meme_caption": meme_caption,
        "description": description,
        "hook_start": hook_start,
        "hook_end": hook_end,
        "rejected": False
    }

def generate_compilation_details(clip_titles: list, mood: str = "funny", profile: dict = None) -> tuple[str, str]:
    """
    Takes a list of individual clip titles and asks Gemini to generate one overarching, 
    highly clickable viral title and a detailed description for the compilation video.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    fallback_title = "EPIC FAILS 🚨 You Will Laugh So Hard 😂 #funny #compilation"
    fallback_desc = "In today's compilation, we've gathered the most hilarious and relatable viral moments! Which clip was your favorite? Let us know in the comments below! 👇"
    
    if not api_key or not clip_titles:
        return fallback_title, fallback_desc
        
    try:
        client = genai.Client(api_key=api_key)
        
        style_guide = ""
        if profile:
            c_gate = profile.get("phase_6_copywriting_directives", {})
            cta_sample = c_gate.get("comment_cta") or profile.get("high_engagement_cta", "")
            title_archetypes = c_gate.get("title_formulas") or profile.get("high_converting_title_templates", [])
            style_guide = f"""
            REINFORCEMENT LEARNING DIRECTIVES:
            - Preferred Title Formulas: {', '.join(title_archetypes) if isinstance(title_archetypes, list) else title_archetypes}
            - High-Reward Comment CTA: {cta_sample}
            """
            
        prompt = f"""
        You are a master YouTube strategist. I am uploading a {mood} compilation video.
        The video contains clips with these themes/events:
        {', '.join(clip_titles)}
        
        {style_guide}
        
        Generate:
        1. Exactly ONE highly clickable, viral YouTube title that summarizes the compilation (Include relevant emojis and #funny #viral #compilation, keep under 80 characters).
        2. A compelling 3-sentence YouTube description inviting viewers to comment on their favorite clip.
        
        Format your response EXACTLY like this:
        TITLE: <viral title here>
        DESCRIPTION: <compelling description here>
        """
        
        model_names = [
            "gemini-3.7-flash",
            "gemini-3.6-flash",
            "gemini-3.5-flash",
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite",
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite"
        ]
        
        response = None
        for model in model_names:
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt
                )
                break
            except Exception:
                continue

        if not response:
            return fallback_title, fallback_desc
            
        title = fallback_title
        desc = fallback_desc
        for line in response.text.strip().split('\n'):
            line = line.strip()
            if line.startswith('TITLE:'):
                title = line.replace('TITLE:', '').strip().replace('"', '')
            elif line.startswith('DESCRIPTION:'):
                desc = line.replace('DESCRIPTION:', '').strip()
                
        print(f"Dynamically Generated Compilation Title: {title}")
        return title, desc
    except Exception as e:
        print(f"Error generating compilation details: {e}")
        return fallback_title, fallback_desc

def generate_compilation_title(clip_titles: list) -> str:
    """Backwards compatible wrapper for compilation title"""
    title, _ = generate_compilation_details(clip_titles)
    return title
