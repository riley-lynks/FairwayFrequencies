# =============================================================================
# pipeline/video_assembly.py — Living Painting Video Assembly (v3)
# =============================================================================
# PURPOSE:
#   Take the 10 animation clips (all from the SAME base image) and stitch
#   them into a seamless 2-3 hour "living painting" — a continuous video
#   that looks like one unbroken animated scene.
#
# THE KEY INSIGHT (why v3 works so well):
#   Normal crossfades between DIFFERENT scenes are visible because the whole
#   composition changes. But crossfades between clips from the SAME base image
#   are nearly invisible — 95% of the frame is identical (same green, same trees,
#   same sky shape). Only the animation elements (cloud position, flag angle,
#   grass ripple) blend, which looks like natural wind variation, NOT a cut.
#
# THE ALGORITHM:
#   1. Normalize all clips to identical codec/resolution/framerate
#   2. Build a shuffled playlist (enough clips to fill target duration)
#   3. Process clips in BATCHES OF 10 (avoids FFmpeg filter graph limits)
#   4. Apply 2-second crossfades between clips in each batch
#   5. Concatenate all batches into the final video
#
# WHY BATCHES OF 10?
#   FFmpeg's filter graph has an internal complexity limit. If you chain too
#   many xfade operations in one command, FFmpeg either crashes or produces
#   errors. Processing 10 clips at a time (9 xfades per FFmpeg call) stays
#   well within these limits.
#
# WHAT WE DO NOT DO (v3 changes from v2):
#   - NO Ken Burns zoom (no camera movement — this is a painting, not a video)
#   - NO color grading (the illustrated image has its own palette)
#   - NO film grain (this is illustrated art, grain looks wrong)
#   - NO scene transitions (all clips are from the SAME base image)
# =============================================================================

import os           # For file paths and directory creation
import subprocess   # For running FFmpeg commands
import math         # For math.ceil() — rounding up clip counts
import random       # For shuffling the clip playlist
import shutil       # For copying/moving files
import logging      # For progress messages
import json         # For reading clip metadata
from pathlib import Path  # For clean path handling

import config       # Our settings

logger = logging.getLogger("fairway.video_assembly")

# How many clips to process per FFmpeg call
# 10 clips = 9 xfade operations — safely within FFmpeg's limits
BATCH_SIZE = 10

# Target framerate for all normalized clips
TARGET_FPS = 30

# Target codec and quality settings
# libx264 = H.264 video codec (standard for YouTube)
# crf 18 = high quality (0=lossless, 51=worst, 18-23 is visually lossless for most content)
# preset fast = faster encoding, slightly larger file (good balance for our use)
VIDEO_CODEC = "libx264"
VIDEO_CRF = "18"
VIDEO_PRESET = "fast"


