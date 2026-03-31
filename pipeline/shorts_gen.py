# =============================================================================
# pipeline/shorts_gen.py — YouTube Shorts Generator
# =============================================================================
# PURPOSE:
#   After the main pipeline produces a finished long-form video (2-3 hours),
#   this module extracts 5 YouTube Shorts from it. Each Short uses a different
#   visual effect so they feel distinct from each other.
#
# WHY Shorts? YouTube Shorts get 10x+ the impressions of long-form videos for
# new channels. Each Short is a free ad for the full-length video. 5 Shorts
# per video = 5 chances to reach new viewers per upload.
#
# THE 5 EFFECTS:
#   1. WARM GRADE       — Static flag crop, golden cinematic color grade + vignette
#   2. KEN BURNS PAN    — Slow horizontal drift across the scene
#   3. BLOOM FADE       — Dreamy brightness pulse + vignette, no camera motion
#   4. COOL MIST        — Static flag crop, cool desaturated misty grade + vignette
#   5. GOLFQUILIZER     — Audio-reactive radial visualizer, mirrored, ball on tee
#
# SONG BOUNDARIES:
#   Each Short starts at the beginning of a song (where the audio fades in),
#   not in the middle of a track. Boundaries come from music_gen.py's exported
#   song_boundaries.json, or as a fallback, from FFmpeg's silencedetect filter.
#
# OUTPUT:
#   output/shorts/{video_stem}/
#     ├── short_1_warm_grade.mp4
#     ├── short_2_ken_burns.mp4
#     ├── short_3_bloom_fade.mp4
#     ├── short_4_cool_mist.mp4
#     ├── short_5_golfquilizer.mp4
#     ├── metadata.json
#     └── metadata.txt
# =============================================================================

import json
import logging
import os
import random
import subprocess
import tempfile

import numpy as np
from PIL import Image

import config
from pipeline.golfquilizer import render_golfquilizer

logger = logging.getLogger("fairway.shorts_gen")


# =============================================================================
# CONSTANTS
# =============================================================================

# The 5 effects in fixed order — every video gets all 5, one per Short.
EFFECT_NAMES = [
    "warm_grade",
    "ken_burns",
    "bloom_fade",
    "cool_mist",
    "golfquilizer",
]

# How many seconds to skip at the start of the video (avoid intro silence)
SEGMENT_START_OFFSET = 30

# How many seconds after a detected silence ends before we start the Short
# (gives the new song a moment to fade in)
SILENCE_OFFSET = 0.5

# Hook templates for Short titles — each effect gets its own bank of options.
# One is picked randomly per Short so titles feel varied across uploads.
HOOK_TEMPLATES = {
    "warm_grade": [
        "This golf course hits different at {mood}",
        "POV: You found the perfect study spot ⛳",
        "When the vibes are just right",
        "Put this on and let the world fade away",
        "The view from the fairway right now",
    ],
    "ken_burns": [
        "Take a walk through this painted golf course",
        "The most peaceful place on earth right now",
        "Somewhere between a painting and a dream",
        "Let your eyes wander across the fairway",
        "Every frame is a painting",
    ],
    "bloom_fade": [
        "POV: Golden hour on the fairway",
        "This is what peace looks like",
        "The light on this golf course is unreal",
        "Save this for when you need to breathe",
        "When the light hits the green just right",
    ],
    "cool_mist": [
        "Studio Ghibli golf course, anyone?",
        "If golf courses were anime backgrounds",
        "Can you hear the birds?",
        "The peaceful side of golf",
        "This golf course feels like a dream",
    ],
    "golfquilizer": [
        "Watch the music come alive on the fairway",
        "When the lofi beats match the vibes perfectly",
        "The golf ball is feeling this track",
        "POV: The fairway has its own heartbeat",
        "Feel the rhythm of the course",
        "The Golfquilizer is vibing today",
    ],
}

