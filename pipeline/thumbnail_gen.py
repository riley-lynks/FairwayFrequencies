# =============================================================================
# pipeline/thumbnail_gen.py — YouTube Thumbnail Generation
# =============================================================================
# PURPOSE:
#   Generate a 1280x720 thumbnail image for the YouTube video.
#
# STRATEGY:
#   Use the base image we already generated as the foundation.
#   Apply a saturation boost (+15%) and slight vignette using Pillow
#   to make the thumbnail "pop" more than the video frame.
#
# WHY boost saturation for the thumbnail?
#   YouTube thumbnails compete in a sea of other thumbnails. Your animated
#   scene looks beautiful at full size, but at 320×180 pixels (how thumbnails
#   often display in search results), more vibrant colors catch the eye better.
#   We keep the boost subtle — just +15% saturation — so it looks intentional,
#   not garish.
#
# WHY use the base image instead of generating a new one?
#   - Faster (no new API call needed)
#   - Consistent with the video content (viewer knows what they're clicking into)
#   - The base image is already excellent quality (it's the whole video's visual)
#   If IMAGE_SOURCE = "flux", we optionally generate a fresh thumbnail via the API.
# =============================================================================

import os
import shutil
import logging
import subprocess
from PIL import Image, ImageEnhance  # Pillow library for image processing

import config

logger = logging.getLogger("fairway.thumbnail_gen")

THUMBNAIL_WIDTH = 1280   # YouTube thumbnail dimensions
THUMBNAIL_HEIGHT = 720
SATURATION_BOOST = 1.15  # 15% saturation increase (1.0 = no change)


def generate_thumbnail(
    base_image_path: str,
    thumbnail_prompt: str,
    image_source: str,
    run_dir: str,
    output_dir: str,
    final_video_path: str,
    api_key: str,
    logger: logging.Logger = None,
) -> str:
    """
    Generate a 1280x720 YouTube thumbnail from the base image.

    Args:
        base_image_path:   Path to the base image used for the video.
        thumbnail_prompt:  Thumbnail image prompt (used if generating fresh image).
        image_source:      "midjourney" or "flux" — which image path was used.
        run_dir:           Current run directory.
        output_dir:        Final output directory (thumbnail saved here).
        final_video_path:  Path to the final video (thumbnail uses same base name).
        api_key:           BFL API key (used only if flux and we generate fresh).
        logger:            Logger for progress messages.

    Returns:
        Path to the generated thumbnail file.
    """
    local_logger = logger or logging.getLogger("fairway.thumbnail_gen")

    # Determine thumbnail output path — same name as video, .png extension
    video_basename = os.path.basename(final_video_path).replace(".mp4", "")
    thumbnail_path = os.path.join(output_dir, f"{video_basename}_thumbnail.png")
    os.makedirs(output_dir, exist_ok=True)

    local_logger.info("  Processing thumbnail from base image...")

    # Process the base image into a thumbnail
    try:
        processed_path = _process_base_image_for_thumbnail(
            base_image_path=base_image_path,
            output_path=thumbnail_path,
            local_logger=local_logger,
        )
        local_logger.info(f"  ✓ Thumbnail: {thumbnail_path}")
        return processed_path

    except Exception as e:
        local_logger.warning(f"  ⚠️ Thumbnail generation failed: {e}")
        # Fallback: just copy and resize the base image
        try:
            _simple_resize_thumbnail(base_image_path, thumbnail_path)
            return thumbnail_path
        except Exception as e2:
            local_logger.warning(f"  ⚠️ Thumbnail fallback also failed: {e2}")
            # Last resort: just copy the base image as-is
            shutil.copy2(base_image_path, thumbnail_path)
            return thumbnail_path


