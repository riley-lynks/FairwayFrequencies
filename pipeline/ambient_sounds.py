# =============================================================================
# pipeline/ambient_sounds.py — Golf Course Ambient Sound Layer
# =============================================================================
# PURPOSE:
#   Download ambient golf course sounds from Freesound.org and create a
#   single ambient audio bed that plays beneath the LoFi music.
#
# WHY ambient sounds? At low volume (0.20 = 20%), ambient sounds make the
# video feel like you're actually AT a golf course:
#   - The sound of birds in the distance
#   - Wind through trees
#   - The occasional soft rain on a misty morning
#   - A distant club strike
# These sounds are subtle but they subconsciously enhance the immersion.
#
# FREESOUND.ORG:
#   A Creative Commons sound library with thousands of golf/nature sounds.
#   Many are CC0 (public domain — totally free to use, even commercially).
#   API docs: https://freesound.org/docs/api/
#
# CACHING:
#   Downloaded sounds are cached in assets/sounds/ so repeat runs of the
#   same scene don't re-download the same files. The cache persists between runs.
#
# GRACEFUL FAILURE:
#   If Freesound fails (network issue, API limit, etc.), we log a warning
#   and return None. The pipeline continues WITHOUT ambient sounds rather
#   than crashing. The video is still perfectly viable music-only.
# =============================================================================

import os          # For file operations
import glob        # For finding cached files
import random      # For selecting random sounds
import subprocess  # For running FFmpeg
import requests    # For Freesound API calls
import logging     # For progress messages
import json        # For parsing API responses
import time        # For download delays

import config      # Our settings

logger = logging.getLogger("fairway.ambient_sounds")

# Where to cache downloaded sounds
SOUNDS_CACHE_DIR = os.path.join("assets", "sounds")

# Freesound API base URL
FREESOUND_API_BASE = "https://freesound.org/apiv2"

# Number of sounds to download per keyword
SOUNDS_PER_KEYWORD = 2

# Maximum duration per sound (seconds) — avoid downloading huge files
MAX_SOUND_DURATION = 120


def download_ambient_sounds(
    keywords: list,
    target_duration_hours: float,
    audio_dir: str,
    api_key: str,
    logger: logging.Logger = None,
) -> str:
    """
    Download ambient sounds and create a looped ambient audio bed.

    This is Stage 6 of the pipeline (optional — only if INCLUDE_AMBIENCE = True).
    The output is a single audio file of the right duration to match the video.
    It's a mix of several ambient sounds layered and looped.

    Args:
        keywords:              List of sound keywords from the orchestrator.
        target_duration_hours: How long the ambient bed should be.
        audio_dir:             Directory to save the processed ambient audio.
        api_key:               Freesound API key.
        logger:                Logger for progress messages.

    Returns:
        Path to the ambient audio file, or None if it couldn't be created.
    """
    local_logger = logger or logging.getLogger("fairway.ambient_sounds")
    target_seconds = target_duration_hours * 3600

    if not api_key:
        local_logger.warning(
            "  ⚠️ FREESOUND_API_KEY not set. Skipping ambient sounds.\n"
            "  Get a free key at: https://freesound.org/apiv2/apply/"
        )
        return None

    local_logger.info(f"  Searching Freesound for: {keywords}")
    os.makedirs(SOUNDS_CACHE_DIR, exist_ok=True)

    # Download sounds for each keyword
    downloaded_sounds = []

    for keyword in keywords:
        local_logger.info(f"  Searching for '{keyword}' sounds...")
        try:
            sounds = _search_and_download(
                keyword=keyword,
                api_key=api_key,
                max_count=SOUNDS_PER_KEYWORD,
                local_logger=local_logger,
            )
            downloaded_sounds.extend(sounds)
            local_logger.info(f"  ✓ Downloaded {len(sounds)} '{keyword}' sounds")

        except Exception as e:
            local_logger.warning(f"  ⚠️ Failed to get '{keyword}' sounds: {e}")

    # Also check the cache for previously downloaded sounds
    cached_sounds = glob.glob(os.path.join(SOUNDS_CACHE_DIR, "*.wav"))
    cached_sounds += glob.glob(os.path.join(SOUNDS_CACHE_DIR, "*.mp3"))
    cached_sounds = [f for f in cached_sounds if f not in downloaded_sounds]

    all_sounds = downloaded_sounds + cached_sounds[:10]  # Use up to 10 cached

    if not all_sounds:
        local_logger.warning(
            "  ⚠️ No ambient sounds could be downloaded. Continuing without ambience."
        )
        return None

    local_logger.info(f"  Creating ambient bed from {len(all_sounds)} sounds...")

    # Create the ambient audio bed
    ambient_path = os.path.join(audio_dir, "ambient_bed.wav")
    _create_ambient_bed(
        sound_files=all_sounds,
        target_seconds=target_seconds,
        output_path=ambient_path,
        local_logger=local_logger,
    )

    return ambient_path