def assemble_living_painting(
    clip_paths: list,
    target_duration_hours: float,
    blend_seconds: float,
    run_dir: str,
    norm_dir: str,
    stabilize: bool = False,
    logger: logging.Logger = None,
) -> str:
    """
    Assemble animation clips into a seamless looping living painting.

    This is the most complex function in the pipeline. It handles:
    - Normalizing clips to consistent specs
    - Building a playlist that fills the target duration
    - Processing clips in batches to avoid FFmpeg limits
    - Applying invisible crossfades between clips from the same base image

    Args:
        clip_paths:           List of paths to the animation clips.
        target_duration_hours: How long the final video should be.
        blend_seconds:        Duration of crossfade at each loop point (default: 2).
        run_dir:              Run directory (for storing intermediate files).
        norm_dir:             Directory to store normalized clips.
        logger:               Logger for progress messages.

    Returns:
        Path to the final assembled video file.

    Raises:
        RuntimeError: If FFmpeg fails or no clips are available.
    """
    local_logger = logger or logging.getLogger("fairway.video_assembly")

    if not clip_paths:
        raise RuntimeError("No clips provided to video assembly.")

    local_logger.info(f"  Processing {len(clip_paths)} animation clips")
    local_logger.info(f"  Target: {target_duration_hours} hours = {target_duration_hours * 3600:.0f} seconds")

    # Step 1: Normalize all clips to identical specs (+ optional stabilization)
    if stabilize:
        local_logger.info("  Step 1/4: Normalizing + stabilizing clips (2-pass vidstab)...")
    else:
        local_logger.info("  Step 1/4: Normalizing clips (resolution, framerate, codec)...")
    normalized_clips = _normalize_clips(clip_paths, norm_dir, stabilize, local_logger)
    local_logger.info(f"  ✓ {len(normalized_clips)} clips normalized{' and stabilized' if stabilize else ''}")

    # Step 2: Get clip durations and build playlist
    local_logger.info("  Step 2/4: Building playlist...")
    clip_durations = {path: get_video_duration(path) for path in normalized_clips}

    avg_duration = sum(clip_durations.values()) / len(clip_durations)
    local_logger.info(f"  Average clip duration: {avg_duration:.1f}s")

    playlist = _build_shuffled_playlist(
        clips=normalized_clips,
        target_duration_hours=target_duration_hours,
        blend_seconds=blend_seconds,
        avg_duration=avg_duration,
    )

    total_clips_in_playlist = len(playlist)
    estimated_duration = total_clips_in_playlist * (avg_duration - blend_seconds)
    local_logger.info(
        f"  Playlist: {total_clips_in_playlist} clip plays "
        f"(~{estimated_duration/3600:.2f} hours)"
    )

    # Step 3: Process in batches
    local_logger.info(f"  Step 3/4: Processing in batches of {BATCH_SIZE}...")
    batch_dir = os.path.join(run_dir, "batches")
    os.makedirs(batch_dir, exist_ok=True)

    batch_files = _process_batches(
        playlist=playlist,
        clip_durations=clip_durations,
        blend_seconds=blend_seconds,
        batch_dir=batch_dir,
        local_logger=local_logger,
    )
    local_logger.info(f"  ✓ {len(batch_files)} batches processed")

    # Step 4: Concatenate batches into final video
    local_logger.info("  Step 4/4: Concatenating batches into final video...")
    assembled_path = os.path.join(run_dir, "assembled_video.mp4")

    if len(batch_files) == 1:
        # Only one batch — just rename/copy it
        shutil.copy2(batch_files[0], assembled_path)
    else:
        # Multiple batches — join them with short crossfades
        _concatenate_batches(
            batch_files=batch_files,
            blend_seconds=blend_seconds,
            output_path=assembled_path,
            local_logger=local_logger,
        )

    final_duration = get_video_duration(assembled_path)
    local_logger.info(f"  ✓ Assembly complete: {final_duration/3600:.2f} hours")

    return assembled_path


