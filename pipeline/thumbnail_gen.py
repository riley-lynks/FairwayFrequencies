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
SATURATION_BOOST = 1.25   # Bumped from 1.15 — thumbnails compete at ~270px wide in search
RIGHT_BRIGHTNESS_BOOST = 1.12  # Lightly lift the right-side scenery so it pops against the dark left

# Font paths — Arial Bold preferred, Impact as fallback
_FONT_PATHS = [
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/impact.ttf",
    "C:/Windows/Fonts/arial.ttf",
]


def generate_thumbnail(
    base_image_path: str,
    thumbnail_prompt: str,
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
    Subtitle: Scene anchor extracted from the title (e.g. "Dew-Soaked Fairway",
              "Golden Hour Links") — gives the thumbnail context beyond the keyword.

    Returns:
        (headline, subtitle)
    """
    if not metadata:
        return "LOFI GOLF", "Golf Course Vibes"

    # Use Claude's chosen thumbnail keyword phrase as the headline
    headline = metadata.get("thumbnail_text", "").strip().upper()
    if not headline:
        headline = "STUDY MUSIC"  # fallback

    # Subtitle: extract scene anchor from title.
    # New title format: "[Use-case keyword] • [Scene anchor] ⛳ [Duration]"
    # e.g. "Lofi Study Music • Dew-Soaked Fairway ⛳ 2 Hours"
    title = metadata.get("title", "")
    subtitle = ""

    # Try new bullet-separator format first
    match = re.search(r"•\s*(.+?)(?:\s*⛳.*)?$", title)
    if match:
        subtitle = match.group(1).strip().rstrip("⛳").strip()

    # Fallback: try legacy pipe-separator format
    if not subtitle:
        match = re.search(r"\|\s*(.+?)(?:\s*[⛳|].*)?$", title)
        if match:
            candidate = match.group(1).strip().rstrip("⛳").strip()
            # Skip if it looks like a duration ("2 Hours") or genre phrase
            if not re.match(r"^\d+\s+hours?$", candidate, re.IGNORECASE):
                subtitle = candidate

    if not subtitle:
        subtitle = "Golf Course Lofi"

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

    img_array = np.array(img, dtype=np.float32)

    gradient_width = int(w * 0.58)   # Covers left 58% of image

    # --- Dark gradient on left (text area) ---
    for x in range(gradient_width):
        opacity = 0.68 * (1.0 - (x / gradient_width) ** 0.6)
        img_array[:, x, :] *= (1.0 - opacity)

    # --- Subtle brightness lift on right (scenery area) ---
    # Transitions smoothly from no boost at the gradient edge to full boost at right edge
    right_start = int(w * 0.50)
    for x in range(right_start, w):
        t = (x - right_start) / (w - right_start)  # 0.0 → 1.0 across right side
        boost = 1.0 + (RIGHT_BRIGHTNESS_BOOST - 1.0) * t
        img_array[:, x, :] = np.clip(img_array[:, x, :] * boost, 0, 255)

    img = Image.fromarray(np.clip(img_array, 0, 255).astype(np.uint8))

    # --- Draw text ---
    draw = ImageDraw.Draw(img)

    pad_x = 56
    pad_y = 52

    # Headline — large bold text with word wrap so long phrases don't clip
    font_headline = _load_font(100)
    max_headline_width = int(w * 0.52)  # Don't let text bleed into the bright right side
    headline_lines = _wrap_text(draw, headline, font_headline, max_headline_width)

    _draw_text_with_shadow(draw, (pad_x, pad_y), "\n".join(headline_lines),
                            font_headline, fill=(255, 255, 255),
                            shadow_offset=4, shadow_opacity=200)

    # Measure where the headline block ends
    line_height = draw.textbbox((0, 0), "A", font=font_headline)[3]
    headline_bottom = pad_y + line_height * len(headline_lines) + (10 * (len(headline_lines) - 1))

    # Subtitle — medium text below headline
    font_subtitle = _load_font(48)
    subtitle_y = headline_bottom + 16
    _draw_text_with_shadow(draw, (pad_x, subtitle_y), subtitle, font_subtitle,
                            fill=(215, 225, 215), shadow_offset=3, shadow_opacity=180)

    # Thin gold accent line between headline and subtitle
    accent_y = headline_bottom + 8
    draw.rectangle([(pad_x, accent_y), (pad_x + 160, accent_y + 3)],
                   fill=(184, 148, 77))   # Muted gold — complements the green palette

    # Channel branding — small, bottom-left
    font_brand = _load_font(32)
    brand_y = h - 50
    _draw_text_with_shadow(draw, (pad_x, brand_y), "Fairway Frequencies", font_brand,
                            fill=(170, 205, 170), shadow_offset=2, shadow_opacity=160)

    return img


def _draw_text_with_shadow(
    draw: ImageDraw.ImageDraw,
    position: tuple,
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple,
    shadow_offset: int = 4,
    shadow_opacity: int = 200,
):
    """
    Draw text with a multi-layer drop shadow for strong readability at small sizes.

    WHY multi-layer? A single-pixel shadow looks thin when the thumbnail is
    displayed at 270×152px in YouTube search. Drawing the shadow in 3 passes
    at increasing offsets simulates a soft blur — it reads cleanly even tiny.

    Args:
        draw:           ImageDraw instance.
        position:       (x, y) top-left of the text.
        text:           Text to draw.
        font:           Font to use.
        fill:           Text color as RGB tuple.
        shadow_offset:  Base shadow offset in pixels.
        shadow_opacity: Shadow darkness (0=transparent, 255=black).
    """
    x, y = position

    # Three passes at increasing offsets — farthest first so closest renders on top
    for dist, opacity in [
        (shadow_offset + 2, shadow_opacity // 3),
        (shadow_offset + 1, shadow_opacity // 2),
        (shadow_offset,     shadow_opacity),
    ]:
        draw.text((x + dist, y + dist), text,
                  font=font, fill=(0, 0, 0, opacity))

    # Main text on top
    draw.text((x, y), text, font=font, fill=fill)


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont,
               max_width: int) -> list:
    """
    Break text into lines that fit within max_width pixels.

    Splits on spaces first. If a single word is wider than max_width it
    stays on its own line (no character-level breaking needed for our
    short keyword phrases).

    Returns:
        List of line strings.
    """
    words = text.split()
    lines = []
    current = ""

    for word in words:
        test = (current + " " + word).strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word

    if current:
        lines.append(current)

    return lines if lines else [text]


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