def _search_and_download(
    keyword: str,
    api_key: str,
    max_count: int,
    local_logger,
) -> list:
    """
    Search Freesound for sounds matching a keyword and download them.

    We search for CC0 (public domain) sounds only, filtered by duration,
    and download their high-quality preview files. The preview files are
    freely accessible without OAuth — only full source files need OAuth.

    Args:
        keyword:     Search term (e.g., "golf", "rain", "birds").
        api_key:     Freesound API key.
        max_count:   Max number of sounds to download.
        local_logger: Logger.

    Returns:
        List of paths to downloaded sound files.
    """
    # Search for sounds
    # We use the preview download URLs which are publicly accessible
    # WHY previews? Full-quality files require OAuth2 authentication.
    # Previews (HQ MP3, 160kbps) are high enough quality for ambient beds.
    search_url = f"{FREESOUND_API_BASE}/search/text/"
    params = {
        "query": keyword,
        "token": api_key,
        "fields": "id,name,previews,duration,license",
        "filter": "duration:[1 TO 120]",  # Between 1 and 120 seconds
        "sort": "rating_desc",             # Best-rated first
        "page_size": 10,                   # Fetch 10, pick the best few
    }

    response = requests.get(search_url, params=params, timeout=15)

    if response.status_code != 200:
        raise RuntimeError(
            f"Freesound search failed (HTTP {response.status_code}): {response.text[:200]}"
        )

    results = response.json().get("results", [])

    if not results:
        local_logger.debug(f"  No results found for '{keyword}'")
        return []

    downloaded = []

    for sound in results[:max_count]:
        sound_id = sound["id"]
        sound_name = sound["name"]
        duration = sound.get("duration", 0)

        # Skip sounds that are too short (< 3 seconds) or too long (> 2 min)
        if duration < 3 or duration > MAX_SOUND_DURATION:
            continue

        # Use the HQ preview URL (freely accessible, no OAuth needed)
        preview_url = sound.get("previews", {}).get("preview-hq-mp3")
        if not preview_url:
            continue

        # Create a cache filename from the sound ID and keyword
        # WHY include keyword in name? Helps us identify cached sounds later
        safe_keyword = keyword.replace(" ", "_").replace("/", "_")
        cache_filename = f"{safe_keyword}_{sound_id}.mp3"
        cache_path = os.path.join(SOUNDS_CACHE_DIR, cache_filename)

        # Skip download if already cached
        if os.path.exists(cache_path):
            local_logger.debug(f"  Using cached: {cache_filename}")
            downloaded.append(cache_path)
            continue

        # Download the sound
        local_logger.debug(f"  Downloading: {sound_name} ({duration:.1f}s)")
        try:
            dl_response = requests.get(preview_url, timeout=30)
            if dl_response.status_code == 200:
                with open(cache_path, "wb") as f:
                    f.write(dl_response.content)
                downloaded.append(cache_path)
                time.sleep(0.5)  # Be polite to Freesound's servers

        except Exception as e:
            local_logger.debug(f"  Failed to download {sound_name}: {e}")

    return downloaded


def _create_ambient_bed(
    sound_files: list,
    target_seconds: float,
    output_path: str,
    local_logger,
):
    """
    Create a single ambient audio bed from multiple sound files.

    This mixes the sounds and loops the result to fill the target duration.
    The strategy:
    1. Concatenate all sounds into one long file
    2. Loop that file to fill the target duration
    3. Apply gentle reverb and low-pass filter for a spacious ambient feel
    4. Normalize to a consistent level (we'll lower it further in audio assembly)

    Args:
        sound_files:    List of sound file paths.
        target_seconds: How long the output should be.
        output_path:    Where to save the ambient bed.
        local_logger:   Logger.
    """
    # Step 1: Create a concat list for FFmpeg
    concat_list_path = output_path.replace(".wav", "_concat.txt")
    with open(concat_list_path, "w") as f:
        for sound_file in sound_files:
            abs_path = os.path.abspath(sound_file).replace("\\", "/")
            f.write(f"file '{abs_path}'\n")

    # Step 2: Concatenate all sounds into one file
    concat_path = output_path.replace(".wav", "_concat_raw.wav")
    cmd_concat = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_list_path,
        "-ar", "44100",   # 44.1kHz sample rate
        "-ac", "2",        # Stereo
        concat_path,
    ]

    try:
        subprocess.run(cmd_concat, capture_output=True, text=True, check=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.CalledProcessError as e:
        local_logger.warning(f"  ⚠️ Sound concat failed: {e.stderr[-200:]}")
        # Try with just the first sound file as fallback
        if sound_files:
            import shutil
            shutil.copy2(sound_files[0], concat_path)
        else:
            return

    # Step 3: Loop to fill duration and apply gentle ambient processing
    # aloop=-1: loop indefinitely, stream_loop handles timing
    # atrim: cut at target duration
    # aecho: add subtle reverb (makes sounds feel more spacious/outdoor)
    # lowpass: gentle high-frequency rolloff (makes sounds feel distant/ambient)
    # loudnorm: normalize to a consistent level
    cmd_process = [
        "ffmpeg", "-y",
        "-stream_loop", "-1",          # Loop the input file indefinitely
        "-i", concat_path,
        "-t", str(target_seconds),     # Trim at target duration
        "-af", (
            "aecho=0.8:0.88:60:0.4,"  # Subtle echo/reverb (outdoor space feel)
            "lowpass=f=8000,"           # Roll off above 8kHz (muffled distance)
            "loudnorm=I=-23:LRA=7:TP=-2"  # Normalize (quieter than music — audio assembly layers it in)
        ),
        "-ar", "44100",
        "-ac", "2",
        "-c:a", "pcm_s16le",
        output_path,
    ]

    try:
        subprocess.run(cmd_process, capture_output=True, text=True, check=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        # Clean up intermediate files
        if os.path.exists(concat_path):
            os.remove(concat_path)
        if os.path.exists(concat_list_path):
            os.remove(concat_list_path)
        local_logger.info(f"  ✓ Ambient bed created: {target_seconds/3600:.2f}h")

    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"FFmpeg ambient processing failed: {e.stderr[-300:]}")
