# =============================================================================
# pipeline/thumbnail_gen.py — YouTube Thumbnail Generation
# =============================================================================
# PURPOSE:
#   Generate a 1280x720 thumbnail image for the YouTube video.
#
# STRATEGY:
#   Use the base image as the foundation, then add a text overlay in the
#   style of popular study/chill music channels:
#     - Dark gradient on the left third for readability
#     - Large bold headline (2-3 words from the video title)
#     - Smaller subtitle (mood/genre)
#     - "Fairway Frequencies" channel branding
#
# WHY text overlays? Competitor research shows the top study/lofi channels
# all use bold keyword text on thumbnails. At small sizes (how thumbnails
# display in search), the text communicates instantly what the video is.
# =============================================================================

import os
import re
import shutil
import logging
from PIL import Image, ImageEnhance, ImageDraw, ImageFont

import config

logger = logging.getLogger("fairway.thumbnail_gen")

THUMBNAIL_WIDTH  = 1280
THUMBNAIL_HEIGHT = 720
SATURATION_BOOST = 1.15

# Font paths — Arial Bold preferred, Impact as fallback
_FONT_PATHS = [
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/impact.ttf",
    "C:/Windows/Fonts/arial.ttf",
]


def generate_thumbnail(
    base_image_path: str,
    thumbnail_prompt: str,
    image_source: str,
    run_dir: str,
    output_dir: str,
    final_video_path: str,
    api_key: str,
    metadata: dict = None,
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
        metadata:          Video metadata dict (used for title-based text overlay).
        logger:            Logger for progress messages.

    Returns:
        Path to the generated thumbnail file.
    """
    local_logger = logger or logging.getLogger("fairway.thumbnail_gen")

    video_basename = os.path.basename(final_video_path).replace(".mp4", "")
    thumbnail_path = os.path.join(output_dir, f"{video_basename}_thumbnail.png")
    os.makedirs(output_dir, exist_ok=True)

    local_logger.info("  Processing thumbnail from base image...")

    try:
        processed_path = _process_base_image_for_thumbnail(
            base_image_path=base_image_path,
            output_path=thumbnail_path,
            metadata=metadata,
            local_logger=local_logger,
        )
        local_logger.info(f"  ✓ Thumbnail: {thumbnail_path}")
        return processed_path

    except Exception as e:
        local_logger.warning(f"  ⚠️ Thumbnail generation failed: {e}")
        try:
            _simple_resize_thumbnail(base_image_path, thumbnail_path)
            return thumbnail_path
        except Exception as e2:
            local_logger.warning(f"  ⚠️ Thumbnail fallback also failed: {e2}")
            shutil.copy2(base_image_path, thumbnail_path)
            return thumbnail_path


def _process_base_image_for_thumbnail(
    base_image_path: str,
    output_path: str,
    metadata: dict,
    local_logger,
) -> str:
    """
    Process the base image into a polished YouTube thumbnail with text overlay.

    Steps:
    1. Open and resize to 1280x720
    2. Boost saturation by 15%
    3. Apply subtle vignette
    4. Add dark gradient on the left for text readability
    5. Draw bold headline + subtitle + channel name text
    6. Save as PNG
    """
    img = Image.open(base_image_path)

    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    img = _resize_and_crop(img, THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT)

    enhancer = ImageEnhance.Color(img)
    img = enhancer.enhance(SATURATION_BOOST)

    img = _apply_vignette(img, strength=0.2)

    # Extract text lines from metadata
    headline, subtitle = _extract_text_from_metadata(metadata)

    # Add gradient + text overlay
    img = _add_text_overlay(img, headline, subtitle)

    img.save(output_path, "PNG", optimize=True)

    size_kb = os.path.getsize(output_path) / 1024
    local_logger.debug(f"  Thumbnail saved: {size_kb:.0f}KB — {THUMBNAIL_WIDTH}x{THUMBNAIL_HEIGHT}")

    return output_path


def _extract_text_from_metadata(metadata: dict) -> tuple[str, str]:
    """
    Extract headline and subtitle for the thumbnail text overlay.

    Headline: Claude-chosen keyword phrase from metadata["thumbnail_text"]
              (e.g. "STUDY MUSIC", "DEEP FOCUS") — optimized for click-through.
    Subtitle: mood/genre extracted from the title.

    Returns:
        (headline, subtitle)
    """
    if not metadata:
        return "LOFI GOLF", "Fairway Frequencies"

    # Use Claude's chosen thumbnail keyword phrase as the headline
    headline = metadata.get("thumbnail_text", "").strip().upper()
    if not headline:
        headline = "STUDY MUSIC"  # fallback

    # Subtitle: extract mood/genre from title (part after "|")
    title = metadata.get("title", "")
    subtitle = "Fairway Frequencies"
    match = re.search(r"\|\s*(.+?)(?:\s*⛳.*)?$", title)
    if match:
        subtitle = match.group(1).strip().rstrip("⛳").strip()

    return headline, subtitle


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    """Load the best available bold font at the given size."""
    for path in _FONT_PATHS:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _add_text_overlay(img: Image.Image, headline: str, subtitle: str) -> Image.Image:
    """
    Add a text overlay to the thumbnail in the style of top study/lofi channels.

    Layout:
      - Semi-transparent dark gradient on the left ~55% of the image
      - Large bold headline in the upper-left area
      - Smaller subtitle below
      - "Fairway Frequencies" channel name at the bottom-left

    Args:
        img:      The base thumbnail image (1280x720).
        headline: Large bold text (e.g. "GOLDEN HOUR").
        subtitle: Smaller descriptor text (e.g. "Nostalgic LoFi Golf").

    Returns:
        Image with overlay applied.
    """
    import numpy as np

    w, h = img.size

    # --- Dark gradient overlay on left portion ---
    img_array = np.array(img, dtype=np.float32)

    gradient_width = int(w * 0.58)   # Covers left 58% of image
    for x in range(gradient_width):
        # Starts at 65% opacity at left edge, fades to 0 at gradient_width
        opacity = 0.65 * (1.0 - (x / gradient_width) ** 0.6)
        img_array[:, x, :] *= (1.0 - opacity)

    img = Image.fromarray(np.clip(img_array, 0, 255).astype(np.uint8))

    # --- Draw text ---
    draw = ImageDraw.Draw(img)

    pad_x = 60    # Left padding
    pad_y = 55    # Top padding

    # Headline — large bold text
    font_headline = _load_font(108)
    _draw_text_with_shadow(draw, (pad_x, pad_y), headline, font_headline,
                            fill=(255, 255, 255), shadow_offset=3, shadow_opacity=160)

    # Subtitle — medium text below headline
    font_subtitle = _load_font(52)
    headline_bbox = draw.textbbox((pad_x, pad_y), headline, font=font_headline)
    subtitle_y = headline_bbox[3] + 18
    _draw_text_with_shadow(draw, (pad_x, subtitle_y), subtitle, font_subtitle,
                            fill=(220, 220, 220), shadow_offset=2, shadow_opacity=140)

    # Channel branding — small, bottom-left
    font_brand = _load_font(34)
    brand_y = h - 54
    _draw_text_with_shadow(draw, (pad_x, brand_y), "Fairway Frequencies", font_brand,
                            fill=(180, 210, 180), shadow_offset=2, shadow_opacity=120)

    return img


def _draw_text_with_shadow(
    draw: ImageDraw.ImageDraw,
    position: tuple,
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple,
    shadow_offset: int = 3,
    shadow_opacity: int = 150,
):
    """
    Draw text with a drop shadow for readability against any background.

    Args:
        draw:           ImageDraw instance.
        position:       (x, y) top-left of the text.
        text:           Text to draw.
        font:           Font to use.
        fill:           Text color as RGB tuple.
        shadow_offset:  How many pixels to offset the shadow.
        shadow_opacity: Shadow darkness (0=transparent, 255=black).
    """
    x, y = position
    shadow_color = (0, 0, 0, shadow_opacity)

    # Draw shadow slightly offset
    draw.text((x + shadow_offset, y + shadow_offset), text,
              font=font, fill=shadow_color)

    # Draw main text on top
    draw.text((x, y), text, font=font, fill=fill)


def _resize_and_crop(img: Image.Image, target_width: int, target_height: int) -> Image.Image:
    """Resize and center-crop to exact target dimensions (cover behavior)."""
    target_ratio = target_width / target_height
    img_ratio = img.width / img.height

    if img_ratio > target_ratio:
        new_height = target_height
        new_width = int(img_ratio * new_height)
    else:
        new_width = target_width
        new_height = int(new_width / img_ratio)

    img = img.resize((new_width, new_height), Image.LANCZOS)

    left = (new_width - target_width) // 2
    top  = (new_height - target_height) // 2

    return img.crop((left, top, left + target_width, top + target_height))


def _apply_vignette(img: Image.Image, strength: float = 0.2) -> Image.Image:
    """Apply a radial vignette — darkens edges, draws eye to center."""
    try:
        import numpy as np

        w, h = img.size
        Y, X = np.ogrid[:h, :w]
        cx, cy = w / 2, h / 2
        dist = np.sqrt(((X - cx) / cx) ** 2 + ((Y - cy) / cy) ** 2)
        dist = np.clip(dist, 0, 1)
        vignette = 1.0 - (strength * dist)

        img_array = np.array(img, dtype=np.float32)
        img_array *= vignette[:, :, np.newaxis]

        return Image.fromarray(np.clip(img_array, 0, 255).astype(np.uint8))

    except ImportError:
        return img


def _simple_resize_thumbnail(source_path: str, output_path: str):
    """Fallback: simple resize without enhancement."""
    img = Image.open(source_path)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    img = img.resize((THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT), Image.LANCZOS)
    img.save(output_path, "PNG")
