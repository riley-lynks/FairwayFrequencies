# =============================================================================
# pipeline/video_import.py — Video Clip Import
# =============================================================================
# PURPOSE:
#   Find the video clips you've generated externally (Veo, Kling, Runway,
#   Pika, etc.) and copy them into the current run's clips directory for
#   video assembly.
#
# WORKFLOW:
#   1. Generate clips in your preferred tool
#   2. Save them to a named subfolder: assets/video_clips/my_scene/
#   3. Run: python fairway.py "scene" --clips-folder my_scene
# =============================================================================

import os
import shutil
import glob
import logging

logger = logging.getLogger("fairway.video_import")

VIDEO_CLIPS_DIR = os.path.join("assets", "video_clips")

MIN_CLIPS_REQUIRED = 3


def list_clip_sets() -> list:
    """
    Return all available clip sets in the video clips directory.

    A "clip set" is either:
      - A named subfolder inside assets/video_clips/ containing .mp4 files
      - The root folder itself, if it contains .mp4 files directly

    Returns:
        List of dicts sorted by modification time (newest first):
        [{ "name": "my_scene", "count": 6, "path": "assets/video_clips/my_scene" }, ...]
    """
    os.makedirs(VIDEO_CLIPS_DIR, exist_ok=True)
    sets = []

    try:
        entries = os.scandir(VIDEO_CLIPS_DIR)
    except OSError:
        return []

    subfolder_entries = []
    for entry in entries:
        if entry.is_dir():
            clips = _find_clips_in_folder(entry.path)
            if clips:
                subfolder_entries.append({
                    "name": entry.name,
                    "count": len(clips),
                    "path": entry.path,
                    "_mtime": entry.stat().st_mtime,
                })

    subfolder_entries.sort(key=lambda x: x["_mtime"], reverse=True)
    for e in subfolder_entries:
        del e["_mtime"]
    sets.extend(subfolder_entries)

    root_clips = _find_clips_in_folder(VIDEO_CLIPS_DIR, top_level_only=True)
    if root_clips:
        sets.append({
            "name": "",
            "count": len(root_clips),
            "path": VIDEO_CLIPS_DIR,
        })

    return sets


def import_video_clips(
    clips_dir: str,
    logger: logging.Logger = None,
    clips_subfolder: str = None,
) -> list:
    """
    Find video clips and copy them into the run's clips directory.

    Clips can be organised in named subfolders:
      assets/video_clips/my_scene/clip1.mp4   → clips_subfolder="my_scene"
      assets/video_clips/clip1.mp4            → clips_subfolder="" or None

    Args:
        clips_dir:       The run's clips directory (clips are copied here).
        logger:          Logger instance for progress messages.
        clips_subfolder: Named subfolder inside VIDEO_CLIPS_DIR to use.

    Returns:
        List of paths to the copied clip files inside clips_dir.

    Raises:
        RuntimeError: If not enough clips are found.
    """
    local_logger = logger or logging.getLogger("fairway.video_import")
    os.makedirs(clips_dir, exist_ok=True)

    if clips_subfolder:
        source_dir = os.path.join(VIDEO_CLIPS_DIR, clips_subfolder)
        local_logger.info(f"  Clip set: \"{clips_subfolder}\" ({source_dir})")
    else:
        source_dir = VIDEO_CLIPS_DIR
        local_logger.info(f"  Clip set: root folder ({source_dir})")

    found_clips = _find_clips_in_folder(source_dir)
    local_logger.info(f"  Found {len(found_clips)} clip(s) in {source_dir}/")

    if len(found_clips) < MIN_CLIPS_REQUIRED:
        raise RuntimeError(
            f"Not enough clips in {source_dir}/\n"
            f"Found {len(found_clips)}, need at least {MIN_CLIPS_REQUIRED}.\n"
            f"Generate clips with Veo, Kling, Runway, or any video tool and "
            f"save them to {source_dir}/"
        )

    found_clips.sort()

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
    """Find all .mp4 files in the given folder (non-recursive)."""
    if not os.path.exists(folder_path):
        os.makedirs(folder_path, exist_ok=True)
        return []

    found = []
    seen = set()

    for ext in ["*.mp4", "*.MP4"]:
        pattern = os.path.join(folder_path, ext)
        for path in glob.glob(pattern):
            if top_level_only and os.path.dirname(os.path.abspath(path)) != os.path.abspath(folder_path):
                continue
            name_lower = os.path.basename(path).lower()
            if name_lower not in seen:
                seen.add(name_lower)
                found.append(path)

    return found