# Map scene keywords to mood words used in hook templates
MOOD_MAP = {
    "sunset": "sunset", "sunrise": "sunrise", "golden": "golden hour",
    "rain": "rain", "misty": "dawn", "morning": "morning",
    "night": "night", "winter": "winter", "snow": "snowfall",
    "autumn": "autumn", "spring": "spring", "tropical": "sunset",
    "dusk": "dusk", "dawn": "dawn", "fog": "fog",
}


# =============================================================================
# PUBLIC ENTRY POINT
# =============================================================================

def generate_shorts(
    final_video_path: str,
    run_dir: str,
    boundaries_path: str,
    metadata: dict,
    logger: logging.Logger = None,
) -> dict:
    """
    Generate YouTube Shorts from a finished long-form Fairway Frequencies video.

    Each Short is 45 seconds, uses a different visual effect, and starts at the
    beginning of a song (detected from boundaries or via silence detection).

    Args:
        final_video_path: Path to the finished 2-3 hour .mp4 video.
        run_dir:          The run directory (for finding song_boundaries.json).
        boundaries_path:  Path to song_boundaries.json (or None for auto-detect).
        metadata:         The video's metadata dict (title, tags, etc.).
        logger:           Logger for progress messages.

    Returns:
        Dict with keys: count, output_dir, shorts (list of per-Short info).
    """
    local_logger = logger or logging.getLogger("fairway.shorts_gen")

    # Create the output directory for this video's Shorts
    video_stem = os.path.splitext(os.path.basename(final_video_path))[0]
    output_dir = os.path.join(config.OUTPUT_DIR, "shorts", video_stem)
    os.makedirs(output_dir, exist_ok=True)

    local_logger.info(f"  Output: {output_dir}")

    # Get the source video's total duration
    duration = _get_video_duration(final_video_path, local_logger)
    local_logger.info(f"  Source video: {duration / 3600:.2f} hours ({_format_time(duration)})")

    # --- Load song boundaries ---
    # WHY: We want each Short to start at the beginning of a song, not mid-track.
    # The music_gen stage exports exact timestamps; silencedetect is the fallback.
    boundaries = _load_boundaries(boundaries_path, final_video_path, duration, local_logger)

    # --- Pick where each Short will start ---
    count = min(config.SHORTS_COUNT, len(EFFECT_NAMES))
    starts = _pick_segment_starts(boundaries, count, duration, local_logger)

    local_logger.info(f"  Extraction points:")
    for i, ts in enumerate(starts):
        local_logger.info(f"    Short {i + 1} ({EFFECT_NAMES[i]}): {_format_time(ts)}")

    # --- Render each Short ---
    shorts_info = []
    successes = 0

    for i in range(count):
        effect_name = EFFECT_NAMES[i]
        start_time = starts[i]
        output_path = os.path.join(output_dir, f"short_{i + 1}_{effect_name}.mp4")

        local_logger.info(f"  [{i + 1}/{count}] Rendering {effect_name}...")
        local_logger.info(
            f"    Source: {_format_time(start_time)} → "
            f"{_format_time(start_time + config.SHORTS_DURATION)}"
        )

        if effect_name == "golfquilizer":
            ball_color = _detect_scene_brightness(final_video_path, start_time, local_logger)
            ball_path = (config.GOLFQUILIZER_BALL_WHITE if ball_color == "white"
                         else config.GOLFQUILIZER_BALL_BLACK)
            ok = render_golfquilizer(
                video_path=final_video_path,
                start_time=start_time,
                duration=config.SHORTS_DURATION,
                output_path=output_path,
                ball_path=ball_path,
                local_logger=local_logger,
            )
        else:
            # Detect flag position and build effect filter centered on it
            flag_x = _detect_flag_position(final_video_path, start_time, local_logger)
            filter_str = _build_effect_filter(effect_name, config.SHORTS_DURATION, flag_x)
            ok = _render_short(
                final_video_path, start_time, effect_name, filter_str,
                output_path, local_logger
            )

        if ok:
            successes += 1
            size_mb = os.path.getsize(output_path) / (1024 * 1024)
            local_logger.info(f"    ✓ Created: {os.path.basename(output_path)} ({size_mb:.1f} MB)")
        else:
            local_logger.warning(f"    ⚠️ Failed: {effect_name}")

        shorts_info.append({
            "file": os.path.basename(output_path),
            "effect": effect_name,
            "start_time": start_time,
            "success": ok,
        })

    # --- Generate metadata for each Short ---
    _generate_shorts_metadata(shorts_info, metadata, output_dir, local_logger)

    local_logger.info(f"  ✓ Shorts complete: {successes}/{count} rendered")

    return {
        "count": successes,
        "output_dir": output_dir,
        "shorts": shorts_info,
    }


