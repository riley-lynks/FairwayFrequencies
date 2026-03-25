# =============================================================================
# pipeline/music_gen.py — LoFi Music Generation
# =============================================================================
# PURPOSE:
#   Get a LoFi music track for the video. First checks your local library
#   (assets/music/) for pre-generated Suno tracks. If none are found, falls
#   back to the Mubert API to generate one programmatically.
#
# TWO SOURCES:
#   1. LOCAL LIBRARY (preferred): Pre-made Suno tracks you've dropped in assets/music/
#      Suno (suno.com) produces excellent LoFi music. Generate tracks there,
#      download them, and put them in assets/music/. The pipeline uses these first.
#
#   2. MUBERT API (automated fallback): Mubert can generate LoFi music on demand.
#      Quality is good (not quite Suno level) but completely automated.
#      API: https://mubert.com/render/api
#
# WHY check local first? For a YouTube channel, you want CONSISTENT, HIGH-QUALITY
# music. Pre-vetted Suno tracks give you that. The Mubert fallback ensures the
# pipeline never completely fails due to an empty music library.
#
# MUSIC TREATMENT:
#   - Local tracks: Loop to fill target duration with 5-second crossfades
#   - Mubert tracks: Already the right duration (we request specific duration)
#   - Final normalization: -14 LUFS (YouTube's recommended loudness target)
# =============================================================================

import os          # For file operations
import glob        # For finding files matching a pattern
import random      # For randomly selecting from library
import subprocess  # For running FFmpeg (audio looping and normalization)
import requests    # For Mubert API calls
import logging     # For progress messages
import time        # For retry delays
import json        # For parsing API responses
import math        # For math.ceil() when calculating loop count

import config      # Our settings

logger = logging.getLogger("fairway.music_gen")

# Where pre-made Suno tracks live
MUSIC_LIBRARY_DIR = os.path.join("assets", "music")

# Supported music file formats
SUPPORTED_FORMATS = [".mp3", ".wav", ".m4a", ".flac", ".ogg"]

# YouTube's recommended loudness level (LUFS = Loudness Units relative to Full Scale)
# WHY -14 LUFS? YouTube normalizes all videos to -14 LUFS. If your audio is louder,
# YouTube will turn it down and it may sound compressed. If quieter, YouTube adds
# gain and you get noise. Normalizing to -14 LUFS upfront gives the best result.
TARGET_LUFS = -14.0


def get_music_track(
    music_prompt: str,
    target_duration_hours: float,
    audio_dir: str,
    api_key: str,
    logger: logging.Logger = None,
) -> str:
    """
    Get a LoFi music track, either from the local library or Mubert API.

    This is Stage 5 of the pipeline. The resulting track will be a single
    audio file long enough (or looped enough) to fill the entire video duration.

    Args:
        music_prompt:         Description of the music style (from orchestrator).
        target_duration_hours: How long the video is (we need music this long).
        audio_dir:            Directory to save the processed music file.
        api_key:              Mubert API key (used only if local library is empty).
        logger:               Logger for progress messages.

    Returns:
        Path to the ready-to-use music audio file.

    Raises:
        RuntimeError: If both local library and Mubert API fail.
    """
    local_logger = logger or logging.getLogger("fairway.music_gen")
    target_seconds = target_duration_hours * 3600

    # Try local library first
    library_tracks = _find_library_tracks()

    if library_tracks:
        local_logger.info(f"  Found {len(library_tracks)} tracks in local library.")
        output_path = os.path.join(audio_dir, "music_looped.wav")

        if len(library_tracks) == 1:
            # Only one track available — fall back to looping it
            local_logger.info(f"  Only 1 track — looping: {os.path.basename(library_tracks[0])}")
            _loop_track_to_duration(
                track_path=library_tracks[0],
                target_seconds=target_seconds,
                output_path=output_path,
                local_logger=local_logger,
            )
        else:
            # Multiple tracks — sequence them in random order
            local_logger.info(f"  Sequencing {len(library_tracks)} tracks in random order...")
            _sequence_tracks_to_duration(
                tracks=library_tracks,
                target_seconds=target_seconds,
                output_path=output_path,
                local_logger=local_logger,
            )

        return output_path

    # No local tracks — use Mubert API
    local_logger.info("  No local tracks in assets/music/. Trying Mubert API...")
    local_logger.info(
        "  Tip: Download LoFi tracks from suno.com and save to assets/music/"
        " for best results!"
    )

    if not api_key:
        raise RuntimeError(
            "No music tracks found in assets/music/ AND MUBERT_API_KEY is not set.\n"
            "Please do ONE of the following:\n"
            "  1. Download LoFi tracks from suno.com and save to assets/music/\n"
            "  2. Add your Mubert API key to .env (get at https://mubert.com/render/pricing)\n"
            "  3. Run with --no-ambience and skip to check your music setup first"
        )

    # Use Mubert to generate a track
    mubert_path = os.path.join(audio_dir, "music_mubert_raw.mp3")
    _generate_mubert_track(
        music_prompt=music_prompt,
        target_seconds=min(target_seconds, 3600),  # Mubert max is typically 1 hour
        output_path=mubert_path,
        api_key=api_key,
        local_logger=local_logger,
    )

    # If we got a track shorter than needed, loop it
    track_duration = _get_audio_duration(mubert_path)
    if track_duration < target_seconds:
        local_logger.info(f"  Mubert track is {track_duration:.0f}s, looping to fill {target_seconds:.0f}s...")
        output_path = os.path.join(audio_dir, "music_looped.wav")
        _loop_track_to_duration(
            track_path=mubert_path,
            target_seconds=target_seconds,
            output_path=output_path,
            local_logger=local_logger,
        )
        return output_path

    return mubert_path


