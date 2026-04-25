#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# =============================================================================
# fairway.py — Fairway Frequencies Main Entry Point
# =============================================================================
# This is the file you run. Everything starts here.
#
# BASIC USAGE:
#   python fairway.py "Misty dawn, links-style course, coastal cliffs"
#
# COMMON OPTIONS:
#   python fairway.py "scene description"           # Standard 2-hour video
#   python fairway.py "scene" --duration 3.0        # 3-hour video
#   python fairway.py "scene" --no-ambience         # Music only, no golf sounds
#   python fairway.py "scene" --character always    # Always show a character
#   python fairway.py "scene" --character never     # Landscape only
#   python fairway.py "scene" --images flux         # Use Flux API instead of MJ
#   python fairway.py "scene" --upload              # Upload to YouTube after
#   python fairway.py --random                      # Random scene from library
#   python fairway.py --list-scenes                 # Show all 20 pre-built scenes
#   python fairway.py --prompts-only "scene"        # Just print Midjourney prompt
#   python fairway.py --resume RUN_ID               # Resume a failed run
#   python fairway.py --test                        # Quick 3-minute smoke test
# =============================================================================

import argparse           # For parsing command-line arguments like --duration
import sys                # For sys.exit() when something goes wrong

# Fix Windows terminal encoding so special characters don't crash the script.
# WHY: Windows uses cp1252 encoding by default, which can't display certain
# Unicode characters. Setting UTF-8 makes everything work correctly.
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
import os                 # For file/folder operations
import json               # For reading/writing JSON data files
import logging            # For writing progress messages to console and log file
import time               # For timestamps and tracking how long things take
import random             # For picking random scenes from the library
import threading          # For running video and audio pipelines in parallel
import shutil             # For copying files
from pathlib import Path  # For working with file paths in a clean way
from datetime import datetime  # For creating timestamped run folders

# Import our configuration settings from config.py
import config

# Import all the pipeline stage modules from the pipeline/ folder
# Each module handles one stage of the production process
from pipeline.orchestrator import decompose_prompt, generate_scene_prompt, get_current_art_style
from pipeline.video_import import import_video_clips
from pipeline.video_assembly import assemble_living_painting
from pipeline.music_gen import get_music_track
from pipeline.ambient_sounds import download_ambient_sounds
from pipeline.audio_assembly import assemble_audio
from pipeline.final_render import render_final_video
from pipeline.metadata_gen import generate_metadata
from pipeline.thumbnail_gen import generate_thumbnail
from pipeline.youtube_upload import upload_to_youtube, list_channel_playlists
from pipeline.shorts_gen import generate_shorts as generate_shorts_stage
from pipeline.shorts_scheduler import (
    schedule_weeks, seed_tracker, print_tracker_summary,
    backfill_video_links, print_backfill_report,
    import_channel_videos, print_import_report,
    reset_scheduled_shorts,
)
from pipeline.scene_tracker import log_scene_use


# =============================================================================
# LOGGING SETUP
# =============================================================================
def setup_logging(run_dir: str) -> logging.Logger:
    """
    Set up logging to both the console and a log file.

    WHY two outputs? The console shows you real-time progress while the
    pipeline runs. The log file saves everything for later debugging if
    something went wrong. Console shows INFO level (the important stuff).
    The file captures DEBUG level (everything, including gory details).

    Args:
        run_dir: The folder for this specific run — log file goes here.

    Returns:
        A configured Logger object.
    """
    logger = logging.getLogger("fairway")
    logger.setLevel(logging.DEBUG)  # Capture everything at the logger level

    # Console handler — shows INFO and above (INFO, WARNING, ERROR, CRITICAL)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S"  # Short time format for console readability
    )
    console_handler.setFormatter(console_format)

    # File handler — saves DEBUG and above (everything) to a log file
    os.makedirs(run_dir, exist_ok=True)  # Create the run directory if needed
    log_file = os.path.join(run_dir, "generation.log")
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_format = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"  # Full timestamp in the log file
    )
    file_handler.setFormatter(file_format)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger


# =============================================================================
# STARTUP CHECKS
# =============================================================================
def check_requirements(args) -> bool:
    """
    Verify that everything needed to run is in place before we start.

    WHY check upfront? It's frustrating to run a pipeline for 20 minutes
    and then have it crash because FFmpeg isn't installed. We check everything
    at the start so you get one clear list of what's missing.

    Args:
        args: The parsed command-line arguments.

    Returns:
        True if all checks pass, False if something is missing.
    """
    all_ok = True
    issues = []

    # Check FFmpeg is installed — it's required for all video assembly
    if shutil.which("ffmpeg") is None:
        issues.append(
            "FFmpeg is not installed or not in your PATH.\n"
            "  Windows: winget install Gyan.FFmpeg  (then restart your terminal)\n"
            "  Mac:     brew install ffmpeg\n"
            "  Linux:   sudo apt install ffmpeg"
        )
        all_ok = False

    # Check the Anthropic API key — required for prompt decomposition
    if not config.ANTHROPIC_API_KEY:
        issues.append(
            "ANTHROPIC_API_KEY is not set.\n"
            "  1. Copy .env.example to .env\n"
            "  2. Add your key from https://console.anthropic.com/"
        )
        all_ok = False

    # Print all issues at once for a clean experience
    if issues:
        print("\n❌ Setup issues found. Please fix these before running:\n")
        for i, issue in enumerate(issues, 1):
            print(f"  {i}. {issue}\n")

    return all_ok


