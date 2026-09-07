import os
import re
import subprocess
from typing import Dict, List, Optional
import yt_dlp

ASSETS_FOLEY_DIR = os.path.abspath("data/assets/foley")
ASSETS_MUSIC_DIR = os.path.abspath("data/assets/music")

# Built-in sound aliases for fuzzy matching
SOUND_ALIASES = {
    "knife": "knife_chop.mp3",
    "chop": "knife_chop.mp3",
    "slice": "knife_chop.mp3",
    "cutting": "knife_chop.mp3",
    "whisk": "knife_chop.mp3",
    "whisking": "knife_chop.mp3",
    "sizzle": "sizzle.mp3",
    "fry": "sizzle.mp3",
    "boil": "sizzle.mp3",
    "crunch": "crunch.mp3",
    "bite": "crunch.mp3",
    "chew": "crunch.mp3",
    "eat": "crunch.mp3",
    "meow": "meow.mp3",
    "cat": "meow.mp3",
    "kitten": "meow.mp3",
    "purr": "meow.mp3",
    "ding": "ding.mp3",
    "bell": "ding.mp3",
    "chime": "ding.mp3",
    "tada": "ding.mp3",
    "whoosh": "whoosh.mp3",
    "swoosh": "whoosh.mp3",
    "swing": "whoosh.mp3",
    "punch": "whoosh.mp3",
    "slide": "whoosh.mp3",
    "slip": "whoosh.mp3",
    "spin": "whoosh.mp3",
    "speed": "whoosh.mp3",
    "run": "whoosh.mp3",
    "bonk": "bonk.mp3",
    "thud": "bonk.mp3",
    "hit": "bonk.mp3",
    "slap": "bonk.mp3",
    "splat": "bonk.mp3",
    "smack": "bonk.mp3",
    "fall": "bonk.mp3",
    "fail": "bonk.mp3",
    "crash": "bonk.mp3",
    "quack": "quack.mp3",
    "duck": "quack.mp3",
    "goose": "quack.mp3",
    "bark": "bark.mp3",
    "dog": "bark.mp3",
    "puppy": "bark.mp3",
    "woof": "bark.mp3",
    "boing": "boing.mp3",
    "spring": "boing.mp3",
    "bounce": "boing.mp3",
    "jump": "boing.mp3",
    "squeak": "boing.mp3",
    "horn": "car_horn.mp3",
    "honk": "car_horn.mp3",
    "car": "car_horn.mp3",
    "beep": "car_horn.mp3",
    "drive": "tire_screech.mp3",
    "skid": "tire_screech.mp3",
    "tire": "tire_screech.mp3",
    "screech": "tire_screech.mp3",
    "drift": "tire_screech.mp3",
    "click": "mechanical_click.mp3",
    "button": "mechanical_click.mp3",
    "switch": "mechanical_click.mp3",
    "press": "mechanical_click.mp3",
    "mechanical_click": "mechanical_click.mp3",
    "clatter": "clatter_thump.mp3",
    "chaos": "clatter_thump.mp3",
    "pots": "clatter_thump.mp3",
    "pans": "clatter_thump.mp3",
    "tumble": "clatter_thump.mp3",
    "clatter_thump": "clatter_thump.mp3",
    "hum": "rising_hum.mp3",
    "levitate": "rising_hum.mp3",
    "glow": "rising_hum.mp3",
    "rising_hum": "rising_hum.mp3",
    "gold": "ding_high_confirm.mp3",
    "triumph": "ding_high_confirm.mp3",
    "confirm": "ding_high_confirm.mp3",
    "ding_high_confirm": "ding_high_confirm.mp3",
    "whoosh_fast": "whoosh.mp3",
    "whoosh_high": "whoosh.mp3",
    "object_drop": "bonk.mp3",
    "drop": "bonk.mp3",
    "clatter_multi": "clatter_thump.mp3",
    "crash_multi": "clatter_thump.mp3",
    "slide_whistle_down": "slide_whistle_down.mp3",
    "whistle": "slide_whistle_down.mp3",
    "sizzle_loud": "sizzle.mp3",
    "snap": "bonk.mp3",
    "rev": "whoosh.mp3",
    "engine": "whoosh.mp3",
    "stomp": "bonk.mp3",
    "earthquake": "clatter_thump.mp3",
    "rumble": "clatter_thump.mp3",
    "splatter": "bonk.mp3",
    "catch": "whoosh.mp3",
    "land": "bonk.mp3",
    "chomp": "crunch.mp3",
    "munch": "crunch.mp3",
    "gasp": "whoosh.mp3",
    "pop": "boing.mp3",
    "ollie": "whoosh.mp3",
}

def generate_synthetic_fallback(out_path: str, duration: float = 1.5, freq: int = 500) -> str:
    """Generates an emergency clean sound tone if no audio assets exist."""
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"sine=frequency={freq}:duration={duration}",
        "-c:a", "libmp3lame", out_path
    ], capture_output=True, check=True)
    return out_path