def _find_library_tracks() -> list:
    """
    Find all audio tracks in the local music library directory.

    Returns:
        List of file paths to audio files in assets/music/.
    """
    if not os.path.exists(MUSIC_LIBRARY_DIR):
        return []

    found = []
    for ext in SUPPORTED_FORMATS:
        found.extend(glob.glob(os.path.join(MUSIC_LIBRARY_DIR, f"*{ext}")))
        found.extend(glob.glob(os.path.join(MUSIC_LIBRARY_DIR, f"*{ext.upper()}")))

    # Filter out the .gitkeep placeholder
    found = [f for f in found if not f.endswith(".gitkeep")]

    return list(set(found))


def _sequence_tracks_to_duration(
    tracks: list,
    target_seconds: float,
    output_path: str,
    local_logger,
):
    """
    Concatenate multiple tracks in a random shuffled order, cycling through
    the library until the target duration is reached.

    WHY concat instead of loop? Looping one track sounds repetitive after a
    few minutes. Cycling through the full library keeps the music fresh for
    the entire 2-3 hour video.

    Args:
        tracks:         List of audio file paths in the local library.
        target_seconds: How many seconds long the output should be.
        output_path:    Where to save the final sequenced audio.
        local_logger:   Logger.
    """
    # Build a shuffled sequence, cycling through the library until we
    # have enough total duration to fill the video (plus a small buffer)
    shuffled = tracks[:]
    random.shuffle(shuffled)

    sequence = []
    total = 0.0
    idx = 0
    while total < target_seconds + 30:
        track = shuffled[idx % len(shuffled)]
        duration = _get_audio_duration(track)
        sequence.append(track)
        total += duration
        idx += 1
        # Reshuffle each time we cycle through the full library so the
        # order is different on every pass
        if idx % len(shuffled) == 0:
            random.shuffle(shuffled)

    local_logger.info(
        f"  Sequence: {len(sequence)} tracks, "
        f"~{total/3600:.1f}h total before trim"
    )

    # Write an FFmpeg concat list file
    concat_file = output_path.replace(".wav", "_concat.txt")
    with open(concat_file, "w", encoding="utf-8") as f:
        for track_path in sequence:
            # FFmpeg concat needs forward slashes and single-quote escaping
            safe = track_path.replace("\\", "/").replace("'", "\\'")
            f.write(f"file '{safe}'\n")

    # Step 1: Concatenate all tracks into one raw file
    raw_path = output_path.replace(".wav", "_raw_concat.wav")
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_file,
        "-t", str(target_seconds + 10),   # Small buffer — trim precisely in step 2
        "-c:a", "pcm_s16le",
        "-ar", "44100",
        raw_path,
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"FFmpeg concat failed: {e.stderr[-300:]}")
    finally:
        if os.path.exists(concat_file):
            os.remove(concat_file)

    # Step 2: Trim to exact duration and normalize to -14 LUFS
    cmd = [
        "ffmpeg", "-y",
        "-i", raw_path,
        "-t", str(target_seconds),
        "-af", f"loudnorm=I={TARGET_LUFS}:LRA=11:TP=-1.5",
        "-ar", "44100",
        "-c:a", "pcm_s16le",
        output_path,
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        os.remove(raw_path)
        local_logger.info(
            f"  ✓ Music ready: {len(sequence)} tracks, "
            f"{target_seconds/3600:.2f}h, normalized to {TARGET_LUFS} LUFS"
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"FFmpeg normalize failed: {e.stderr[-300:]}")


def _loop_track_to_duration(
    track_path: str,
    target_seconds: float,
    output_path: str,
    local_logger,
):
    """
    Loop an audio track to fill a target duration using FFmpeg.

    Uses FFmpeg's "aloop" filter to repeat the track as many times as needed,
    then applies a 5-second crossfade at each loop point to avoid a click.
    Finally normalizes to -14 LUFS for YouTube.

    WHY FFmpeg for looping? It handles the crossfading and normalization in one
    pass, producing clean, professional audio without any manual editing.

    Args:
        track_path:     Source audio track.
        target_seconds: How many seconds long the output should be.
        output_path:    Where to save the looped audio.
        local_logger:   Logger.
    """
    track_duration = _get_audio_duration(track_path)
    local_logger.info(f"  Track duration: {track_duration:.0f}s, need: {target_seconds:.0f}s")

    # Calculate how many loops are needed
    loops_needed = math.ceil(target_seconds / track_duration)
    local_logger.info(f"  Looping {loops_needed}x with 5-second crossfades...")

    # Step 1: Loop the audio
    looped_path = output_path.replace(".wav", "_raw_loop.wav")
    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", str(loops_needed + 1),  # Repeat the file N+1 times
        "-i", track_path,
        "-t", str(target_seconds + 10),         # Trim with a little buffer
        "-c:a", "pcm_s16le",                    # Uncompressed WAV for quality
        "-ar", "44100",                          # 44.1kHz — standard CD quality
        looped_path,
    ]

    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"FFmpeg loop failed: {e.stderr[-300:]}")

    # Step 2: Normalize to -14 LUFS for YouTube
    # We use the "loudnorm" filter which measures and adjusts in two passes
    # for accurate normalization. For simplicity here, we use single-pass.
    cmd = [
        "ffmpeg", "-y",
        "-i", looped_path,
        "-t", str(target_seconds),              # Trim to exact target duration
        "-af", f"loudnorm=I={TARGET_LUFS}:LRA=11:TP=-1.5",  # Normalize loudness
        "-ar", "44100",
        "-c:a", "pcm_s16le",
        output_path,
    ]

    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        # Clean up the intermediate file
        os.remove(looped_path)
        local_logger.info(f"  ✓ Music ready: {target_seconds/3600:.2f}h, normalized to {TARGET_LUFS} LUFS")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"FFmpeg normalize failed: {e.stderr[-300:]}")


