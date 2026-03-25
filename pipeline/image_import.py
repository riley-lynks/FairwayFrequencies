# =============================================================================
# pipeline/image_import.py — Midjourney Image Import (Manual Path)
# =============================================================================
# PURPOSE:
#   When IMAGE_SOURCE = "midjourney" in config.py, this module handles finding
#   and preparing the base image that the user has manually generated in
#   Midjourney and dropped into the assets/midjourney_images/ folder.
#
# WHY a manual path at all? Midjourney v7 produces significantly better
# anime/Ghibli landscape output than any automated API. The tradeoff is
# that it requires manual steps (generate in browser, download, place in folder).
# For a YouTube channel where every video represents your brand, that extra
# quality is worth the extra 5 minutes.
#
# WORKFLOW FOR THE USER:
#   1. Run: python fairway.py --prompts-only "your scene"
#   2. Copy the printed Midjourney prompt
#   3. Paste into Midjourney (Discord or web app), generate, pick your fave
#   4. Download the image and save it to assets/midjourney_images/
#   5. Run: python fairway.py "your scene" (full pipeline)
# =============================================================================

import os       # For file operations and path checking
import shutil   # For copying files between directories
import glob     # For finding files matching a pattern (like *.png)
import random   # For selecting a random image when multiple exist
import logging  # For progress messages

logger = logging.getLogger("fairway.image_import")

# Where users drop their Midjourney images
MIDJOURNEY_IMAGES_DIR = os.path.join("assets", "midjourney_images")

# Supported image formats Midjourney outputs
SUPPORTED_EXTENSIONS = [".png", ".jpg", ".jpeg", ".webp"]


def import_midjourney_images(
    target_dir: str,
    image_prompt: str,
    specific_filename: str = None,
) -> str:
    """
    Find the user's Midjourney image and copy it to the current run directory.

    In v3, we need exactly ONE base image (not 3). If multiple images exist in
    the folder, we pick the most recently modified one (the user's latest work).
    If none exist, we print a helpful guide showing the Midjourney prompt.

    Args:
        target_dir:   The current run's working directory (images get copied here).
        image_prompt: The Midjourney prompt (shown to user if folder is empty).

    Returns:
        Path to the copied image file in target_dir.

    Raises:
        RuntimeError: If no images are found in the Midjourney images folder.
    """
    # If the user selected a specific image (via the UI or --image flag), use that.
    # Otherwise fall back to picking the most recently modified one.
    if specific_filename:
        specific_path = os.path.join(MIDJOURNEY_IMAGES_DIR, specific_filename)
        if not os.path.exists(specific_path):
            raise RuntimeError(
                f"Selected image not found: {specific_path}\n"
                f"Make sure '{specific_filename}' is in the {MIDJOURNEY_IMAGES_DIR}/ folder."
            )
        selected_image = specific_path
        logger.info(f"  Using selected image: {specific_filename}")
    else:
        # Find all image files in the Midjourney images directory
        found_images = _find_images_in_folder(MIDJOURNEY_IMAGES_DIR)

        if not found_images:
            _print_no_images_guide(image_prompt)
            raise RuntimeError(
                f"No images found in {MIDJOURNEY_IMAGES_DIR}/\n"
                "Please add a Midjourney image and run again.\n"
                "Or switch to automated mode: set IMAGE_SOURCE = 'flux' in config.py"
            )

        # Sort by modification time, use the most recent
        found_images.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        selected_image = found_images[0]
        logger.info(f"  Found {len(found_images)} image(s). Auto-selected most recent: "
                    f"{os.path.basename(selected_image)}")
        if len(found_images) > 1:
            logger.info(
                f"  Tip: Select a specific image in the control panel to override this."
            )

    # Copy the selected image to the run directory
    # WHY copy instead of just use in place? The run directory contains everything
    # for this specific video generation. Copying keeps runs self-contained so
    # you can resume them or review them later without worrying about source files
    # being moved or deleted.
    extension = os.path.splitext(selected_image)[1].lower()
    destination = os.path.join(target_dir, f"base_image{extension}")
    shutil.copy2(selected_image, destination)

    file_size_kb = os.path.getsize(destination) / 1024
    logger.info(f"  ✓ Image copied to run directory ({file_size_kb:.0f}KB): {destination}")

    return destination


def _find_images_in_folder(folder_path: str) -> list:
    """
    Find all supported image files in the given folder.

    Args:
        folder_path: The folder to search (not recursive — only top-level files).

    Returns:
        List of full file paths to image files found.
    """
    if not os.path.exists(folder_path):
        # Create the folder with a helpful message if it doesn't exist yet
        os.makedirs(folder_path, exist_ok=True)
        logger.debug(f"  Created {folder_path} (it was missing)")
        return []

    found = []
    for ext in SUPPORTED_EXTENSIONS:
        # glob.glob finds all files matching a pattern
        # The * wildcard matches any filename
        pattern = os.path.join(folder_path, f"*{ext}")
        found.extend(glob.glob(pattern))

        # Also check uppercase extensions (e.g., .PNG, .JPG) — common on Windows
        pattern_upper = os.path.join(folder_path, f"*{ext.upper()}")
        found.extend(glob.glob(pattern_upper))

    # Remove duplicates (in case the same file matched both patterns)
    return list(set(found))


def _print_no_images_guide(image_prompt: str):
    """
    Print a clear, friendly guide when no Midjourney images are found.

    WHY print detailed instructions here? The user is a Python beginner.
    A bare "file not found" error would be confusing. This guide explains
    exactly what to do with a copy-pasteable Midjourney prompt.

    Args:
        image_prompt: The Midjourney prompt to display.
    """
    separator = "=" * 65

    print(f"""
{separator}
  ⚠️  No Midjourney images found in {MIDJOURNEY_IMAGES_DIR}/
{separator}

  No worries! Here's what to do:

  STEP 1 — Copy this Midjourney prompt:
  ──────────────────────────────────────
  {image_prompt}
  ──────────────────────────────────────
  Add these parameters:  --ar 16:9 --v 7 --s 750

  STEP 2 — Generate in Midjourney:
    • Go to midjourney.com or Discord
    • Type /imagine and paste the prompt + parameters
    • Wait for Midjourney to generate 4 images
    • Pick your favorite (upscale it with U1-U4)

  STEP 3 — Save the image:
    • Click the image to open it full size
    • Right-click → Save Image As
    • Save it into:  {MIDJOURNEY_IMAGES_DIR}/
    • Any filename works (e.g., golf_course_01.png)

  STEP 4 — Run again:
    python fairway.py "your scene description"

  ──────────────────────────────────────
  WANT FULLY AUTOMATED? (no manual steps)
  Set IMAGE_SOURCE = "flux" in config.py
  Flux 2 runs automatically — slightly lower
  quality but completely hands-off.
{separator}
""")
