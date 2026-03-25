# =============================================================================
# pipeline/video_import.py — Kling Clip Import (Manual Path)
# =============================================================================
# PURPOSE:
#   Stage 3 of the pipeline: find the Kling animation clips the user has
#   manually generated via app.klingai.com and saved to assets/kling_clips/.
#   Copies them into the current run's clips directory for video assembly.
#
# WHY manual instead of API? The Kling web subscription (app.klingai.com)
# is far cheaper than equivalent API credits. You generate 6 clips in the
# browser, download them, drop them in assets/kling_clips/, and the pipeline
# handles everything else automatically.
#
# WORKFLOW FOR THE USER:
#   1. Run: python fairway.py --prompts-only "your scene"
#      → Prints the Midjourney prompt AND all 6 Kling animation prompts
#   2. Generate your base image in Midjourney, save to assets/midjourney_images/
#   3. Open app.klingai.com → AI Videos → Image to Video
#      Upload your base image, paste each prompt, generate 6 clips
#      Settings: Standard mode · 5 seconds · 16:9 aspect ratio
#   4. Download each clip and save to assets/kling_clips/
#   5. Run: python fairway.py "your scene"  (pipeline handles the rest)
# =============================================================================

import os       # For file operations and path checking
import shutil   # For copying files between directories
import glob     # For finding files matching a pattern
import logging  # For progress messages

logger = logging.getLogger("fairway.video_import")

# Where users save their Kling clips (can be overridden in config.py)
KLING_CLIPS_DIR = os.path.join("assets", "kling_clips")

# Minimum clips needed to assemble a looping video.
# 3 is the practical minimum — the loop would be too repetitive with fewer.
MIN_CLIPS_REQUIRED = 3


def list_clip_sets() -> list:
    """
    Return all available clip sets in the Kling clips directory.

    A "clip set" is either:
      - A named subfolder inside assets/kling_clips/ that contains .mp4 files
        (e.g., assets/kling_clips/misty_dawn/ → set name "misty_dawn")
      - The root folder itself, if it contains .mp4 files directly
        (shown as name="" for backward compatibility)

    Returns:
        List of dicts sorted by modification time (newest first):
        [{ "name": "misty_dawn", "count": 6, "path": "assets/kling_clips/misty_dawn" }, ...]
        Root clips (if any) appear as { "name": "", "count": N, "path": "assets/kling_clips" }
    """
    os.makedirs(KLING_CLIPS_DIR, exist_ok=True)
    sets = []

    # Check named subfolders first
    try:
        entries = os.scandir(KLING_CLIPS_DIR)
    except OSError:
        return []

    subfolder_entries = []
    for entry in entries:
        if entry.is_dir():
            clips = _find_clips_in_folder(entry.path)
            if clips:  # Only include folders that actually contain clips
                subfolder_entries.append({
                    "name": entry.name,
                    "count": len(clips),
                    "path": entry.path,
                    "_mtime": entry.stat().st_mtime,
                })

    # Sort subfolders by modification time, newest first
    subfolder_entries.sort(key=lambda x: x["_mtime"], reverse=True)
    for e in subfolder_entries:
        del e["_mtime"]  # Remove sort key before returning
    sets.extend(subfolder_entries)

    # Check root folder for clips (backward compatibility)
    root_clips = _find_clips_in_folder(KLING_CLIPS_DIR, top_level_only=True)
    if root_clips:
        sets.append({
            "name": "",
            "count": len(root_clips),
            "path": KLING_CLIPS_DIR,
        })

    return sets


def import_kling_clips(
    clips_dir: str,
    base_video_prompt: str,
    animation_variations: list,
    num_clips: int,
    logger: logging.Logger = None,
    clips_ready: bool = False,
    clips_subfolder: str = None,
) -> list:
    """
    Find the user's Kling clips and copy them into the run's clips directory.

    Clips can be organised in named subfolders:
      assets/kling_clips/misty_dawn/clip1.mp4   → clips_subfolder="misty_dawn"
      assets/kling_clips/clip1.mp4              → clips_subfolder="" or None (root)

    If enough clips are found (>= MIN_CLIPS_REQUIRED), copies them and
    returns their paths. If not enough are found, prints a step-by-step guide
    showing every animation prompt the user needs to generate in Kling, then
    raises RuntimeError to pause the pipeline.

    Args:
        clips_dir:            The run's clips directory (clips are copied here).
        base_video_prompt:    Base animation direction from the orchestrator.
        animation_variations: Per-clip animation prompt variations.
        num_clips:            Target number of clips (used for instructions).
        logger:               Logger instance for progress messages.
        clips_ready:          If True, skip the instructions and proceed with
                              whatever clips are available (minimum 1).
        clips_subfolder:      Named subfolder inside KLING_CLIPS_DIR to use.
                              None / "" means use the root folder directly.

    Returns:
        List of paths to the copied clip files inside clips_dir.

    Raises:
        RuntimeError: If not enough clips are found.
    """
    local_logger = logger or logging.getLogger("fairway.video_import")
    os.makedirs(clips_dir, exist_ok=True)

    # Resolve the actual source directory
    if clips_subfolder:
        source_dir = os.path.join(KLING_CLIPS_DIR, clips_subfolder)
        local_logger.info(f"  Clip set: \"{clips_subfolder}\" ({source_dir})")
    else:
        source_dir = KLING_CLIPS_DIR
        local_logger.info(f"  Clip set: root folder ({source_dir})")

    # Find all .mp4 files in the resolved source directory
    found_clips = _find_clips_in_folder(source_dir)

    local_logger.info(f"  Found {len(found_clips)} clip(s) in {source_dir}/")

    # Check if we have enough clips to proceed
    min_required = 1 if clips_ready else MIN_CLIPS_REQUIRED

    if len(found_clips) < min_required:
        if not clips_ready:
            # Print a full walkthrough with all prompts pre-filled
            _print_no_clips_guide(base_video_prompt, animation_variations, num_clips)

        raise RuntimeError(
            f"Not enough clips in {source_dir}/\n"
            f"Found {len(found_clips)}, need at least {min_required}.\n"
            f"Generate clips at app.klingai.com, download as .mp4, "
            f"save to {source_dir}/"
        )

    # Sort clips by name for a consistent, repeatable order
    found_clips.sort()

    # Copy each clip into the run directory with standardized names
    # WHY copy? Keeps the run self-contained — the source files in
    # assets/kling_clips/ can be reused for other videos without conflict.
    copied_clips = []
    for i, clip_path in enumerate(found_clips, start=1):
        clip_filename = f"clip_{i:02d}.mp4"
        dest_path = os.path.join(clips_dir, clip_filename)
        shutil.copy2(clip_path, dest_path)
        copied_clips.append(dest_path)
        local_logger.info(
            f"  ✓ Clip {i}/{len(found_clips)}: {os.path.basename(clip_path)} → {clip_filename}"
        )

    local_logger.info(f"\n  {len(copied_clips)} clip(s) copied and ready for assembly")
    return copied_clips


