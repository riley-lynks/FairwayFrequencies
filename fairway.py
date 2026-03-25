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
from pipeline.orchestrator import decompose_prompt
from pipeline.image_gen import generate_images
from pipeline.image_import import import_midjourney_images
from pipeline.video_import import import_kling_clips
from pipeline.video_assembly import assemble_living_painting
from pipeline.music_gen import get_music_track
from pipeline.ambient_sounds import download_ambient_sounds
from pipeline.audio_assembly import assemble_audio
from pipeline.final_render import render_final_video
from pipeline.metadata_gen import generate_metadata
from pipeline.thumbnail_gen import generate_thumbnail
from pipeline.youtube_upload import upload_to_youtube


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

    # Check image generation requirements based on chosen path
    image_source = getattr(args, 'images', None) or config.IMAGE_SOURCE
    if image_source == "flux" and not config.BFL_API_KEY:
        issues.append(
            "IMAGE_SOURCE is 'flux' but BFL_API_KEY is not set.\n"
            "  Get your key at https://api.bfl.ml/\n"
            "  Or switch to Midjourney: set IMAGE_SOURCE = 'midjourney' in config.py"
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
    image_source = getattr(args, 'images', None) or config.IMAGE_SOURCE
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

    start_time = time.time()

    # =========================================================================
    # STAGE 1: ORCHESTRATOR
    # =========================================================================
    # Ask Claude to decompose the scene prompt into detailed sub-prompts for
    # every downstream stage (image, video, music, ambient sounds, thumbnail).
    if "orchestration" not in state:
        logger.info("━" * 60)
        logger.info("[Stage 1/11] Decomposing scene prompt with Claude...")
        logger.info(f"  Scene: \"{prompt}\"")

        orchestration = decompose_prompt(
            scene_prompt=prompt,
            character_mode=character_mode,
            style_suffix=config.STYLE_SUFFIX,
            animation_variations=config.ANIMATION_VARIATIONS,
        )

        state["orchestration"] = orchestration
        save_state(run_dir, state)
        logger.info("  ✓ Orchestration complete")
        logger.debug(f"  Orchestration result: {json.dumps(orchestration, indent=2)}")
    else:
        logger.info("[Stage 1/11] Orchestration — loaded from saved state")
        orchestration = state["orchestration"]

    # If --prompts-only, print the Midjourney image prompt AND all Kling
    # animation prompts, then stop. The user copies these into each tool
    # before running the full pipeline.
    if getattr(args, 'prompts_only', False):
        separator = "=" * 65

        # --- STEP 1: Midjourney image prompt ---
        print(f"\n{separator}")
        print("  STEP 1 — MIDJOURNEY PROMPT  (generate your base image)")
        print(f"{separator}")
        print(f"\n  {orchestration['image_prompt']}")
        print("\n  Parameters:  --ar 16:9 --v 7 --s 750")
        print("\n  After generating:")
        print("    1. Pick your favorite, upscale it (U1–U4)")
        print("    2. Save the .png to:  assets/midjourney_images/")

        # --- STEP 2: Kling animation prompts ---
        animation_variations = orchestration.get(
            "animation_variations", config.ANIMATION_VARIATIONS
        )
        base_video_prompt = orchestration.get("base_video_prompt", "")

        # Extract the negative prompt (same for all clips; may come from first variation dict)
        first_var = animation_variations[0] if animation_variations else None
        if isinstance(first_var, dict):
            negative_prompt = first_var.get("negative_prompt", config.DEFAULT_NEGATIVE_PROMPT)
        else:
            negative_prompt = config.DEFAULT_NEGATIVE_PROMPT

        thin = "─" * 65
        print(f"\n{separator}")
        print("  STEP 2 — KLING ANIMATION PROMPTS  (generate 6 clips)")
        print("  app.klingai.com → AI Videos → Image to Video")
        print("  Settings: Standard mode · 5 seconds · 16:9 aspect ratio")
        print(f"{separator}")

        print(f"\n  ⚠️  NEGATIVE PROMPT — paste this into Kling's Negative Prompt field")
        print(f"       (same for every clip — set it once, keep it for all 6):\n")
        print(f"  {negative_prompt}\n")
        print(f"  {thin}")

        for i, variation in enumerate(
            animation_variations[:config.NUM_ANIMATION_CLIPS], start=1
        ):
            if isinstance(variation, dict):
                prompt_text = variation.get("prompt", "")
            else:
                # Legacy string format
                prompt_text = (
                    f"{base_video_prompt}. {variation}" if base_video_prompt else variation
                )
            print(f"\n  Clip {i} of {config.NUM_ANIMATION_CLIPS}:")
            print(f"  {prompt_text}")

        print(f"\n{separator}")
        print("  After generating all clips:")
        print(f"    1. Download each .mp4 to:  assets/kling_clips/")
        print(f"    2. Run: python fairway.py \"{prompt}\"")
        print(f"{separator}\n")
        return

    # =========================================================================
    # STAGE 2: IMAGE GENERATION
    # =========================================================================
    # Get the ONE base image that will be the visual world of this entire video.
    if "base_image" not in state:
        logger.info("━" * 60)
        logger.info("[Stage 2/11] Getting base image...")

        if image_source == "midjourney":
            logger.info("  Mode: Midjourney (manual) — checking assets/midjourney_images/")
            logger.info(f"\n  Midjourney prompt:\n  {orchestration['image_prompt']}\n")
            specific_image = getattr(args, 'image', None)
            if specific_image:
                logger.info(f"  Using selected image: {specific_image}")
            base_image_path = import_midjourney_images(
                target_dir=run_dir,
                image_prompt=orchestration['image_prompt'],
                specific_filename=specific_image,
            )
        else:
            logger.info("  Mode: Flux 2 (automated) — calling Black Forest Labs API")
            base_image_path = generate_images(
                image_prompt=orchestration['image_prompt'],
                run_dir=run_dir,
                api_key=config.BFL_API_KEY,
            )

        state["base_image"] = base_image_path
        save_state(run_dir, state)
        logger.info(f"  ✓ Base image ready: {base_image_path}")
    else:
        logger.info("[Stage 2/11] Base image — loaded from saved state")
        base_image_path = state["base_image"]

    # =========================================================================
    # STAGES 3–4 (video) and STAGES 5–6 (audio) run IN PARALLEL
    # =========================================================================
    # WHY parallel? Video generation takes ~20 minutes (Kling API).
    # Music generation also takes a few minutes (Mubert API).
    # Running them at the same time saves those minutes.
    # Python "threads" let us do two things simultaneously.

    video_result = {}   # Will be filled by the video thread
    audio_result = {}   # Will be filled by the audio thread
    video_error = []    # Catches exceptions from the video thread
    audio_error = []    # Catches exceptions from the audio thread

    def run_video_pipeline():
        """
        Run Stages 3 and 4: generate animation clips, then assemble them
        into the final 2-3 hour video. Runs in its own thread.
        """
        try:
            # === STAGE 3: VIDEO CLIP IMPORT ===
            # Clips are generated manually at app.klingai.com and saved to
            # assets/kling_clips/. This stage copies them into the run directory.
            # Use --prompts-only first to get all the animation prompts to paste.
            if "animation_clips" not in state:
                logger.info("━" * 60)
                logger.info(f"[Stage 3/11] Importing Kling animation clips...")
                logger.info(f"  Looking in: {config.KLING_CLIPS_DIR}")

                clip_paths = import_kling_clips(
                    clips_dir=clips_dir,
                    base_video_prompt=orchestration["base_video_prompt"],
                    animation_variations=orchestration["animation_variations"],
                    num_clips=config.NUM_ANIMATION_CLIPS,
                    logger=logger,
                    clips_ready=getattr(args, 'clips_ready', False),
                    clips_subfolder=getattr(args, 'clips_folder', None),
                )

                state["animation_clips"] = clip_paths
                save_state(run_dir, state)
                logger.info(f"  ✓ {len(clip_paths)} animation clips ready")
            else:
                logger.info("[Stage 3/11] Animation clips — loaded from saved state")
                clip_paths = state["animation_clips"]

            # === STAGE 4: VIDEO ASSEMBLY ===
            if "assembled_video" not in state:
                logger.info("━" * 60)
                logger.info("[Stage 4/11] Assembling living painting (seamless loop)...")
                logger.info(f"  Target duration: {target_hours} hours")
                logger.info(f"  Loop blend: {config.LOOP_BLEND_SECONDS}s crossfades between clips")

                assembled_video_path = assemble_living_painting(
                    clip_paths=clip_paths,
                    target_duration_hours=target_hours,
                    blend_seconds=config.LOOP_BLEND_SECONDS,
                    run_dir=run_dir,
                    norm_dir=norm_dir,
                    logger=logger,
                )

                state["assembled_video"] = assembled_video_path
                save_state(run_dir, state)
                logger.info(f"  ✓ Video assembled: {assembled_video_path}")
            else:
                logger.info("[Stage 4/11] Assembled video — loaded from saved state")
                assembled_video_path = state["assembled_video"]

            video_result["path"] = assembled_video_path

        except Exception as e:
            video_error.append(e)
            logger.error(f"  ✗ Video pipeline failed: {e}")
            raise

    def run_audio_pipeline():
        """
        Run Stages 5 and 6: get music track and ambient sounds (if enabled).
        Runs in its own thread, parallel to video generation.
        """
        try:
            # === STAGE 5: MUSIC GENERATION ===
            if "music_track" not in state:
                logger.info("━" * 60)
                logger.info("[Stage 5/11] Getting LoFi music track...")

                music_path = get_music_track(
                    music_prompt=orchestration["music_prompt"],
                    target_duration_hours=target_hours,
                    audio_dir=audio_dir,
                    api_key=config.MUBERT_API_KEY,
                    logger=logger,
                )

                state["music_track"] = music_path
                save_state(run_dir, state)
                logger.info(f"  ✓ Music ready: {music_path}")
            else:
                logger.info("[Stage 5/11] Music track — loaded from saved state")
                music_path = state["music_track"]

            # === STAGE 6: AMBIENT SOUNDS ===
            ambient_path = None
            if include_ambience:
                if "ambient_sounds" not in state:
                    logger.info("━" * 60)
                    logger.info("[Stage 6/11] Downloading ambient golf course sounds...")

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
                    logger.info("[Stage 6/11] Ambient sounds — loaded from saved state")
                    ambient_path = state["ambient_sounds"]
            else:
                logger.info("[Stage 6/11] Ambient sounds — skipped (--no-ambience or disabled in config)")

            audio_result["music"] = music_path
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
    music_path = audio_result["music"]
    ambient_path = audio_result.get("ambient")

    # =========================================================================
    # STAGE 7: AUDIO ASSEMBLY
    # =========================================================================
    if "mixed_audio" not in state:
        logger.info("━" * 60)
        logger.info("[Stage 7/11] Mixing music and ambient sounds...")

        mixed_audio_path = assemble_audio(
            music_path=music_path,
            ambient_path=ambient_path,
            target_duration_hours=target_hours,
            music_volume=config.MUSIC_VOLUME,
            ambience_volume=config.AMBIENCE_VOLUME,
            audio_dir=audio_dir,
            logger=logger,
        )

        state["mixed_audio"] = mixed_audio_path
        save_state(run_dir, state)
        logger.info(f"  ✓ Mixed audio ready: {mixed_audio_path}")
    else:
        logger.info("[Stage 7/11] Mixed audio — loaded from saved state")
        mixed_audio_path = state["mixed_audio"]

    # =========================================================================
    # STAGE 8: FINAL RENDER
    # =========================================================================
    if "final_video" not in state:
        logger.info("━" * 60)
        logger.info("[Stage 8/11] Rendering final video (merging video + audio)...")

        # Build output filename: channel_name_scene_timestamp.mp4
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_prompt = "".join(c if c.isalnum() or c == "_" else "_" for c in prompt[:30])
        output_filename = f"fairway_{safe_prompt}_{timestamp}.mp4"
        output_path = os.path.join(config.OUTPUT_DIR, output_filename)
        os.makedirs(config.OUTPUT_DIR, exist_ok=True)

        final_video_path = render_final_video(
            video_path=assembled_video_path,
            audio_path=mixed_audio_path,
            output_path=output_path,
            logger=logger,
        )

        state["final_video"] = final_video_path
        save_state(run_dir, state)
        logger.info(f"  ✓ Final video: {final_video_path}")
        _cleanup_intermediates(run_dir, logger)
    else:
        logger.info("[Stage 8/11] Final video — loaded from saved state")
        final_video_path = state["final_video"]

    # =========================================================================
    # STAGE 9: METADATA GENERATION
    # =========================================================================
    if "metadata" not in state:
        logger.info("━" * 60)
        logger.info("[Stage 9/11] Generating YouTube title, description, and tags...")

        metadata = generate_metadata(
            scene_prompt=prompt,
            orchestration=orchestration,
            api_key=config.ANTHROPIC_API_KEY,
            claude_model=config.CLAUDE_MODEL,
            logger=logger,
        )

        # Save metadata as a JSON file next to the video
        metadata_path = final_video_path.replace(".mp4", "_metadata.json")
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        state["metadata"] = metadata
        save_state(run_dir, state)
        logger.info(f"  ✓ Metadata saved: {metadata_path}")
    else:
        logger.info("[Stage 9/11] Metadata — loaded from saved state")
        metadata = state["metadata"]

    # =========================================================================
    # STAGE 10: THUMBNAIL GENERATION
    # =========================================================================
    if "thumbnail" not in state:
        logger.info("━" * 60)
        logger.info("[Stage 10/11] Generating thumbnail image...")

        thumbnail_path = generate_thumbnail(
            base_image_path=base_image_path,
            thumbnail_prompt=orchestration.get("thumbnail_prompt", orchestration["image_prompt"]),
            image_source=image_source,
            run_dir=run_dir,
            output_dir=config.OUTPUT_DIR,
            final_video_path=final_video_path,
            api_key=config.BFL_API_KEY,
            logger=logger,
        )

        state["thumbnail"] = thumbnail_path
        save_state(run_dir, state)
        logger.info(f"  ✓ Thumbnail: {thumbnail_path}")
    else:
        logger.info("[Stage 10/11] Thumbnail — loaded from saved state")
        thumbnail_path = state["thumbnail"]

    # =========================================================================
    # STAGE 11: YOUTUBE UPLOAD (OPTIONAL)
    # =========================================================================
    if getattr(args, 'upload', False):
        logger.info("━" * 60)
        logger.info("[Stage 11/11] Uploading to YouTube (unlisted)...")

        upload_to_youtube(
            video_path=final_video_path,
            thumbnail_path=thumbnail_path,
            metadata=metadata,
            client_id=config.YOUTUBE_CLIENT_ID,
            client_secret=config.YOUTUBE_CLIENT_SECRET,
            logger=logger,
        )
        logger.info("  ✓ Upload complete")
    else:
        logger.info("[Stage 11/11] YouTube upload — skipped (add --upload to enable)")

    # =========================================================================
    # SUMMARY
    # =========================================================================
    elapsed = time.time() - start_time
    elapsed_min = elapsed / 60

    logger.info("\n" + "=" * 60)
    logger.info("  FAIRWAY FREQUENCIES -- Production Complete!")
    logger.info("=" * 60)
    logger.info(f"  Scene:     {prompt[:50]}...")
    logger.info(f"  Video:     {final_video_path}")
    logger.info(f"  Thumbnail: {thumbnail_path}")
    logger.info(f"  Duration:  {target_hours} hours")
    logger.info(f"  Runtime:   {elapsed_min:.1f} minutes")
    logger.info(f"  Title:     {metadata.get('title', 'N/A')}")
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
            "Generates 2–3 hour living painting videos from a single scene prompt.\n"
            "\nExamples:\n"
            "  python fairway.py \"Misty dawn, links course, coastal cliffs\"\n"
            "  python fairway.py --random --duration 3.0\n"
            "  python fairway.py --prompts-only \"Cherry blossom Japanese course\"\n"
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

    # Image source override
    parser.add_argument(
        "--images",
        choices=["midjourney", "flux"],
        default=None,
        help="Image generation method: 'midjourney' (manual) or 'flux' (automated)"
    )

    # Specific image filename to use (instead of auto-selecting most recent)
    parser.add_argument(
        "--image",
        metavar="FILENAME",
        default=None,
        help="Exact filename in assets/midjourney_images/ to use as the base image"
    )

    # YouTube upload
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Upload to YouTube as unlisted after generation (requires YouTube API setup)"
    )

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
        "--prompts-only",
        action="store_true",
        help="Print the Midjourney image prompt and all Kling animation prompts, then exit"
    )

    parser.add_argument(
        "--clips-folder",
        metavar="FOLDER",
        default=None,
        help=(
            "Named subfolder inside assets/kling_clips/ to use for this run. "
            "E.g. --clips-folder misty_dawn uses assets/kling_clips/misty_dawn/. "
            "If omitted, clips are read from the root folder (backward compatible)."
        )
    )

    parser.add_argument(
        "--clips-ready",
        action="store_true",
        help=(
            "Skip straight to video assembly — assumes clips are already "
            "in assets/kling_clips/ (lowers minimum from 3 to 1)"
        )
    )

    parser.add_argument(
        "--resume",
        metavar="RUN_ID",
        help="Resume a failed run by its ID (e.g., 'runs/20260318_143201')"
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
        args.images = args.images or config.IMAGE_SOURCE
        prompt = "Sunny morning, classic parkland course, gentle hills, puffy clouds"
    elif args.random:
        # Pick a random scene from the library
        scenes = load_scene_library()
        if not scenes:
            print("\n✗ Scene library is empty. Check prompts/scene_library.json")
            sys.exit(1)
        scene = random.choice(scenes)
        prompt = scene["description"]
        print(f"\n🎲 Random scene selected: {scene['name']}")
        print(f"   {prompt}\n")
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