def _normalize_clips(clip_paths: list, norm_dir: str, stabilize: bool, local_logger) -> list:
    """
    Re-encode all clips to identical resolution, framerate, and codec.

    WHY normalize? The 10 clips might have slightly different properties
    depending on what Kling returns (different bitrates, slightly different
    durations, etc.). FFmpeg's xfade filter requires all inputs to have
    the same properties. Normalizing upfront prevents subtle mismatches
    that would cause the crossfades to stutter or glitch.

    Args:
        clip_paths:   List of raw clip paths.
        norm_dir:     Directory to save normalized clips.
        local_logger: Logger.

    Returns:
        List of paths to normalized clip files.
    """
    os.makedirs(norm_dir, exist_ok=True)
    normalized = []

    for i, clip_path in enumerate(clip_paths):
        clip_name = os.path.basename(clip_path)
        norm_path = os.path.join(norm_dir, f"norm_{i:02d}.mp4")

        # Skip if already normalized (resume support)
        if os.path.exists(norm_path):
            local_logger.debug(f"  Clip {i+1} already normalized, skipping")
            normalized.append(norm_path)
            continue

        local_logger.info(f"  {'Stabilizing' if stabilize else 'Normalizing'} clip {i+1}/{len(clip_paths)}: {clip_name}")

        # The base video filter chain: scale to target resolution, then crop, then fps
        base_vf = (
            f"scale={config.VIDEO_WIDTH}:{config.VIDEO_HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={config.VIDEO_WIDTH}:{config.VIDEO_HEIGHT},"
            f"fps={TARGET_FPS}"
        )

        try:
            if stabilize:
                # Two-pass vidstab:
                # Pass 1 — vidstabdetect: analyzes motion in the raw clip and writes
                #           a .trf (transform) file. No output video is produced (-f null).
                # Pass 2 — vidstabtransform: applies the correction from the .trf file,
                #           then runs the normal scale/crop/fps chain.
                #
                # vidstabtransform settings:
                #   smoothing=10  — considers 10 frames before/after for smoothing (gentle)
                #   optzoom=0     — disables auto-zoom (we handle framing with scale+crop)
                trf_path = os.path.join(norm_dir, f"stab_{i:02d}.trf")

                # Pass 1: motion analysis
                pass1_cmd = [
                    "ffmpeg", "-y",
                    "-i", clip_path,
                    "-vf", f"vidstabdetect=shakiness=5:accuracy=15:result={trf_path}",
                    "-f", "null", "-",
                ]
                subprocess.run(
                    pass1_cmd,
                    capture_output=True, text=True, check=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                local_logger.debug(f"  Pass 1 done: {trf_path}")

                # Pass 2: apply stabilization + full normalize
                pass2_cmd = [
                    "ffmpeg", "-y",
                    "-i", clip_path,
                    "-vf", f"vidstabtransform=input={trf_path}:smoothing=10:optzoom=0,{base_vf}",
                    "-c:v", VIDEO_CODEC,
                    "-crf", VIDEO_CRF,
                    "-preset", VIDEO_PRESET,
                    "-an",
                    "-pix_fmt", "yuv420p",
                    norm_path,
                ]
                subprocess.run(
                    pass2_cmd,
                    capture_output=True, text=True, check=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                # Standard single-pass normalization
                cmd = [
                    "ffmpeg", "-y",
                    "-i", clip_path,
                    "-vf", base_vf,
                    "-c:v", VIDEO_CODEC,
                    "-crf", VIDEO_CRF,
                    "-preset", VIDEO_PRESET,
                    "-an",
                    "-pix_fmt", "yuv420p",
                    norm_path,
                ]
                subprocess.run(
                    cmd,
                    capture_output=True, text=True, check=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )

            normalized.append(norm_path)
            duration = get_video_duration(norm_path)
            local_logger.debug(f"  {'Stabilized' if stabilize else 'Normalized'}: {duration:.1f}s — {norm_path}")

        except subprocess.CalledProcessError as e:
            local_logger.warning(
                f"  ⚠️ Failed to {'stabilize' if stabilize else 'normalize'} clip {clip_name}: {e.stderr[-300:]}"
            )
            # Skip this clip rather than crashing the whole pipeline

    if not normalized:
        raise RuntimeError(
            "All clips failed to normalize.\n"
            "Check that FFmpeg is installed and the clip files are valid MP4s."
        )

    return normalized


def _build_shuffled_playlist(
    clips: list,
    target_duration_hours: float,
    blend_seconds: float,
    avg_duration: float,
) -> list:
    """
    Build a shuffled list of clip paths that fills the target duration.

    The playlist cycles through all clips in random order, re-shuffling
    each cycle. This creates natural variation — the viewer never sees
    the same animation sequence repeated in an obvious pattern.

    WHY re-shuffle each cycle? A fixed shuffle would repeat every ~20 minutes
    (10 clips × 2 min). Re-shuffling each cycle means the pattern never
    obviously repeats within the 2-3 hour video.

    Args:
        clips:                 List of clip paths (normalized).
        target_duration_hours: Target video length in hours.
        blend_seconds:         Crossfade duration (subtracts from each clip's contribution).
        avg_duration:          Average clip duration in seconds.

    Returns:
        List of clip paths in the order they should be assembled.
    """
    target_seconds = target_duration_hours * 3600

    # Each clip effectively contributes (duration - blend_seconds) to the total
    # because the last "blend_seconds" of each clip overlaps with the next clip
    # WHY subtract blend_seconds? With a 2-second crossfade, clip A's last 2 seconds
    # play simultaneously with clip B's first 2 seconds. So the net contribution
    # of each clip to the total runtime is (clip_duration - 2).
    effective_per_clip = max(avg_duration - blend_seconds, 1.0)

    total_clips_needed = math.ceil(target_seconds / effective_per_clip)

    # Add 10% buffer to ensure we definitely hit the target duration
    # (we'll trim the final video if needed, but never want to fall short)
    total_clips_needed = int(total_clips_needed * 1.1)

    local_logger = logging.getLogger("fairway.video_assembly")
    local_logger.debug(
        f"  Need {total_clips_needed} clip plays for {target_duration_hours}h "
        f"(effective {effective_per_clip:.1f}s/clip)"
    )

    # Build playlist by cycling through shuffled clips
    playlist = []
    clips_copy = clips.copy()

    while len(playlist) < total_clips_needed:
        # Shuffle the clips for this cycle
        random.shuffle(clips_copy)
        playlist.extend(clips_copy)

    # Trim to exactly the number we need
    return playlist[:total_clips_needed]


def _process_batches(
    playlist: list,
    clip_durations: dict,
    blend_seconds: float,
    batch_dir: str,
    local_logger,
) -> list:
    """
    Process the playlist in batches of BATCH_SIZE, applying xfade to each batch.

    WHY batches of 10? FFmpeg's filter_complex has limits on the number of
    simultaneous filter chains. With 60 clips (for a 2-hour video), we'd need
    59 xfade operations in one FFmpeg command — this overflows FFmpeg's internal
    buffers and causes errors. Processing 10 at a time (9 xfades per call)
    keeps each FFmpeg command manageable.

    Args:
        playlist:      Complete list of clip paths in order.
        clip_durations: Dict mapping clip path to duration in seconds.
        blend_seconds: Crossfade duration.
        batch_dir:     Directory to save batch output files.
        local_logger:  Logger.

    Returns:
        List of batch output file paths.
    """
    # Split the playlist into chunks of BATCH_SIZE
    chunks = [playlist[i:i+BATCH_SIZE] for i in range(0, len(playlist), BATCH_SIZE)]

    batch_files = []
    total_batches = len(chunks)

    for batch_idx, chunk in enumerate(chunks):
        batch_path = os.path.join(batch_dir, f"batch_{batch_idx:04d}.mp4")

        # Skip if this batch was already processed (resume support)
        if os.path.exists(batch_path):
            local_logger.debug(f"  Batch {batch_idx+1}/{total_batches} already exists, skipping")
            batch_files.append(batch_path)
            continue

        local_logger.info(f"  Batch {batch_idx+1}/{total_batches} ({len(chunk)} clips)...")

        if len(chunk) == 1:
            # Single clip batch — just copy it
            shutil.copy2(chunk[0], batch_path)
        else:
            # Multiple clips — apply xfade between each pair
            _apply_xfade_batch(
                clips=chunk,
                clip_durations=clip_durations,
                blend_seconds=blend_seconds,
                output_path=batch_path,
                local_logger=local_logger,
            )

        batch_files.append(batch_path)
        local_logger.debug(f"  Batch {batch_idx+1} done: {batch_path}")

    return batch_files


def _apply_xfade_batch(
    clips: list,
    clip_durations: dict,
    blend_seconds: float,
    output_path: str,
    local_logger,
):
    """
    Apply xfade crossfades between clips in a single batch using FFmpeg.

    This builds an FFmpeg filter_complex that chains xfade operations:
    [clip0][clip1] → xfade → [v01]
    [v01][clip2]  → xfade → [v012]
    ...etc

    The "offset" for each xfade is the point in the timeline when the
    crossfade should START. We calculate this by accumulating clip durations
    and subtracting the blend time for each crossfade already applied.

    Args:
        clips:         List of clip paths for this batch.
        clip_durations: Dict of clip path → duration in seconds.
        blend_seconds: Crossfade duration in seconds.
        output_path:   Where to save this batch's output.
        local_logger:  Logger.
    """
    n = len(clips)
    if n < 2:
        shutil.copy2(clips[0], output_path)
        return

    # Build the FFmpeg command
    # Start with input flags: -i clip1 -i clip2 -i clip3 ...
    input_flags = []
    for clip in clips:
        input_flags.extend(["-i", clip])

    # Build the filter_complex string
    # WHY filter_complex? For operations involving multiple input streams
    # (which xfade requires), FFmpeg needs the filter_complex argument.
    # It's FFmpeg's way of describing a graph of video processing operations.

    filter_parts = []
    accumulated_offset = 0.0
    prev_label = "[0:v]"  # The first clip's video stream

    for i in range(1, n):
        # Duration of the clip we're transitioning FROM
        clip_duration = clip_durations.get(clips[i-1], 10.0)

        # Offset = when this crossfade starts in the output timeline
        # We subtract blend_seconds because the previous xfade already
        # trimmed blend_seconds from the effective length
        accumulated_offset += clip_duration - blend_seconds

        # Label for the output of this xfade operation
        # The last xfade outputs to [outv] (our final output stream)
        out_label = "[outv]" if i == n - 1 else f"[v{i}]"

        # The xfade filter:
        # transition=fade: simple dissolve between clips
        # duration: how long the crossfade lasts
        # offset: when in the output timeline the crossfade begins
        #
        # WHY "fade" transition? It's the most invisible for our use case.
        # Since all clips share the same composition, a fade just blends
        # the animation motion — it looks like natural wind variation.
        filter_parts.append(
            f"{prev_label}[{i}:v]xfade=transition=fade:"
            f"duration={blend_seconds}:offset={accumulated_offset:.3f}{out_label}"
        )
        prev_label = out_label

    filter_complex = ";".join(filter_parts)

    cmd = [
        "ffmpeg", "-y",
    ] + input_flags + [
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-c:v", VIDEO_CODEC,
        "-crf", VIDEO_CRF,
        "-preset", VIDEO_PRESET,
        "-pix_fmt", "yuv420p",
        output_path,
    ]

    local_logger.debug(
        f"  FFmpeg xfade: {n} clips, offsets up to {accumulated_offset:.1f}s"
    )

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"FFmpeg xfade failed for batch:\n"
            f"Command: {' '.join(cmd[:10])}...\n"
            f"Error: {e.stderr[-500:]}\n"
            "Try checking that all input clips are valid MP4 files."
        )


def _concatenate_batches(
    batch_files: list,
    blend_seconds: float,
    output_path: str,
    local_logger,
    _depth: int = 0,
):
    """
    Concatenate batch files into the final video using recursive xfade batching.

    WHY recursive? FFmpeg's xfade filter supports at most ~10 inputs per call
    (9 xfade operations). A 2-hour video produces ~260 batch files, so we can't
    xfade them all in one pass.

    Solution — recursive batching:
      Level 0: batch_files → super-batches in _sb_0_<name>/ (BATCH_SIZE each, xfaded)
      Level 1: super-batches → super-super-batches in _sb_1_<name>/ (if still > BATCH_SIZE)
      ...until ≤ BATCH_SIZE files remain, then xfade directly to output_path.

    WHY depth-based subdirectories? Without them, each recursion level would try to
    create files with the same names, find the previous level's files already there,
    skip them, and join only BATCH_SIZE segments instead of all of them — producing a
    video far shorter than the target duration.

    Args:
        batch_files:   List of batch video paths.
        blend_seconds: Crossfade duration between segments.
        output_path:   Final output video path.
        local_logger:  Logger.
        _depth:        Internal recursion depth (do not pass manually).
    """
    n = len(batch_files)
    local_logger.info(f"  Joining {n} batches with crossfades (depth={_depth})...")

    if n <= BATCH_SIZE:
        # Small enough to xfade in a single pass
        batch_durations = {p: get_video_duration(p) for p in batch_files}
        _apply_xfade_batch(
            clips=batch_files,
            clip_durations=batch_durations,
            blend_seconds=blend_seconds,
            output_path=output_path,
            local_logger=local_logger,
        )
        return

    # More than BATCH_SIZE files — group them into super-batches and xfade each group,
    # then recursively join the resulting super-batch files.
    #
    # Use a depth-specific subdirectory so that each recursion level writes to a
    # unique location. Without this, level N+1 would find level N's files already
    # on disk (same name pattern), skip creating them, and join only BATCH_SIZE
    # segments instead of all — producing a truncated video.
    base_name = os.path.basename(output_path).replace('.mp4', '')
    super_batch_dir = os.path.join(
        os.path.dirname(output_path), f"_sb_{_depth}_{base_name}"
    )
    os.makedirs(super_batch_dir, exist_ok=True)

    super_batch_files = []
    chunks = [batch_files[i:i+BATCH_SIZE] for i in range(0, n, BATCH_SIZE)]
    total = len(chunks)

    for idx, chunk in enumerate(chunks):
        super_path = os.path.join(super_batch_dir, f"part_{idx:04d}.mp4")

        if os.path.exists(super_path):
            local_logger.debug(f"  Super-batch {idx+1}/{total} already exists, skipping")
            super_batch_files.append(super_path)
            continue

        local_logger.info(f"  Super-batch {idx+1}/{total} ({len(chunk)} segments)...")
        chunk_durations = {p: get_video_duration(p) for p in chunk}
        _apply_xfade_batch(
            clips=chunk,
            clip_durations=chunk_durations,
            blend_seconds=blend_seconds,
            output_path=super_path,
            local_logger=local_logger,
        )
        super_batch_files.append(super_path)

    # Recursively join the super-batches, incrementing depth so the next level
    # uses a different subdirectory and avoids the naming collision.
    local_logger.info(f"  Joining {len(super_batch_files)} super-batches...")
    _concatenate_batches(
        batch_files=super_batch_files,
        blend_seconds=blend_seconds,
        output_path=output_path,
        local_logger=local_logger,
        _depth=_depth + 1,
    )


def get_video_duration(video_path: str) -> float:
    """
    Get the duration of a video file in seconds using FFprobe.

    FFprobe is a companion tool to FFmpeg that reads media file metadata.
    It ships with FFmpeg — if FFmpeg is installed, FFprobe is too.

    Args:
        video_path: Path to the video file.

    Returns:
        Duration in seconds (as a float, e.g., 119.967).

    Raises:
        RuntimeError: If FFprobe fails or the file doesn't exist.
    """
    if not os.path.exists(video_path):
        raise RuntimeError(f"Video file not found: {video_path}")

    cmd = [
        "ffprobe",
        "-v", "quiet",                          # Suppress verbose output
        "-show_entries", "format=duration",     # Only show duration
        "-of", "json",                           # Output as JSON for easy parsing
        video_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        data = json.loads(result.stdout)
        duration = float(data["format"]["duration"])
        return duration
    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError, ValueError) as e:
        # Fallback: try with ffmpeg itself if ffprobe fails
        try:
            result = subprocess.run(
                ["ffprobe", "-i", video_path, "-show_entries", "format=duration",
                 "-v", "quiet", "-of", "csv=p=0"],
                capture_output=True, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return float(result.stdout.strip())
        except Exception:
            # Last resort: assume a default duration
            logger.warning(
                f"  ⚠️ Couldn't read duration of {video_path}, assuming 10s"
            )
            return 10.0


# Allow running this module directly for testing:
# python -m pipeline.video_assembly --input-dir ./test/ --duration 0.05
if __name__ == "__main__":
    import sys
    import glob

    print("\nTesting video assembly...")

    test_dir = sys.argv[1] if len(sys.argv) > 1 else "./runs"
    test_clips = glob.glob(os.path.join(test_dir, "**", "clip_*.mp4"), recursive=True)

    if not test_clips:
        print(f"No test clips found in {test_dir}")
        sys.exit(1)

    print(f"Found {len(test_clips)} clips. Assembling 3-minute test video...")

    result = assemble_living_painting(
        clip_paths=test_clips[:3],  # Use just 3 clips for the test
        target_duration_hours=0.05,  # 3 minutes
        blend_seconds=2,
        run_dir="./test_assembly",
        norm_dir="./test_assembly/normalized",
    )

    print(f"✓ Test video: {result}")