def _find_clips_in_folder(folder_path: str, top_level_only: bool = False) -> list:
    """
    Find all .mp4 files in the given folder (non-recursive, top-level only).

    Args:
        folder_path:     The folder to search.
        top_level_only:  If True, skip files that are inside subdirectories.
                         Used by list_clip_sets() to count only root-level clips.

    Returns:
        List of full file paths to .mp4 files found.
    """
    if not os.path.exists(folder_path):
        # Create the folder so it's ready for the user to drop files into
        os.makedirs(folder_path, exist_ok=True)
        logger.debug(f"  Created {folder_path} (it was missing)")
        return []

    found = []
    seen = set()  # Track filenames (lowercased) to prevent duplicates on Windows

    # Check both lowercase and uppercase extensions (.mp4 and .MP4)
    for ext in ["*.mp4", "*.MP4"]:
        pattern = os.path.join(folder_path, ext)
        for path in glob.glob(pattern):
            # top_level_only: skip files whose parent dir is not folder_path
            if top_level_only and os.path.dirname(os.path.abspath(path)) != os.path.abspath(folder_path):
                continue
            name_lower = os.path.basename(path).lower()
            if name_lower not in seen:
                seen.add(name_lower)
                found.append(path)

    return found


def _print_no_clips_guide(
    base_video_prompt: str,
    animation_variations: list,
    num_clips: int,
):
    """
    Print step-by-step instructions when Kling clips aren't ready yet.

    Prints the negative prompt once (it's identical for every clip), then
    lists each positive prompt ready to copy-paste into Kling's web UI.

    Variations may be dicts {"prompt": "...", "negative_prompt": "..."} or
    plain strings (legacy format). Both are handled.

    Args:
        base_video_prompt:    The base animation prompt from the orchestrator.
        animation_variations: Per-clip variation prompts (dicts or strings).
        num_clips:            How many clips to generate.
    """
    import config as _cfg

    separator = "=" * 65
    thin = "─" * 65

    # Extract negative prompt from first variation (all are the same)
    first = animation_variations[0] if animation_variations else None
    if isinstance(first, dict):
        negative_prompt = first.get("negative_prompt", _cfg.DEFAULT_NEGATIVE_PROMPT)
    else:
        negative_prompt = _cfg.DEFAULT_NEGATIVE_PROMPT

    # Build the numbered positive-prompt list
    prompts_text = ""
    for i, variation in enumerate(animation_variations[:num_clips], start=1):
        if isinstance(variation, dict):
            prompt_text = variation.get("prompt", "")
        else:
            # Legacy string format — prepend base if available
            prompt_text = f"{base_video_prompt}. {variation}" if base_video_prompt else variation

        prompts_text += f"\n  {thin}\n  Clip {i} of {num_clips}\n  {thin}\n  {prompt_text}\n"

    print(f"""
{separator}
  ⚠️  No Kling clips found in {KLING_CLIPS_DIR}/
{separator}

  STEP 1 — Open Kling's web app:
    app.klingai.com → AI Videos → Image to Video

  STEP 2 — Upload your base image:
    Use the image from assets/midjourney_images/

  STEP 3 — Set generation settings:
    Mode: Standard  ·  Duration: 5 seconds  ·  Aspect ratio: 16:9

  STEP 4 — Copy this NEGATIVE PROMPT into Kling's Negative Prompt field
    (same for every clip — paste it once, it stays for all 6 generations):

    {negative_prompt}

  STEP 5 — Generate {num_clips} clips using these prompts:
    Paste each into Kling's main prompt field, keep the negative prompt above.
{prompts_text}
  STEP 6 — Download each clip and save to a named subfolder:
    • Click the completed clip in Kling → Download
    • Create a folder for this scene, e.g.:
        {KLING_CLIPS_DIR}/misty_dawn/
    • Save all 6 clips into that folder (any filename works)
    • Using subfolders keeps each scene's clips separate so the
      pipeline always grabs the right set

  STEP 7 — Run again and select your clip set:
    python fairway.py "your scene" --clips-folder misty_dawn

  Tip: If you have the clips ready and just want to proceed:
    python fairway.py "your scene" --clips-folder misty_dawn --clips-ready
{separator}
""")