# =============================================================================
# RESUME SUPPORT
# =============================================================================
def load_state(run_dir: str) -> dict:
    """
    Load the saved state from a previous interrupted run.

    WHY: API calls take minutes each. If the pipeline crashes at Stage 7,
    you don't want to regenerate all the images and video clips from scratch.
    We save state after each stage so --resume can pick up where we left off.

    Args:
        run_dir: The run directory containing a .state.json file.

    Returns:
        A dict with the saved state, or an empty dict if no state found.
    """
    state_file = os.path.join(run_dir, ".state.json")
    if os.path.exists(state_file):
        with open(state_file, "r") as f:
            return json.load(f)
    return {}


def save_state(run_dir: str, state: dict):
    """
    Save the current pipeline state to disk after each completed stage.

    Args:
        run_dir: The run directory.
        state: Dict of completed stages and their outputs.
    """
    state_file = os.path.join(run_dir, ".state.json")
    with open(state_file, "w") as f:
        json.dump(state, f, indent=2)


# =============================================================================
# SCENE LIBRARY
# =============================================================================
def load_scene_library() -> list:
    """
    Load the pre-built scene library from prompts/scene_library.json.

    WHY a scene library? Having 20 ready-to-go scene prompts means you can
    run the pipeline with --random and it just works. Great for scheduled
    automated production.

    Returns:
        A list of scene dicts with 'name', 'description', and 'mood' keys.
    """
    library_path = os.path.join("prompts", "scene_library.json")
    if not os.path.exists(library_path):
        print(
            f"\n⚠️  Scene library not found at {library_path}\n"
            "  Make sure you have the prompts/ folder with scene_library.json"
        )
        return []

    with open(library_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data.get("scenes", [])


# =============================================================================
# FRAME EXTRACTION — thumbnail base image from a video clip
# =============================================================================
def _extract_frame_from_clip(clip_path: str, run_dir: str, logger: logging.Logger) -> str:
    """
    Extract a single frame from the middle of a video clip to use as the
    thumbnail base image (replaces the old Midjourney base image).

    Args:
        clip_path: Path to the source MP4 clip.
        run_dir:   Current run directory (frame saved here).
        logger:    Logger for progress messages.

    Returns:
        Path to the extracted PNG frame.
    """
    import subprocess, json as _json

    output_path = os.path.join(run_dir, "base_image.png")

    # Get clip duration with ffprobe
    probe_cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "json", clip_path,
    ]
    try:
        result = subprocess.run(probe_cmd, capture_output=True, text=True, check=True,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        duration = float(_json.loads(result.stdout)["format"]["duration"])
    except Exception:
        duration = 5.0  # Fallback if ffprobe fails

    seek_time = duration * 0.5  # Extract from the middle of the clip

    extract_cmd = [
        "ffmpeg", "-y",
        "-ss", str(seek_time),
        "-i", clip_path,
        "-vframes", "1",
        "-q:v", "2",
        output_path,
    ]
    try:
        subprocess.run(extract_cmd, capture_output=True, text=True, check=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        logger.info(f"  ✓ Thumbnail base frame extracted from: {os.path.basename(clip_path)}")
    except subprocess.CalledProcessError as e:
        logger.warning(f"  ⚠️ Frame extraction failed: {e.stderr[-200:]}")

    return output_path


# =============================================================================
# INTERMEDIATE FILE CLEANUP
# =============================================================================
def _cleanup_intermediates(run_dir: str, logger: logging.Logger):
    """
    Delete large intermediate files after a successful final render.

    The batch files and assembled video are only needed during production.
    Once the final MP4 exists, these can be safely removed to reclaim disk space.

    Keeps: generation.log, .state.json, base_image.png, audio/final_audio.wav
    Deletes: batches/ folder, assembled_video.mp4, audio/music_looped.wav
    """
    freed = 0

    # Delete the batches folder (260 MP4s — by far the biggest space hog)
    batches_dir = os.path.join(run_dir, "batches")
    if os.path.exists(batches_dir):
        size = sum(os.path.getsize(f) for f in Path(batches_dir).glob("**/*") if f.is_file())
        shutil.rmtree(batches_dir)
        freed += size
        logger.debug(f"  Deleted batches/: {size / (1024**3):.2f}GB freed")

    # Delete the assembled video (video-only, before audio was added)
    assembled = os.path.join(run_dir, "assembled_video.mp4")
    if os.path.exists(assembled):
        size = os.path.getsize(assembled)
        os.remove(assembled)
        freed += size
        logger.debug(f"  Deleted assembled_video.mp4: {size / (1024**3):.2f}GB freed")

    # Delete the intermediate looped music file
    looped = os.path.join(run_dir, "audio", "music_looped.wav")
    if os.path.exists(looped):
        size = os.path.getsize(looped)
        os.remove(looped)
        freed += size
        logger.debug(f"  Deleted music_looped.wav: {size / (1024**2):.0f}MB freed")

    logger.info(f"  ✓ Cleaned up intermediates: {freed / (1024**3):.2f}GB freed")


# =============================================================================
# MAIN PIPELINE
# =============================================================================
def run_pipeline(prompt: str, args, run_dir: str, logger: logging.Logger, state: dict):
    """
    Execute the full Fairway Frequencies production pipeline.

    This is the heart of the application. It runs all 11 stages in order,
    saving state after each one. Video (Stages 2–4) and audio (Stages 5–6)
    run in parallel threads to save time, joining back together at Stage 7.

    Args:
        prompt:  The scene description (e.g., "Misty dawn links course").
        args:    Parsed CLI arguments.
        run_dir: Path to this run's working directory.
        logger:  The logger for progress messages.
        state:   Previously saved state (empty dict for fresh runs).
    """
    # Determine active settings — CLI args override config.py values
    include_ambience = not getattr(args, 'no_ambience', False) and config.INCLUDE_AMBIENCE
    character_mode = getattr(args, 'character', None) or config.INCLUDE_CHARACTER
    target_hours = getattr(args, 'duration', None) or config.TARGET_DURATION_HOURS

    # Create subdirectories inside this run's folder
    clips_dir = os.path.join(run_dir, "clips")      # Raw video clips go here
    norm_dir = os.path.join(run_dir, "normalized")  # Normalized clips go here
    audio_dir = os.path.join(run_dir, "audio")      # Music and ambience files
    os.makedirs(clips_dir, exist_ok=True)
    os.makedirs(norm_dir, exist_ok=True)
    os.makedirs(audio_dir, exist_ok=True)

    # Output directory — scoped to the clip folder when one is specified.
    # E.g. --clips-folder Video_6 → all outputs land in output/Video_6/
    # This keeps finished videos, metadata, thumbnails, and Shorts for each
    # scene together in one place rather than mixed in the root output/ folder.
    clips_folder_name = getattr(args, 'clips_folder', None)
    run_output_dir = (
        os.path.join(config.OUTPUT_DIR, clips_folder_name)
        if clips_folder_name
        else config.OUTPUT_DIR
    )
    os.makedirs(run_output_dir, exist_ok=True)

    start_time = time.time()

    # =========================================================================
    # STAGE 1: ORCHESTRATOR
    # =========================================================================
    if "orchestration" not in state:
        logger.info("━" * 60)
        logger.info("[Stage 1/10] Decomposing scene prompt with Claude...")
        logger.info(f"  Scene: \"{prompt}\"")

        art_style = get_current_art_style()
        orchestration = decompose_prompt(
            scene_prompt=prompt,
            character_mode=character_mode,
            style_suffix=art_style["style_suffix"],
            animation_variations=config.ANIMATION_VARIATIONS,
            art_style=art_style,
        )

        state["orchestration"] = orchestration
        save_state(run_dir, state)
        logger.info("  ✓ Orchestration complete")
        logger.debug(f"  Orchestration result: {json.dumps(orchestration, indent=2)}")
    else:
        logger.info("[Stage 1/10] Orchestration — loaded from saved state")
        orchestration = state["orchestration"]

    # =========================================================================
    # STAGES 2–3 (video) and STAGES 4–5 (audio) run IN PARALLEL
    # =========================================================================
    video_result = {}
    audio_result = {}
    video_error = []
    audio_error = []

    def run_video_pipeline():
        """Run Stages 2 and 3: import clips, then assemble the full video."""
        try:
            # === STAGE 2: VIDEO CLIP IMPORT ===
            if "animation_clips" not in state:
                logger.info("━" * 60)
                logger.info(f"[Stage 2/10] Importing video clips...")
                logger.info(f"  Looking in: {config.VIDEO_CLIPS_DIR}")

                clip_paths = import_video_clips(
                    clips_dir=clips_dir,
                    logger=logger,
                    clips_subfolder=getattr(args, 'clips_folder', None),
                )

                state["animation_clips"] = clip_paths
                save_state(run_dir, state)
                logger.info(f"  ✓ {len(clip_paths)} clips ready")
            else:
                logger.info("[Stage 2/10] Video clips — loaded from saved state")
                clip_paths = state["animation_clips"]

            # === STAGE 3: VIDEO ASSEMBLY ===
            if "assembled_video" not in state:
                logger.info("━" * 60)
                logger.info("[Stage 3/10] Assembling living painting (seamless loop)...")
                logger.info(f"  Target duration: {target_hours} hours")
                logger.info(f"  Loop blend: {config.LOOP_BLEND_SECONDS}s crossfades between clips")

                assembled_video_path = assemble_living_painting(
                    clip_paths=clip_paths,
                    target_duration_hours=target_hours,
                    blend_seconds=config.LOOP_BLEND_SECONDS,
                    run_dir=run_dir,
                    norm_dir=norm_dir,
                    stabilize=getattr(args, "stabilize", False),
                    logger=logger,
                )

                state["assembled_video"] = assembled_video_path
                save_state(run_dir, state)
                logger.info(f"  ✓ Video assembled: {assembled_video_path}")
            else:
                logger.info("[Stage 3/10] Assembled video — loaded from saved state")
                assembled_video_path = state["assembled_video"]

            video_result["path"] = assembled_video_path
            video_result["clips"] = clip_paths

        except Exception as e:
            video_error.append(e)
            logger.error(f"  ✗ Video pipeline failed: {e}")
            raise

    def run_audio_pipeline():
        """Run Stages 4 and 5: get music track and ambient sounds."""
        try:
            ab_test = getattr(args, 'ab_test', False)

            # === STAGE 4: MUSIC GENERATION ===
            # In AB test mode this is skipped here and run per-genre after the
            # threads join, so each genre gets its own music track in isolation.
            if not ab_test:
                if "music_track" not in state:
                    logger.info("━" * 60)
                    logger.info("[Stage 4/10] Getting LoFi music track...")

                    music_path, boundaries_path = get_music_track(
                        music_prompt=orchestration["music_prompt"],
                        target_duration_hours=target_hours,
                        audio_dir=audio_dir,
                        api_key=config.MUBERT_API_KEY,
                        logger=logger,
                    )

                    state["music_track"] = music_path
                    if boundaries_path:
                        state["song_boundaries"] = boundaries_path
                    save_state(run_dir, state)
                    logger.info(f"  ✓ Music ready: {music_path}")
                else:
                    logger.info("[Stage 4/10] Music track — loaded from saved state")

            audio_result["music"] = state.get("music_track")

            # === STAGE 5: AMBIENT SOUNDS ===
            ambient_path = None
            if include_ambience:
                if "ambient_sounds" not in state:
                    logger.info("━" * 60)
                    logger.info("[Stage 5/10] Downloading ambient golf course sounds...")

                    ambient_path = download_ambient_sounds(
                        keywords=orchestration["ambience_keywords"],
                        target_duration_hours=target_hours,
                        audio_dir=audio_dir,
                        api_key=config.FREESOUND_API_KEY,
                        logger=logger,
                    )

                    state["ambient_sounds"] = ambient_path
                    save_state(run_dir, state)
                    logger.info(f"  ✓ Ambient sounds ready: {ambient_path}")
                else:
                    logger.info("[Stage 5/10] Ambient sounds — loaded from saved state")
                    ambient_path = state["ambient_sounds"]
            else:
                logger.info("[Stage 5/10] Ambient sounds — skipped (--no-ambience or disabled in config)")

            audio_result["ambient"] = ambient_path

        except Exception as e:
            audio_error.append(e)
            logger.error(f"  ✗ Audio pipeline failed: {e}")
            raise

    # Start both pipelines in separate threads
    logger.info("\n  Starting video and audio pipelines in parallel...")
    video_thread = threading.Thread(target=run_video_pipeline, name="VideoThread")
    audio_thread = threading.Thread(target=run_audio_pipeline, name="AudioThread")

    video_thread.start()
    audio_thread.start()

    # Wait for BOTH to finish before continuing
    # .join() blocks this thread until the target thread completes
    video_thread.join()
    audio_thread.join()

    # Check if either thread had an error
    if video_error:
        logger.error(f"\n✗ Video pipeline failed: {video_error[0]}")
        sys.exit(1)
    if audio_error:
        logger.error(f"\n✗ Audio pipeline failed: {audio_error[0]}")
        sys.exit(1)

    assembled_video_path = video_result["path"]
    clip_paths = video_result["clips"]
    ambient_path = audio_result.get("ambient")

    # =========================================================================
    # FRAME EXTRACTION — thumbnail base image from the first video clip
    # =========================================================================
    if "base_image" not in state:
        base_image_path = _extract_frame_from_clip(clip_paths[0], run_dir, logger)
        state["base_image"] = base_image_path
        save_state(run_dir, state)
    else:
        base_image_path = state["base_image"]

    # =========================================================================
    # PER-GENRE PIPELINE CLOSURE (stages 4, 6-11)
    # =========================================================================
    # This closure runs for each genre in AB test mode, or once with genre=None
    # in normal mode.  Using a closure keeps all local variables in scope without
    # passing a huge argument list.
    #
    # State namespacing:
    #   Normal mode   → gstate = state            (same flat dict as always)
    #   AB test mode  → gstate = state["ab_genres"][genre]  (per-genre sub-dict)
    # =========================================================================
    def _run_for_genre(genre):
        """
        Run stages 4, 6-11 for a specific music genre (or None = all tracks).

        Returns:
            (final_video_path, thumbnail_path, metadata, shorts_result)
        """
        genre_label = genre or "all tracks"
        genre_lower = genre.lower() if genre else None
        tag = f" ({genre})" if genre else ""

        # Genre-specific state namespace
        if genre:
            gstate = state.setdefault("ab_genres", {}).setdefault(genre, {})
        else:
            gstate = state

        # Genre-specific audio subdirectory
        g_audio_dir = os.path.join(audio_dir, genre_lower) if genre else audio_dir
        os.makedirs(g_audio_dir, exist_ok=True)

        # =================================================================
        # STAGE 4: MUSIC
        # =================================================================
        if "music_track" not in gstate:
            logger.info("━" * 60)
            logger.info(f"[Stage 4] Getting LoFi music track{tag}...")

            music_path, boundaries_path = get_music_track(
                music_prompt=orchestration["music_prompt"],
                target_duration_hours=target_hours,
                audio_dir=g_audio_dir,
                api_key=config.MUBERT_API_KEY,
                genre=genre,
                logger=logger,
            )

            gstate["music_track"] = music_path
            if boundaries_path:
                gstate["song_boundaries"] = boundaries_path
            save_state(run_dir, state)
            logger.info(f"  ✓ Music ready: {music_path}")
        else:
            logger.info(f"[Stage 4] Music track — loaded from saved state{tag}")
            music_path = gstate["music_track"]

        # =================================================================
        # STAGE 6: AUDIO ASSEMBLY
        # =================================================================
        if "mixed_audio" not in gstate:
            logger.info("━" * 60)
            logger.info(f"[Stage 6] Mixing music and ambient sounds{tag}...")

            mixed_audio_path = assemble_audio(
                music_path=music_path,
                ambient_path=ambient_path,
                target_duration_hours=target_hours,
                music_volume=config.MUSIC_VOLUME,
                ambience_volume=config.AMBIENCE_VOLUME,
                audio_dir=g_audio_dir,
                logger=logger,
            )

            gstate["mixed_audio"] = mixed_audio_path
            save_state(run_dir, state)
            logger.info(f"  ✓ Mixed audio ready: {mixed_audio_path}")
        else:
            logger.info(f"[Stage 6] Mixed audio — loaded from saved state{tag}")
            mixed_audio_path = gstate["mixed_audio"]

        # =================================================================
        # STAGE 7: FINAL RENDER
        # =================================================================
        if "final_video" not in gstate:
            logger.info("━" * 60)
            logger.info(f"[Stage 7] Rendering final video{tag}...")

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_prompt = "".join(c if c.isalnum() or c == "_" else "_" for c in prompt[:30])
            genre_suffix = f"_{genre_lower}" if genre else ""
            output_filename = f"fairway_{safe_prompt}_{timestamp}{genre_suffix}.mp4"
            output_path = os.path.join(run_output_dir, output_filename)
            os.makedirs(run_output_dir, exist_ok=True)

            final_video_path = render_final_video(
                video_path=assembled_video_path,
                audio_path=mixed_audio_path,
                output_path=output_path,
                logger=logger,
            )

            gstate["final_video"] = final_video_path
            save_state(run_dir, state)
            logger.info(f"  ✓ Final video: {final_video_path}")
        else:
            logger.info(f"[Stage 7] Final video — loaded from saved state{tag}")
            final_video_path = gstate["final_video"]

        # =================================================================
        # STAGE 8: METADATA
        # =================================================================
        if "metadata" not in gstate:
            logger.info("━" * 60)
            logger.info(f"[Stage 8] Generating YouTube title, description, and tags{tag}...")

            metadata = generate_metadata(
                scene_prompt=prompt,
                orchestration=orchestration,
                duration_hours=target_hours,
                image_path=base_image_path,
                api_key=config.ANTHROPIC_API_KEY,
                claude_model=config.CLAUDE_MODEL,
                genre=genre,
                logger=logger,
            )

            metadata_path = final_video_path.replace(".mp4", "_metadata.json")
            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)

            txt_path = final_video_path.replace(".mp4", "_metadata.txt")
            tags_line = ", ".join(metadata.get("tags", []))
            txt_content = (
                f"TITLE:\n{metadata.get('title', '')}\n\n"
                f"DESCRIPTION:\n{metadata.get('description', '')}\n\n"
                f"TAGS:\n{tags_line}\n\n"
                f"THUMBNAIL TEXT:\n{metadata.get('thumbnail_text', '')}\n"
            )
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(txt_content)

            gstate["metadata"] = metadata
            save_state(run_dir, state)
            logger.info(f"  ✓ Title: {metadata['title']}")
        else:
            logger.info(f"[Stage 8] Metadata — loaded from saved state{tag}")
            metadata = gstate["metadata"]

        # =================================================================
        # STAGE 9: THUMBNAIL
        # =================================================================
        if "thumbnail" not in gstate:
            logger.info("━" * 60)
            logger.info(f"[Stage 9] Generating thumbnail{tag}...")

            thumbnail_path = generate_thumbnail(
                base_image_path=base_image_path,
                thumbnail_prompt=orchestration.get("thumbnail_prompt", orchestration["image_prompt"]),
                run_dir=run_dir,
                output_dir=run_output_dir,
                final_video_path=final_video_path,
                api_key=config.BFL_API_KEY,
                metadata=metadata,
                logger=logger,
            )

            gstate["thumbnail"] = thumbnail_path
            save_state(run_dir, state)
            logger.info(f"  ✓ Thumbnail: {thumbnail_path}")
        else:
            logger.info(f"[Stage 9] Thumbnail — loaded from saved state{tag}")
            thumbnail_path = gstate["thumbnail"]

        # =================================================================
        # STAGE 10: YOUTUBE UPLOAD (OPTIONAL)
        # =================================================================
        if getattr(args, 'upload', False):
            logger.info("━" * 60)
            logger.info(f"[Stage 10] Uploading to YouTube{tag}...")
            v_stem = os.path.splitext(os.path.basename(final_video_path))[0]
            stem_prefix = v_stem
            for _suffix in ("_jazz", "_hiphop"):
                if stem_prefix.endswith(_suffix):
                    stem_prefix = stem_prefix[: -len(_suffix)]
                    break
            upload_to_youtube(
                video_path=final_video_path,
                thumbnail_path=thumbnail_path,
                metadata=metadata,
                client_id=config.YOUTUBE_CLIENT_ID,
                client_secret=config.YOUTUBE_CLIENT_SECRET,
                logger=logger,
                video_stem=v_stem,
                scene_stem_prefix=stem_prefix,
                genre=genre,
                scene_prompt=prompt,
                playlists=config.YOUTUBE_PLAYLISTS,
            )
            logger.info("  ✓ Upload complete")
        else:
            logger.info(f"[Stage 10] YouTube upload — skipped{tag}")

        # =================================================================
        # STAGE 11: YOUTUBE SHORTS
        # =================================================================
        shorts_enabled = getattr(args, 'shorts', True) and config.SHORTS_ENABLED
        shorts_result = None
        if shorts_enabled:
            if "shorts" not in gstate:
                logger.info("━" * 60)
                logger.info(f"[Stage 11] Generating YouTube Shorts{tag}...")

                shorts_result = generate_shorts_stage(
                    final_video_path=final_video_path,
                    run_dir=run_dir,
                    boundaries_path=gstate.get("song_boundaries"),
                    metadata=metadata,
                    output_dir=run_output_dir,
                    logger=logger,
                )

                gstate["shorts"] = shorts_result
                save_state(run_dir, state)
            else:
                logger.info(f"[Stage 11] YouTube Shorts — loaded from saved state{tag}")
                shorts_result = gstate["shorts"]
        else:
            logger.info(f"[Stage 11] YouTube Shorts — skipped{tag}")

        return final_video_path, thumbnail_path, metadata, shorts_result

    # =========================================================================
    # DISPATCH — AB test mode or normal single-genre run
    # =========================================================================
    ab_test = getattr(args, 'ab_test', False)

    if ab_test:
        # AB test: generate one video per genre, sharing the assembled video
        state.setdefault("ab_genres", {})
        save_state(run_dir, state)
        genre_results = {}
        for genre in config.AB_TEST_GENRES:
            logger.info("\n" + "━" * 60)
            logger.info(f"  A/B TEST — {genre} variant")
            logger.info("━" * 60)
            genre_results[genre] = _run_for_genre(genre)

        # Clean up shared intermediates after all genres are done
        _cleanup_intermediates(run_dir, logger)

        # Summary
        try:
            log_scene_use(prompt, scene_library=load_scene_library())
        except Exception:
            pass

        elapsed = time.time() - start_time
        logger.info("\n" + "=" * 60)
        logger.info("  FAIRWAY FREQUENCIES -- A/B Test Complete!")
        logger.info("=" * 60)
        logger.info(f"  Scene:    {prompt[:50]}...")
        logger.info(f"  Duration: {target_hours} hours")
        logger.info(f"  Runtime:  {elapsed / 60:.1f} minutes")
        for genre, (fvp, tp, md, sr) in genre_results.items():
            logger.info(f"  [{genre}] Video:     {fvp}")
            logger.info(f"  [{genre}] Thumbnail: {tp}")
            logger.info(f"  [{genre}] Title:     {md.get('title', 'N/A')}")
            if sr:
                logger.info(f"  [{genre}] Shorts:    {sr['count']} clips in {sr['output_dir']}")
        logger.info("=" * 60)
        logger.info("\nBoth genre variants are ready!")

    else:
        # Normal mode: single run using all tracks across all genre folders
        final_video_path, thumbnail_path, metadata, shorts_result = _run_for_genre(None)
        _cleanup_intermediates(run_dir, logger)

        # Summary
        try:
            log_scene_use(prompt, scene_library=load_scene_library())
        except Exception:
            pass

        elapsed = time.time() - start_time
        logger.info("\n" + "=" * 60)
        logger.info("  FAIRWAY FREQUENCIES -- Production Complete!")
        logger.info("=" * 60)
        logger.info(f"  Scene:     {prompt[:50]}...")
        logger.info(f"  Video:     {final_video_path}")
        logger.info(f"  Thumbnail: {thumbnail_path}")
        logger.info(f"  Duration:  {target_hours} hours")
        logger.info(f"  Runtime:   {elapsed / 60:.1f} minutes")
        logger.info(f"  Title:     {metadata.get('title', 'N/A')}")
        if shorts_result:
            logger.info(f"  Shorts:    {shorts_result['count']} clips in {shorts_result['output_dir']}")
        logger.info("=" * 60)
        logger.info("\nYour video is ready to upload!")


# =============================================================================
# ARGUMENT PARSING
# =============================================================================
def parse_args():
    """
    Define and parse all command-line arguments.

    WHY argparse? It automatically handles --help, type checking, and
    gives users a clean interface without us writing parsing code manually.

    Returns:
        Parsed arguments object. Access values like args.duration, args.upload, etc.
    """
    parser = argparse.ArgumentParser(
        prog="fairway",
        description=(
            "Fairway Frequencies — AI-Automated LoFi Golf YouTube Channel\n"
            "Generates 2–3 hour living painting videos from your video clips.\n"
            "\nExamples:\n"
            "  python fairway.py \"Misty dawn, links course, coastal cliffs\"\n"
            "  python fairway.py \"scene\" --clips-folder my_veo_clips\n"
            "  python fairway.py --random --duration 3.0\n"
            "  python fairway.py --test"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    # The main scene prompt (optional — use --random if omitted)
    parser.add_argument(
        "prompt",
        nargs="?",  # Optional — makes the prompt not required
        help="Scene description, e.g. 'Misty dawn, links-style course, coastal cliffs'"
    )

    # Duration override
    parser.add_argument(
        "--duration", "-d",
        type=float,
        default=None,  # None means "use config.py value"
        metavar="HOURS",
        help=f"Video duration in hours (default: {config.TARGET_DURATION_HOURS})"
    )

    # Ambience toggle
    parser.add_argument(
        "--no-ambience",
        action="store_true",  # True if flag is present, False if not
        help="Music only — skip ambient golf course sounds"
    )

    # Character mode override
    parser.add_argument(
        "--character",
        choices=["always", "never", "random"],
        default=None,
        help="Whether to include a foreground character figure (default: from config.py)"
    )

    # YouTube upload
    parser.add_argument(
        "--no-upload",
        dest="upload",
        action="store_false",
        help="Skip YouTube upload (upload is on by default; requires YouTube API setup)"
    )
    parser.set_defaults(upload=True)

    # YouTube Shorts generation
    parser.add_argument(
        "--no-shorts",
        dest="shorts",
        action="store_false",
        help="Skip YouTube Shorts generation (on by default; produces 5 Shorts per video)"
    )
    parser.set_defaults(shorts=True)

    # A/B music genre test
    parser.add_argument(
        "--ab-test",
        dest="ab_test",
        action="store_true",
        help=(
            "Generate two videos from the same visuals — one per genre in config.AB_TEST_GENRES "
            "(default: Jazz and HipHop). Each gets its own music, title, and thumbnail. "
            "Add tracks to assets/music/Jazz/ and assets/music/HipHop/ before running."
        )
    )
    parser.set_defaults(ab_test=False)

    # Convenience flags
    parser.add_argument(
        "--random",
        action="store_true",
        help="Pick a random scene from the pre-built scene library"
    )

    parser.add_argument(
        "--list-scenes",
        action="store_true",
        help="List all available scenes in the library and exit"
    )

    parser.add_argument(
        "--clips-folder",
        metavar="FOLDER",
        default=None,
        help=(
            "Named subfolder inside assets/video_clips/ to use for this run. "
            "E.g. --clips-folder my_veo_clips uses assets/video_clips/my_veo_clips/. "
            "If omitted, clips are read from the root folder."
        )
    )

    parser.add_argument(
        "--schedule-shorts",
        dest="schedule_shorts",
        action="store_true",
        help="Seed the shorts tracker and schedule the next 4 weeks of shorts to YouTube",
    )

    parser.add_argument(
        "--weeks",
        type=int,
        default=4,
        metavar="N",
        help="Weeks of shorts to schedule — applies to --schedule-shorts and the auto-schedule after --upload (default: 4)",
    )

    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="With --schedule-shorts: preview the schedule without uploading anything",
    )

    parser.add_argument(
        "--shorts-status",
        dest="shorts_status",
        action="store_true",
        help="Print a summary of the shorts tracker and exit",
    )

    parser.add_argument(
        "--reset-tracker",
        dest="reset_tracker",
        action="store_true",
        help=(
            "Reset all scheduled shorts back to 'unused' in the tracker. "
            "Run this after deleting the corresponding YouTube videos."
        ),
    )

    parser.add_argument(
        "--backfill",
        dest="backfill",
        action="store_true",
        help=(
            "Match existing video_tracker.json entries to archive folders by title, "
            "then link their shorts. Use --dry-run to preview without saving."
        ),
    )

    parser.add_argument(
        "--import-videos",
        dest="import_videos",
        action="store_true",
        help=(
            "Fetch all videos from your YouTube channel and import any missing ones "
            "into video_tracker.json, linking them to archive folders. "
            "Requires youtube.readonly OAuth (one-time browser login). "
            "Use --dry-run to preview without saving."
        ),
    )

    parser.add_argument(
        "--list-playlists",
        dest="list_playlists",
        action="store_true",
        help="Print all playlists on your YouTube channel with their IDs, then exit.",
    )

    parser.add_argument(
        "--resume",
        metavar="RUN_ID",
        help="Resume a failed run by its ID (e.g., 'runs/20260318_143201')"
    )

    # Video stabilization (two-pass vidstab — removes camera shake from Kling clips)
    parser.add_argument(
        "--stabilize",
        action="store_true",
        help="Apply two-pass vidstab stabilization to each clip before assembly (removes Kling camera shake)"
    )

    # Smoke test — generates a 3-minute video to test the full pipeline
    parser.add_argument(
        "--test",
        action="store_true",
        help="Smoke test: generate a 3-minute video to validate the pipeline works"
    )

    return parser.parse_args()


# =============================================================================
# ENTRY POINT
# =============================================================================
def main():
    """
    Main function — called when you run: python fairway.py

    This orchestrates everything:
    1. Parse arguments
    2. Determine the scene prompt
    3. Set up the run directory and logging
    4. Check requirements
    5. Run the pipeline (or resume it)
    """
    args = parse_args()

    # Handle --reset-tracker: reset all scheduled shorts back to unused
    if getattr(args, 'reset_tracker', False):
        logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s",
                            datefmt="%H:%M:%S", stream=sys.stdout)
        print("\n  Fairway Frequencies — Reset Shorts Tracker\n")
        count = reset_scheduled_shorts()
        print(f"  Reset {count} shorts back to 'unused'.")
        print("  Run --shorts-status to verify.\n")
        sys.exit(0)

    # Handle --shorts-status: show tracker summary and exit
    if getattr(args, 'shorts_status', False):
        seed_tracker()
        print_tracker_summary()
        sys.exit(0)

    # Handle --backfill: match archive folders to tracker entries by title
    if getattr(args, 'backfill', False):
        dry_run = getattr(args, 'dry_run', False)
        logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s",
                            datefmt="%H:%M:%S", stream=sys.stdout)
        print(f"\n  Fairway Frequencies — {'DRY RUN — ' if dry_run else ''}Backfill Video Links\n")
        results = backfill_video_links(dry_run=dry_run)
        print_backfill_report(results)
        if dry_run:
            print("  Remove --dry-run to save the links.\n")
        else:
            matched = sum(1 for r in results if r.get("confidence", 0) >= 0.65)
            print(f"  {matched}/{len(results)} videos linked. Run --shorts-status to verify.\n")
        sys.exit(0)

    # Handle --schedule-shorts: seed tracker + schedule + upload, then exit
    if getattr(args, 'schedule_shorts', False):
        weeks = getattr(args, 'weeks', 4)
        dry_run = getattr(args, 'dry_run', False)
        logging.basicConfig(
            level=logging.INFO,
            format="[%(asctime)s] %(message)s",
            datefmt="%H:%M:%S",
            stream=sys.stdout,
        )
        mode = "DRY RUN — " if dry_run else ""
        print(f"\n  Fairway Frequencies — {mode}Shorts Scheduler")
        print(f"  Scheduling {weeks} weeks of shorts...\n")
        slots = schedule_weeks(
            weeks_ahead=weeks,
            client_id=config.YOUTUBE_CLIENT_ID,
            client_secret=config.YOUTUBE_CLIENT_SECRET,
            dry_run=dry_run,
        )
        print(f"\n  Done — {len(slots)} slots {'previewed' if dry_run else 'scheduled'}.")
        if dry_run:
            print("  Remove --dry-run to upload for real.\n")
        sys.exit(0)

    # Handle --list-playlists: print channel playlists for .env setup
    if getattr(args, 'list_playlists', False):
        logging.basicConfig(level=logging.WARNING, stream=sys.stdout)
        if not config.YOUTUBE_CLIENT_ID or not config.YOUTUBE_CLIENT_SECRET:
            print("  ✗ YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET must be set in .env")
            sys.exit(1)
        playlists = list_channel_playlists(config.YOUTUBE_CLIENT_ID, config.YOUTUBE_CLIENT_SECRET)
        print("\n  Your YouTube channel playlists:\n")
        for p in playlists:
            print(f"  {p['id']}  {p['title']}")
        print("\n  Add to your .env file:")
        print("  YT_PLAYLIST_JAZZ=<id>")
        print("  YT_PLAYLIST_HIPHOP=<id>")
        print("  YT_PLAYLIST_MORNING=<id>")
        print("  YT_PLAYLIST_EVENING=<id>\n")
        sys.exit(0)

    # Handle --import-videos: fetch channel videos from YouTube API
    if getattr(args, 'import_videos', False):
        dry_run = getattr(args, 'dry_run', False)
        logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s",
                            datefmt="%H:%M:%S", stream=sys.stdout)
        print(f"\n  Fairway Frequencies — {'DRY RUN — ' if dry_run else ''}Import Channel Videos\n")
        if not config.YOUTUBE_CLIENT_ID or not config.YOUTUBE_CLIENT_SECRET:
            print("  ✗ YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET must be set in .env")
            sys.exit(1)
        results = import_channel_videos(
            client_id=config.YOUTUBE_CLIENT_ID,
            client_secret=config.YOUTUBE_CLIENT_SECRET,
            dry_run=dry_run,
        )
        print_import_report(results)
        if dry_run:
            print("  Remove --dry-run to import for real.\n")
        else:
            linked = sum(1 for r in results if r.get("confidence", 0) >= 0.65)
            print(f"  Imported {len(results)} videos, {linked} linked to archive folders.")
            print("  Run --shorts-status to see the updated tracker.\n")
        sys.exit(0)

    # Handle --list-scenes before doing anything else
    if args.list_scenes:
        scenes = load_scene_library()
        if scenes:
            print("\n  Fairway Frequencies -- Pre-Built Scene Library\n")
            for i, scene in enumerate(scenes, 1):
                print(f"  {i:2d}. {scene['name']:<35} [{scene['mood']}]")
                print(f"       {scene['description'][:70]}...")
            print(f"\n  Total: {len(scenes)} scenes")
            print("  Use --random to pick one, or paste the description as your prompt.\n")
        sys.exit(0)

    # Handle --resume
    if args.resume:
        run_dir = args.resume
        state = load_state(run_dir)
        if not state:
            print(f"\n✗ No saved state found in: {run_dir}")
            print("  Check the path and try again.")
            sys.exit(1)
        prompt = state.get("prompt", "")
        logger = setup_logging(run_dir)
        logger.info(f"Resuming run from: {run_dir}")
        logger.info(f"Completed stages: {list(state.keys())}")
        if not check_requirements(args):
            sys.exit(1)
        run_pipeline(prompt, args, run_dir, logger, state)
        return

    # Handle --test — run a smoke test with a short duration
    if args.test:
        print("\n🧪 Running smoke test (3-minute video)...")
        print("   This tests the full pipeline with minimal API cost.\n")
        args.duration = 0.05          # 3 minutes (0.05 hours)
        args.no_ambience = False
        args.character = "never"      # Landscape only for speed
        prompt = "Sunny morning, classic parkland course, gentle hills, puffy clouds"
    elif args.random:
        # Ask Claude to generate a fresh seasonal scene for this month's art style
        art_style = get_current_art_style()
        print(f"\n  Generating scene ({art_style['name']} — {art_style['short']})...")
        from pipeline.scene_tracker import load_scene_history
        try:
            prompt, _ = generate_scene_prompt(
                api_key=config.ANTHROPIC_API_KEY,
                claude_model=config.CLAUDE_MODEL,
                scene_history=load_scene_history(),
            )
            print(f"  Scene: {prompt}\n")
        except Exception as e:
            print(f"\n✗ Scene generation failed: {e}")
            print("  Check your ANTHROPIC_API_KEY in .env")
            sys.exit(1)
    else:
        # Use the prompt provided on the command line
        prompt = args.prompt
        if not prompt:
            print("\n✗ Please provide a scene description, use --random, or use --test")
            print("  Example: python fairway.py \"Misty dawn, links-style course\"")
            print("  Help:    python fairway.py --help\n")
            sys.exit(1)

    # Create a unique directory for this run — makes it easy to find outputs later
    # and supports resume if the run is interrupted
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join("runs", timestamp)
    os.makedirs(run_dir, exist_ok=True)

    # Set up logging for this run
    logger = setup_logging(run_dir)

    # Print the welcome banner
    logger.info("=" * 60)
    logger.info("  Fairway Frequencies — LoFi Golf YouTube Automation")
    logger.info("  Living Painting Pipeline v3")
    logger.info("=" * 60)
    logger.info(f"  Run ID:  {timestamp}")
    logger.info(f"  Prompt:  {prompt}")
    logger.info(f"  Output:  {config.OUTPUT_DIR}")

    # Check that all requirements are met before starting
    if not check_requirements(args):
        logger.error("\nPlease fix the issues above and try again.")
        sys.exit(1)

    # Start fresh state
    state = {"prompt": prompt}
    save_state(run_dir, state)

    # Run the full pipeline
    try:
        run_pipeline(prompt, args, run_dir, logger, state)

        # Auto-schedule shorts after a successful upload
        if getattr(args, 'upload', False):
            weeks = getattr(args, 'weeks', 4)
            logger.info("\n" + "━" * 60)
            logger.info(f"  Auto-scheduling {weeks} weeks of shorts to YouTube...")
            logger.info("━" * 60)
            try:
                slots = schedule_weeks(
                    weeks_ahead=weeks,
                    client_id=config.YOUTUBE_CLIENT_ID,
                    client_secret=config.YOUTUBE_CLIENT_SECRET,
                )
                logger.info(f"  ✓ {len(slots)} shorts scheduled")
            except Exception as e:
                logger.warning(f"  ⚠ Shorts auto-scheduling failed: {e}")
                logger.warning("  Run: python fairway.py --schedule-shorts to retry")

    except KeyboardInterrupt:
        logger.info(f"\n⚠️  Run interrupted. Resume with:")
        logger.info(f"  python fairway.py --resume {run_dir}")
        sys.exit(0)
    except Exception as e:
        logger.error(f"\n✗ Pipeline failed with unexpected error: {e}")
        logger.info(f"\n  To resume this run after fixing the issue:")
        logger.info(f"  python fairway.py --resume {run_dir}")
        logger.debug("Full traceback:", exc_info=True)
        sys.exit(1)


# This is the standard Python pattern for "run this code only when this file
# is called directly" (not when it's imported by another module).
if __name__ == "__main__":
    main()