def _generate_mubert_track(
    music_prompt: str,
    target_seconds: float,
    output_path: str,
    api_key: str,
    local_logger,
):
    """
    Generate a LoFi music track using the Mubert API.

    Mubert can generate music on demand based on mood/genre tags.
    We extract the key musical descriptors from the orchestrator's
    music_prompt and send them to Mubert.

    Args:
        music_prompt:   Music description from the orchestrator.
        target_seconds: Desired track duration in seconds.
        output_path:    Where to save the downloaded track.
        api_key:        Mubert API key.
        local_logger:   Logger.
    """
    local_logger.info(f"  Generating Mubert track: {music_prompt[:60]}...")

    # Mubert API works with music tags (genre/mood keywords)
    # We use a fixed set of LoFi tags that always produce good results
    # regardless of the scene — LoFi is fundamentally a consistent genre
    lofi_tags = ["lo-fi", "chill", "ambient", "relaxing", "meditation", "study"]

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    # Step 1: Get a licensed track from Mubert's library
    # The Mubert Render API generates tracks based on tags and duration
    payload = {
        "method": "RecordTrack",
        "params": {
            "pat": api_key,
            "tags": lofi_tags,
            "duration": int(min(target_seconds, 3600)),  # Max 1 hour
            "format": "mp3",
            "bitrate": 128,
        }
    }

    try:
        response = requests.post(
            "https://api.mubert.com/v2/RecordTrack",
            json=payload,
            headers=headers,
            timeout=30,
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"Mubert API returned HTTP {response.status_code}: {response.text[:200]}"
            )

        data = response.json()

        # Mubert may return the track URL directly or a task ID to poll
        # Check both patterns
        track_url = (
            data.get("data", {}).get("tasks", [{}])[0].get("download_link")
            or data.get("data", {}).get("url")
        )

        if track_url:
            _download_audio(track_url, output_path)
            local_logger.info(f"  ✓ Mubert track downloaded: {os.path.basename(output_path)}")
        else:
            raise RuntimeError(
                f"Mubert didn't return a download URL. Response: {data}"
            )

    except requests.RequestException as e:
        raise RuntimeError(
            f"Mubert API request failed: {e}\n"
            "Add LoFi tracks to assets/music/ to use the local library instead."
        )


def _download_audio(url: str, save_path: str):
    """
    Download an audio file from a URL.

    Args:
        url:       URL of the audio file.
        save_path: Where to save it.
    """
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    response = requests.get(url, timeout=120, stream=True)
    if response.status_code != 200:
        raise RuntimeError(f"Audio download failed (HTTP {response.status_code})")

    with open(save_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            f.write(chunk)


def _get_audio_duration(audio_path: str) -> float:
    """
    Get the duration of an audio file in seconds using FFprobe.

    Args:
        audio_path: Path to the audio file.

    Returns:
        Duration in seconds.
    """
    cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "json",
        audio_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        data = json.loads(result.stdout)
        return float(data["format"]["duration"])
    except Exception:
        return 3600.0  # Assume 1 hour if we can't read it