def _process_base_image_for_thumbnail(
    base_image_path: str,
    output_path: str,
    local_logger,
) -> str:
    """
    Process the base image into a polished YouTube thumbnail.

    Steps:
    1. Open and resize to 1280x720
    2. Boost saturation by 15% (makes colors pop in search results)
    3. Apply a subtle vignette (darkens edges slightly, draws eye to center)
    4. Save as PNG

    Args:
        base_image_path: Source image.
        output_path:     Where to save the thumbnail.
        local_logger:    Logger.

    Returns:
        Path to the saved thumbnail.
    """
    # Open the image with Pillow
    # WHY Pillow? It's the standard Python image processing library.
    # Simple, well-documented, and handles all common formats.
    img = Image.open(base_image_path)

    # Convert to RGB if needed (PNG images can be RGBA — 4 channels)
    # YouTube thumbnails should be RGB — remove transparency
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    # Resize to 1280x720, maintaining aspect ratio and cropping edges if needed
    # WHY LANCZOS? It's the highest-quality resize algorithm in Pillow.
    # Important for thumbnails — they get scrutinized at varying sizes.
    img = _resize_and_crop(img, THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT)

    # Boost saturation — makes colors more vivid/eye-catching in search results
    # ImageEnhance.Color: 1.0 = original, >1.0 = more saturated, <1.0 = less
    enhancer = ImageEnhance.Color(img)
    img = enhancer.enhance(SATURATION_BOOST)

    # Apply subtle vignette (optional — darkens edges slightly)
    # This is a common thumbnail technique that draws the eye to the center
    img = _apply_vignette(img, strength=0.15)

    # Save as PNG (lossless — thumbnails deserve maximum quality)
    img.save(output_path, "PNG", optimize=True)

    size_kb = os.path.getsize(output_path) / 1024
    local_logger.debug(f"  Thumbnail saved: {size_kb:.0f}KB — {THUMBNAIL_WIDTH}x{THUMBNAIL_HEIGHT}")

    return output_path


def _resize_and_crop(img: Image.Image, target_width: int, target_height: int) -> Image.Image:
    """
    Resize and center-crop an image to the target dimensions.

    This is the "cover" resize behavior — fills the target exactly
    without stretching or leaving black bars. Edges may be cropped
    if the aspect ratio doesn't match.

    Args:
        img:          Input PIL image.
        target_width:  Target width in pixels.
        target_height: Target height in pixels.

    Returns:
        Resized and cropped PIL image.
    """
    target_ratio = target_width / target_height
    img_ratio = img.width / img.height

    if img_ratio > target_ratio:
        # Image is wider than target — scale by height, crop sides
        new_height = target_height
        new_width = int(img_ratio * new_height)
    else:
        # Image is taller than target — scale by width, crop top/bottom
        new_width = target_width
        new_height = int(new_width / img_ratio)

    # Resize using Lanczos (highest quality algorithm)
    img = img.resize((new_width, new_height), Image.LANCZOS)

    # Center crop to exact target size
    left = (new_width - target_width) // 2
    top = (new_height - target_height) // 2
    right = left + target_width
    bottom = top + target_height

    return img.crop((left, top, right, bottom))


def _apply_vignette(img: Image.Image, strength: float = 0.15) -> Image.Image:
    """
    Apply a subtle radial vignette to the image.

    A vignette darkens the corners and edges, drawing the viewer's eye
    to the center of the thumbnail. Common in photography and thumbnails.

    Args:
        img:      Input PIL image.
        strength: How dark the vignette gets at the edges (0.0-1.0).
                  0.15 = 15% darkening at edges — very subtle.

    Returns:
        Image with vignette applied.
    """
    try:
        import numpy as np

        # Create a radial gradient mask
        # Values range from 1.0 (center, no darkening) to (1-strength) (edges)
        w, h = img.size
        Y, X = np.ogrid[:h, :w]

        # Normalized distance from center (0 = center, 1 = corner)
        cx, cy = w / 2, h / 2
        dist = np.sqrt(((X - cx) / cx) ** 2 + ((Y - cy) / cy) ** 2)
        dist = np.clip(dist, 0, 1)

        # Vignette multiplier: 1.0 at center, (1 - strength) at edges
        vignette = 1.0 - (strength * dist)

        # Apply vignette to each channel
        img_array = np.array(img, dtype=np.float32)
        img_array *= vignette[:, :, np.newaxis]
        img_array = np.clip(img_array, 0, 255).astype(np.uint8)

        return Image.fromarray(img_array)

    except ImportError:
        # numpy not available — skip vignette
        return img


def _simple_resize_thumbnail(source_path: str, output_path: str):
    """
    Fallback: simple resize without enhancement.

    Args:
        source_path: Source image path.
        output_path: Output thumbnail path.
    """
    img = Image.open(source_path)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    img = img.resize((THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT), Image.LANCZOS)
    img.save(output_path, "PNG")