def resolve_foley_sound(action_type: str) -> str:
    """
    Finds matching sound file in local assets bank or auto-fetches
    clean royalty-free SFX via yt-dlp if novel sound is requested.
    """
    os.makedirs(ASSETS_FOLEY_DIR, exist_ok=True)
    clean_key = re.sub(r'[^a-zA-Z0-9]', '', action_type.lower())

    # 1. Exact or alias match
    for k, filename in SOUND_ALIASES.items():
        if k in clean_key or clean_key in k:
            fpath = os.path.join(ASSETS_FOLEY_DIR, filename)
            if os.path.exists(fpath):
                return fpath

    # 2. Check if file with this name exists in foley dir
    direct_path = os.path.join(ASSETS_FOLEY_DIR, f"{clean_key}.mp3")
    if os.path.exists(direct_path):
        return direct_path

    # 3. Dynamic Auto-Fetch (works locally, may be blocked on datacenter cloud IPs)
    print(f"[AUDIO DIRECTOR] Novel sound effect requested: '{action_type}'. Checking sound bank...")
    try:
        out_tmpl = os.path.join(ASSETS_FOLEY_DIR, f"{clean_key}.%(ext)s")
        search_q = f"ytsearch1:{action_type} sound effect clean short"
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': out_tmpl,
            'quiet': True,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([search_q])
        if os.path.exists(direct_path):
            return direct_path
    except Exception as e:
        print(f"[AUDIO DIRECTOR] Online fetch unavailable ({e}). Using verified bank sound.")

    # 4. Bulletproof Fallback: search for any existing mp3 in foley bank
    for pref in ["bonk.mp3", "ding.mp3", "whoosh.mp3", "boing.mp3"]:
        f_cand = os.path.join(ASSETS_FOLEY_DIR, pref)
        if os.path.exists(f_cand):
            return f_cand

    # Any mp3 in folder
    all_foley = [os.path.join(ASSETS_FOLEY_DIR, f) for f in os.listdir(ASSETS_FOLEY_DIR) if f.endswith(".mp3")]
    if all_foley:
        return all_foley[0]

    # Ultimate synthetic fallback (guaranteed to exist)
    synth_path = os.path.join(ASSETS_FOLEY_DIR, "synth_pop.mp3")
    if not os.path.exists(synth_path):
        generate_synthetic_fallback(synth_path, duration=0.8, freq=600)
    return synth_path

def resolve_music_track(vibe: str) -> str:
    """
    Finds or defaults background comedy / cartoon music track with guaranteed existence.
    """
    os.makedirs(ASSETS_MUSIC_DIR, exist_ok=True)
    default_music = os.path.join(ASSETS_MUSIC_DIR, "bouncy_comedy.mp3")
    if os.path.exists(default_music):
        return default_music

    # Check for any other mp3 in music dir
    all_music = [os.path.join(ASSETS_MUSIC_DIR, f) for f in os.listdir(ASSETS_MUSIC_DIR) if f.endswith(".mp3")]
    if all_music:
        return all_music[0]

    # Check data/temp
    temp_music = "data/temp/cartoon_music.mp3"
    if os.path.exists(temp_music):
        return os.path.abspath(temp_music)

    # Emergency synthetic background rhythm (guaranteed to never fail ffmpeg)
    synth_music = os.path.join(ASSETS_MUSIC_DIR, "synth_bgm.mp3")
    if not os.path.exists(synth_music):
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", "anoisesrc=d=12:c=pink:r=48000:a=0.05",
            "-c:a", "libmp3lame", synth_music
        ], capture_output=True, check=True)
    return synth_music