# =============================================================================
# SONG BOUNDARY LOADING
# =============================================================================

def _get_video_duration(video_path: str, local_logger) -> float:
    """
    Ask FFprobe how long the source video is.

    WHY ffprobe? It reads the container metadata without decoding the video,
    so it's instant even for a 3-hour file.
    """
    cmd = [
        "ffprobe", "-i", video_path,
        "-show_entries", "format=duration",
        "-v", "quiet", "-of", "csv=p=0",
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return float(result.stdout.strip())
    except Exception as e:
        local_logger.warning(f"  ⚠️ Could not read video duration: {e}")
        # Assume 2 hours as fallback
        return config.TARGET_DURATION_HOURS * 3600


def _load_boundaries(
    boundaries_path: str,
    video_path: str,
    duration: float,
    local_logger,
) -> list:
    """
    Load song boundary timestamps, trying the exported file first, then
    falling back to FFmpeg silence detection, then to even spacing.

    Returns:
        Sorted list of float timestamps (seconds) where songs begin.
    """
    # Option A: Load from the exported boundaries file (most accurate)
    if boundaries_path and os.path.exists(boundaries_path):
        try:
            with open(boundaries_path, "r") as f:
                boundaries = json.load(f)
            if isinstance(boundaries, list) and len(boundaries) > 0:
                # Filter to usable range (not too early, not too late for a Short)
                usable = [
                    b for b in boundaries
                    if SEGMENT_START_OFFSET <= b <= duration - config.SHORTS_DURATION - 10
                ]
                if usable:
                    local_logger.info(
                        f"  Song boundaries: {len(usable)} usable "
                        f"(from {os.path.basename(boundaries_path)})"
                    )
                    return sorted(usable)
        except Exception as e:
            local_logger.warning(f"  ⚠️ Could not load boundaries file: {e}")

    # Option B: Auto-detect via FFmpeg silencedetect (fallback)
    local_logger.info("  No boundary file — detecting song transitions via audio analysis...")
    detected = _detect_boundaries_silencedetect(video_path, duration, local_logger)
    if detected:
        return detected

    # Option C: Even spacing (last resort)
    local_logger.warning(
        "  ⚠️ No song boundaries found — falling back to even spacing. "
        "Shorts may start mid-song."
    )
    usable_start = SEGMENT_START_OFFSET
    usable_end = duration - config.SHORTS_DURATION - 10
    usable_range = usable_end - usable_start
    return [
        round(usable_start + (usable_range * i / (config.SHORTS_COUNT + 1)), 2)
        for i in range(1, config.SHORTS_COUNT + 1)
    ]


def _detect_boundaries_silencedetect(
    video_path: str,
    duration: float,
    local_logger,
) -> list:
    """
    Find song transitions by detecting silence gaps in the audio.

    HOW IT WORKS:
    Your pipeline concatenates Suno tracks with crossfades. Between songs
    there's a brief volume dip. FFmpeg's silencedetect finds these dips.

    We look for audio drops below SILENCE_THRESHOLD_DB for at least
    SILENCE_MIN_DURATION seconds. The END of each silence period
    (+ offset) is where the new song starts — that's our Short's start.
    """
    local_logger.info(
        f"  Scanning audio (threshold: {config.SILENCE_THRESHOLD_DB}dB, "
        f"min silence: {config.SILENCE_MIN_DURATION}s)..."
    )

    cmd = [
        "ffmpeg", "-i", video_path,
        "-af", (
            f"silencedetect=noise={config.SILENCE_THRESHOLD_DB}dB:"
            f"d={config.SILENCE_MIN_DURATION}"
        ),
        "-f", "null", "-",
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception as e:
        local_logger.warning(f"  ⚠️ Silence detection failed: {e}")
        return []

    # Parse silence_end timestamps from FFmpeg stderr.
    # Lines look like:
    #   [silencedetect @ 0x...] silence_end: 185.432 | silence_duration: 1.234
    boundaries = []
    for line in result.stderr.split("\n"):
        if "silence_end" in line:
            try:
                parts = line.split("silence_end:")[1].strip()
                timestamp = float(parts.split("|")[0].strip())
                adjusted = timestamp + SILENCE_OFFSET
                if SEGMENT_START_OFFSET < adjusted < duration - config.SHORTS_DURATION - 10:
                    boundaries.append(round(adjusted, 2))
            except (IndexError, ValueError):
                continue

    boundaries = sorted(set(boundaries))
    local_logger.info(f"  Found {len(boundaries)} song boundaries via silence detection")
    return boundaries


def _pick_segment_starts(
    boundaries: list,
    count: int,
    duration: float,
    local_logger,
) -> list:
    """
    Pick which song boundaries to use for our Shorts.

    STRATEGY: Divide boundaries into equal-sized groups, pick one from each.
    This ensures Shorts come from different parts of the video (not all
    clustered in the first 20 minutes).

    Falls back to even spacing if not enough boundaries are available.
    """
    if len(boundaries) >= count:
        # Divide into groups and pick one per group
        chunk_size = len(boundaries) / count
        picks = []
        for i in range(count):
            chunk_start = int(i * chunk_size)
            chunk_end = int((i + 1) * chunk_size)
            picks.append(random.choice(boundaries[chunk_start:chunk_end]))
        return sorted(picks)
    else:
        # Not enough boundaries — use what we have + fill gaps with even spacing
        local_logger.warning(
            f"  ⚠️ Only {len(boundaries)} boundaries for {count} Shorts — "
            f"filling gaps with even spacing"
        )
        picks = list(boundaries)
        remaining = count - len(picks)
        usable_start = SEGMENT_START_OFFSET
        usable_end = duration - config.SHORTS_DURATION - 10
        usable_range = usable_end - usable_start
        for i in range(remaining):
            offset = usable_start + (usable_range * (i + 1) / (remaining + 1))
            picks.append(round(offset, 2))
        return sorted(picks)


# =============================================================================
# FLAG DETECTION — Find the flagstick's horizontal position in the frame
# =============================================================================

def _detect_scene_brightness(video_path: str, start_time: float, local_logger) -> str:
    """
    Sample the average brightness of a frame to choose white or black golf ball.
    Returns 'white' for dark scenes, 'black' for bright scenes.
    """
    cmd = [
        "ffmpeg", "-ss", str(start_time), "-i", video_path,
        "-frames:v", "1",
        "-vf", "crop=iw/2:ih/2:iw/4:ih/4,signalstats",
        "-f", "null", "-",
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        for line in result.stderr.split("\n"):
            if "YAVG" in line:
                yavg = float(line.split("YAVG:")[1].strip().split()[0])
                color = "black" if yavg > 128 else "white"
                local_logger.info(f"    Scene brightness: {yavg:.0f}/255 → {color} golf ball")
                return color
    except Exception:
        pass
    return "white"


def _detect_flag_position(video_path: str, start_time: float, local_logger) -> int:
    """
    Detect the horizontal center of the golf flag/pin in the source frame.

    HOW: Extracts a single frame at start_time, then scans each column for
    pixels matching typical flag colors (red, orange, yellow, white). The
    column with the highest concentration of flag-colored pixels is where
    the flag is. Only the upper 60% of the frame is considered — the flag
    is always above the ground.

    WHY colors, not shape? The source art is stylized/painted (Studio Ghibli
    style), so edge detection is unreliable. Color is consistent: flags in
    golf course art are almost always warm/bright against a green background.

    Returns:
        x pixel coordinate (0–1919) of the flagstick center, or 960 (center)
        if detection fails or no flag is found.
    """
    frame_path = tempfile.mktemp(suffix=".png")
    try:
        # Extract one frame at the short's start time
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start_time),
            "-i", video_path,
            "-frames:v", "1",
            "-vf", "scale=1920:1080",
            frame_path,
        ]
        subprocess.run(
            cmd, capture_output=True, check=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

        img = Image.open(frame_path).convert("RGB")
        arr = np.array(img)  # shape: (1080, 1920, 3)

        r, g, b = arr[:, :, 0].astype(int), arr[:, :, 1].astype(int), arr[:, :, 2].astype(int)

        # Flag color masks — covers red, orange, yellow, and white flags
        is_red    = (r > 180) & (g < 110) & (b < 110)
        is_orange = (r > 200) & (g > 80)  & (g < 160) & (b < 80)
        is_yellow = (r > 200) & (g > 180) & (b < 100)
        is_white  = (r > 220) & (g > 220) & (b > 220)
        is_flag_color = is_red | is_orange | is_yellow | is_white

        # Only look in the upper 60% of the frame (flag is above ground level)
        is_flag_color[int(1080 * 0.6):, :] = False

        # Sum flag-colored pixels per column → find the peak column
        col_scores = is_flag_color.sum(axis=0)  # shape: (1920,)

        if col_scores.max() < 5:
            local_logger.info("    Flag detection: no flag found — using center crop")
            return 960

        flag_x = int(col_scores.argmax())
        local_logger.info(
            f"    Flag detected at x={flag_x} "
            f"(score={int(col_scores[flag_x])} px)"
        )
        return flag_x

    except Exception as e:
        local_logger.warning(f"    Flag detection failed: {e} — using center crop")
        return 960
    finally:
        try:
            os.unlink(frame_path)
        except OSError:
            pass


# =============================================================================
# EFFECT FILTERS — Effects 1-4 (simple -vf filter strings)
# =============================================================================
# All effects crop the 16:9 source (1920×1080) into 9:16 vertical (1080×1920).
# The crop window is 607px wide (1080 * 9/16 ≈ 607) from the 1080px-tall source.

def _build_effect_filter(effect_name: str, duration: int, flag_x: int) -> str:
    """Route to the correct filter builder for all 4 effects."""
    builders = {
        "warm_grade": _build_filter_warm_grade,
        "ken_burns":  _build_filter_ken_burns,
        "bloom_fade": _build_filter_bloom_fade,
        "cool_mist":  _build_filter_cool_mist,
    }
    return builders[effect_name](duration, flag_x)


def _build_filter_warm_grade(duration: int, flag_x: int) -> str:
    """
    EFFECT 1: WARM GRADE
    Static flag crop with a warm, golden cinematic color grade.
    No camera motion — the rich tones are the whole vibe.

    HOW: colorbalance pushes shadows/midtones warm (red+, blue-), a gentle
    S-curve via curves lifts contrast, and a vignette frames the flag.
    Upscale to 3840×2160 for a clean, sharp 1080×1920 downscale.
    """
    x = max(0, min(2626, (flag_x - 303) * 2))
    return (
        f"scale=3840:2160:flags=bilinear,"
        f"crop=1214:2160:{x}:0,"
        f"colorbalance=rs=0.08:gs=0.02:bs=-0.12:rm=0.05:gm=0.01:bm=-0.08,"
        f"curves=r='0/0 0.5/0.55 1/1':g='0/0 0.5/0.5 1/0.95':b='0/0 0.5/0.45 1/0.85',"
        f"vignette=angle=0.6,"
        f"scale={config.SHORTS_WIDTH}:{config.SHORTS_HEIGHT}:flags=lanczos"
    )


def _build_filter_ken_burns(duration: int, flag_x: int) -> str:
    """
    EFFECT 2: KEN BURNS PAN
    Drifts a 9:16 crop window left-to-right (or right-to-left, randomly chosen),
    centered on the flag so it stays visible throughout the pan.

    HOW: Upscale source to 3840×2160 so each integer crop step = 0.89px in
    output — sub-pixel, invisible after lanczos downscale. All coordinates
    are 2× the 1920-space values. ±400px travel (at 2× scale) around the
    flag while keeping it in frame the whole time.
    """
    total_frames = duration * 30
    direction = random.choice(["ltr", "rtl"])
    # All coords at 2× scale (3840 wide). Max x so 1214px crop fits: 3840-1214=2626.
    x_center = max(0, min(2626, (flag_x - 303) * 2))
    x_start  = max(0, min(2626, x_center - 400))
    x_end    = max(0, min(2626, x_center + 400))
    travel   = x_end - x_start
    x_expr = (
        f"{x_start}+{travel}*(n/{total_frames})" if direction == "ltr"
        else f"{x_end}-{travel}*(n/{total_frames})"
    )
    return (
        f"scale=3840:2160:flags=bilinear,"
        f"crop=w=1214:h=2160:x='{x_expr}':y=0,"
        f"scale={config.SHORTS_WIDTH}:{config.SHORTS_HEIGHT}:flags=lanczos"
    )


def _build_filter_bloom_fade(duration: int, flag_x: int) -> str:
    """
    EFFECT 3: BLOOM FADE
    Static crop on the flag + gentle brightness sine-wave pulse + vignette.
    Dreamy and ethereal — no camera movement; the light IS the motion.

    HOW: Upscale to 3840×2160 for a sharper downscale to 1080×1920.
    Crop is pinned to flag_x (at 2× coordinates) so the flag stays centered.
    """
    total_frames = duration * 30
    x = max(0, min(2626, (flag_x - 303) * 2))
    return (
        f"scale=3840:2160:flags=bilinear,"
        f"crop=1214:2160:{x}:0,"
        f"eq=brightness='0.03*sin(2*3.14159*n/{total_frames})':contrast=1.02,"
        f"vignette=angle=0.7854,"
        f"scale={config.SHORTS_WIDTH}:{config.SHORTS_HEIGHT}:flags=lanczos"
    )


def _build_filter_cool_mist(duration: int, flag_x: int) -> str:
    """
    EFFECT 4: COOL MIST
    Static flag crop with a cool, slightly desaturated misty color grade.
    Counterpart to warm_grade — same composition, opposite mood.

    HOW: colorbalance pushes shadows/midtones cool (blue+, red-), eq drops
    saturation slightly and lifts brightness to give a faded, overcast feel,
    and a wide vignette softens the edges. No motion at all.
    """
    x = max(0, min(2626, (flag_x - 303) * 2))
    return (
        f"scale=3840:2160:flags=bilinear,"
        f"crop=1214:2160:{x}:0,"
        f"colorbalance=rs=-0.06:gs=0:bs=0.10:rm=-0.04:gm=0.01:bm=0.07,"
        f"eq=brightness=0.04:contrast=0.95:saturation=0.80,"
        f"vignette=angle=0.8,"
        f"scale={config.SHORTS_WIDTH}:{config.SHORTS_HEIGHT}:flags=lanczos"
    )


# =============================================================================
# STANDARD SHORT RENDERING (Effects 1-4)
# =============================================================================

def _render_short(
    video_path: str,
    start_time: float,
    effect_name: str,
    filter_str: str,
    output_path: str,
    local_logger,
) -> bool:
    """
    Extract one Short using effects 1-4 (simple -vf filter string).

    WHY -ss before -i? This tells FFmpeg to seek BEFORE opening the file,
    which is nearly instant even for a 3-hour video. Putting -ss after -i
    would decode from the beginning (very slow).
    """
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start_time),
        "-i", video_path,
        "-t", str(config.SHORTS_DURATION),
        "-vf", filter_str,
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        output_path,
    ]

    try:
        subprocess.run(
            cmd, capture_output=True, text=True, check=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return os.path.exists(output_path) and os.path.getsize(output_path) > 0
    except subprocess.CalledProcessError as e:
        local_logger.warning(f"    FFmpeg failed for {effect_name}: {e.stderr[-400:]}")
        return False


# =============================================================================
# SHORTS METADATA GENERATION
# =============================================================================

def _generate_shorts_metadata(
    shorts_info: list,
    parent_metadata: dict,
    output_dir: str,
    local_logger,
) -> None:
    """
    Generate unique titles and descriptions for each Short.

    WHY unique metadata? Identical descriptions across 5 uploads from the same
    channel look spammy to YouTube's algorithm. Each effect gets a different
    "hook" that matches its visual character.
    """
    # Extract a mood word from the parent video's title/description
    parent_title = parent_metadata.get("title", "")
    parent_desc = parent_metadata.get("description", "")
    combined_text = f"{parent_title} {parent_desc}".lower()

    mood = "sunset"  # default
    for keyword, mood_word in MOOD_MAP.items():
        if keyword in combined_text:
            mood = mood_word
            break

    hashtags = "#lofi #studymusic #chillbeats #golfvibes #shorts #ambientmusic"

    metadata = {
        "source_video_title": parent_title,
        "generated_shorts": [],
    }

    for info in shorts_info:
        effect = info["effect"]
        hooks = HOOK_TEMPLATES.get(effect, HOOK_TEMPLATES["warm_grade"])
        hook = random.choice(hooks).format(mood=mood)

        description = (
            f"{hook}\n\n"
            f"🎵 Lofi beats for studying, relaxing & working\n"
            f"🎨 Studio Ghibli-inspired golf course art\n\n"
            f"Full-length version on our channel — hours of peaceful "
            f"golf course vibes.\n"
            f"Subscribe for new scenes every week.\n\n"
            f"{hashtags}"
        )

        metadata["generated_shorts"].append({
            "filename": info["file"],
            "effect": effect,
            "title": hook,
            "description": description,
            "tags": [
                "lofi", "lofi beats", "study music", "chill beats",
                "relaxing music", "golf", "ambient", "shorts",
                "lofi hip hop", "focus music", "Ghibli", "anime",
                "golf course", "peaceful", "study", "relax",
            ],
        })

    # Save metadata.json
    json_path = os.path.join(output_dir, "metadata.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    # Save metadata.txt for easy copy/paste
    txt_path = os.path.join(output_dir, "metadata.txt")
    lines = []
    for entry in metadata["generated_shorts"]:
        lines.append(f"{'=' * 50}")
        lines.append(f"SHORT: {entry['filename']}")
        lines.append(f"EFFECT: {entry['effect']}")
        lines.append(f"{'=' * 50}")
        lines.append(f"\nTITLE:\n{entry['title']}")
        lines.append(f"\nDESCRIPTION:\n{entry['description']}")
        lines.append(f"\nTAGS:\n{', '.join(entry['tags'])}")
        lines.append("")

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    local_logger.info(f"  ✓ Metadata saved: {json_path}")
    local_logger.info(f"  ✓ Plain text:     {txt_path}")


# =============================================================================
# UTILITIES
# =============================================================================

def _format_time(seconds: float) -> str:
    """Format seconds as HH:MM:SS for log output."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"