def build_scene_audio_timeline(story: Dict, total_duration: float = 8.6, output_wav: str = "data/temp/master_studio_audio.wav") -> str:
    """
    Dynamically analyzes ANY story generated by the AI:
    - Identifies each scene's timing and required Foley action.
    - Resolves high-fidelity audio assets.
    - Assembles precise millisecond delay offsets in FFmpeg filter_complex.
    - Ducks background music under the Foley punches.
    """
    scenes = story.get("scenes", [])
    audio_cfg = story.get("audio_config", {})
    music_vibe = audio_cfg.get("bgm_style", story.get("music_vibe", "bouncy_comedy"))
    bgm_vol = audio_cfg.get("bgm_base_volume", 0.75)
    target_lufs = audio_cfg.get("target_loudnorm_lufs", -14.0)

    bgm_path = resolve_music_track(music_vibe)

    inputs = ["-i", bgm_path]
    filter_parts = []
    mix_inputs = ["[bgm]"]
    # Background music energetic bed (full energy, continuous comedy rhythm)
    filter_parts.append(f"[0:a]volume={bgm_vol},atrim=0:{total_duration},asetpts=PTS-STARTPTS[bgm]")
    input_idx = 1

    # Filter and curate cues: MAX 3 cues for the ENTIRE video, minimum 3.0s apart, no random animal noises
    character_name = (story.get("character_name") or story.get("protagonist", {}).get("name", "")).lower()
    banned_animal_sfx = set()
    if "cat" not in character_name:
        banned_animal_sfx.add("meow")
    if "dog" not in character_name and "puppy" not in character_name:
        banned_animal_sfx.add("bark")
    if "duck" not in character_name:
        banned_animal_sfx.add("quack")

    collected_cues = []
    has_scene_foley_cues = any(bool(sc.get("foley_cues")) for sc in scenes)
    if has_scene_foley_cues:
        current_time = 0.0
        for sc in scenes:
            scene_dur = float(sc.get("duration_sec", 2.5))
            for cue in sc.get("foley_cues", []):
                sound_name = cue.get("sfx", "").lower()
                if sound_name in banned_animal_sfx or not sound_name:
                    continue
                rel_t = float(cue.get("timestamp_sec", 0.0))
                abs_t = current_time + rel_t
                vol = min(float(cue.get("volume", 1.2)), 1.3)  # Cap volume to prevent distortion
                dur = min(float(cue.get("duration", 1.2)), 1.5)
                collected_cues.append({
                    "sfx": sound_name,
                    "time": abs_t,
                    "vol": vol,
                    "dur": dur
                })
            current_time += scene_dur

    # Enforce strict pacing: MAX 3 cues total, separated by at least 2.5 seconds
    selected_cues = []
    last_time = -999.0
    for c in collected_cues:
        if len(selected_cues) >= 3:
            break
        if c["time"] - last_time >= 2.5 and c["time"] < (total_duration - 0.5):
            selected_cues.append(c)
            last_time = c["time"]

    print(f"[AUDIO DIRECTOR] Selected {len(selected_cues)} clean narrative Foley cues (curated from {len(collected_cues)} raw cues)")
    for sc_cue in selected_cues:
        sound_name = sc_cue["sfx"]
        sfx_path = resolve_foley_sound(sound_name)
        inputs.extend(["-i", sfx_path])
        delay_ms = int(sc_cue["time"] * 1000)
        vol = sc_cue["vol"]
        dur = sc_cue["dur"]
        label = f"cue{input_idx}"
        filter_parts.append(
            f"[{input_idx}:a]volume={vol},atrim=0:{dur},asetpts=PTS-STARTPTS,adelay={delay_ms}|{delay_ms}[{label}]"
        )
        mix_inputs.append(f"[{label}]")
        input_idx += 1
    else:
        # Default scene timing partitions aligned to the Conflict Arc action climax
        default_offsets = [1.2, 4.0, 6.8]

        for i, sc in enumerate(scenes[:3]):
            sound_type = sc.get("foley_sound_type", "bonk")
            sfx_path = resolve_foley_sound(sound_type)
            inputs.extend(["-i", sfx_path])

            offset_sec = sc.get("impact_offset", default_offsets[i])
            delay_ms = int(offset_sec * 1000)
            dur = 2.4 if i < 2 else 2.6
            label = f"sfx{i+1}"
            filter_parts.append(
                f"[{input_idx}:a]volume=2.0,atrim=0:{dur},asetpts=PTS-STARTPTS,adelay={delay_ms}|{delay_ms}[{label}]"
            )
            mix_inputs.append(f"[{label}]")
            input_idx += 1

            # If scene 3 has an ending punchline/ding, add finishing flourish
            if i == 2:
                ding_path = resolve_foley_sound("ding")
                inputs.extend(["-i", ding_path])
                ding_delay = int((total_duration - 0.8) * 1000)
                filter_parts.append(
                    f"[{input_idx}:a]volume=2.2,atrim=0:1.5,asetpts=PTS-STARTPTS,adelay={ding_delay}|{ding_delay}[ding_finish]"
                )
                mix_inputs.append("[ding_finish]")
                input_idx += 1

    # Final amix with normalize=0 (prevents volume crush) + loudnorm target
    amix_str = (
        "".join(mix_inputs)
        + f"amix=inputs={len(mix_inputs)}:duration=first:dropout_transition=0:normalize=0,"
        + f"loudnorm=I={target_lufs}:TP=-1.5:LRA=7[aout]"
    )
    filter_parts.append(amix_str)

    full_filter = ";".join(filter_parts)

    os.makedirs(os.path.dirname(output_wav), exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", full_filter,
        "-map", "[aout]",
        "-c:a", "pcm_s16le",
        "-ar", "48000",
        "-t", str(total_duration),
        output_wav
    ]

    print(f"[AUDIO DIRECTOR] Mixing dynamic Foley audio track for story: '{story.get('title')}'...")
    subprocess.run(cmd, check=True)
    print(f"[AUDIO DIRECTOR] Dynamic Foley audio rendered successfully: {output_wav}")
    return output_wav
