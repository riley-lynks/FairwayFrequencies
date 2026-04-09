# =============================================================================
# pipeline/golfquilizer.py — Radial Audio Visualizer ("The Golfquilizer")
# =============================================================================
# PURPOSE:
#   Renders the signature Fairway Frequencies audio-reactive visualizer for
#   YouTube Shorts. A golf ball wireframe PNG sits in the center, surrounded
#   by radial frequency bars that pulse outward in sync with the LoFi beats.
#
# HOW IT WORKS:
#   1. Extract raw audio from the video segment (PCM via FFmpeg)
#   2. For each video frame (30fps), compute FFT of the matching audio window
#   3. Draw radial bars emanating outward from the golf ball using PIL
#   4. Pipe the rendered RGBA frames into FFmpeg as a transparent overlay
#   5. FFmpeg composites: cropped golf course + radial bars + golf ball PNG
#
# WHY Python instead of FFmpeg filters?
#   FFmpeg's built-in visualizers (showcqt, showwaves) only render linear
#   bar charts or waveforms. There's no way to make bars radiate outward
#   in a circle using FFmpeg filters alone. Python + PIL gives us full
#   control over the radial layout, bar shapes, glow effects, and timing.
#
# DEPENDENCIES:
#   - numpy (FFT computation)
#   - Pillow (drawing radial bars on transparent canvas)
#   - FFmpeg (audio extraction + final video composition)
# =============================================================================

import logging
import math
import os
import struct
import subprocess
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import config

logger = logging.getLogger("fairway.golfquilizer")

# --- Visualizer Design Constants ---

# How many radial bars around the circle (more = denser, fewer = chunkier)
NUM_BARS = 48

# Frequency range to visualize (Hz) — lofi lives in this range
FREQ_LOW = 60
FREQ_HIGH = 4000

# Audio analysis settings
SAMPLE_RATE = 44100
FFT_SIZE = 4096          # Larger = better frequency resolution, slight latency
HOP_SIZE = 1470          # Samples per frame at 30fps (44100 / 30)
FPS = 30

# Temporal smoothing — prevents bars from jittering too fast.
# Each frame blends with the previous: new = old * DECAY + current * (1 - DECAY)
# Higher DECAY = smoother/slower response. 0.6 feels musical for lofi.
SMOOTHING_DECAY = 0.6

# Bar appearance
BAR_WIDTH_DEGREES = 4.0    # Angular width of each bar in degrees
BAR_MIN_LENGTH = 4         # Minimum bar length in pixels (always visible)
BAR_MAX_LENGTH = 100       # Maximum bar length in pixels at peak volume
BAR_COLOR = (255, 255, 255)  # Solid white bars — matches the golf ball wireframe
BAR_GLOW_COLOR = (255, 255, 255)  # White glow to match
BAR_ALPHA_MIN = 200        # Minimum alpha (even quiet bars are clearly visible)
BAR_ALPHA_MAX = 255        # Maximum alpha (full opacity at peak volume)

# Sensitivity multiplier — scales bar lengths before drawing.
# >1.0 = more reactive (bars extend further for the same audio level).
# Caps at 1.0 so bars never exceed the outer radius.
SENSITIVITY = 1.2


def render_golfquilizer(
    video_path: str,
    start_time: float,
    duration: float,
    output_path: str,
    ball_path: str,
    local_logger: logging.Logger = None,
) -> bool:
    """
    Render a YouTube Short with the Golfquilizer radial audio visualizer.

    Extracts audio, computes per-frame FFT, draws radial bars emanating
    outward from the golf ball, and composites everything into a final
    vertical (9:16) video.

    Args:
        video_path:   Path to the source long-form video.
        start_time:   Where to start extracting (seconds).
        duration:     Length of the Short (seconds).
        output_path:  Where to save the rendered Short.
        ball_path:    Path to the golf ball wireframe PNG (transparent bg).
        local_logger: Logger for progress messages.

    Returns:
        True if rendering succeeded, False otherwise.
    """
    local_logger = local_logger or logging.getLogger("fairway.golfquilizer")

    eq_size = config.GOLFQUILIZER_SIZE      # Canvas size for the visualizer
    ball_size = config.GOLFQUILIZER_BALL_SIZE  # Golf ball PNG display size

    # The bars radiate outward from the golf ball's edge.
    # Ball PNG is 720×720 with the ball circle centered at the image center.
    # At ball_size=700, ball outer radius ≈ 194px. inner_radius starts bars
    # just outside that edge with a 2px gap.
    inner_radius = 196                        # just outside ball outer stroke edge
    outer_radius = eq_size // 2 - 10          # Bars extend to edge of halo canvas

    total_frames = int(duration * FPS)

    local_logger.info(f"    Rendering radial visualizer: {NUM_BARS} bars, {total_frames} frames")

    # --- Step 1: Extract raw audio from the video segment ---
    local_logger.info("    Extracting audio for FFT analysis...")
    audio_samples = _extract_audio(video_path, start_time, duration, local_logger)
    if audio_samples is None:
        local_logger.warning("    ⚠️ Could not extract audio — skipping Golfquilizer")
        return False

    # --- Step 2: Compute FFT magnitudes for each frame ---
    local_logger.info("    Computing frequency spectrum per frame...")
    frame_magnitudes = _compute_frame_magnitudes(audio_samples, total_frames)

    # --- Step 3: Render radial bar overlay frames and pipe to FFmpeg ---
    local_logger.info("    Drawing radial bars and compositing video...")
    success = _render_composite(
        video_path=video_path,
        start_time=start_time,
        duration=duration,
        ball_path=ball_path,
        frame_magnitudes=frame_magnitudes,
        eq_size=eq_size,
        ball_size=ball_size,
        inner_radius=inner_radius,
        outer_radius=outer_radius,
        output_path=output_path,
        local_logger=local_logger,
    )

    if success and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        local_logger.info(f"    ✓ Golfquilizer rendered: {size_mb:.1f} MB")
        return True

    local_logger.warning("    ⚠️ Golfquilizer rendering failed")
    return False


# =============================================================================
# AUDIO EXTRACTION & FFT
# =============================================================================

def _extract_audio(
    video_path: str,
    start_time: float,
    duration: float,
    local_logger,
) -> np.ndarray:
    """
    Extract raw mono audio samples from a video segment using FFmpeg.

    Returns a numpy array of float64 samples normalized to [-1.0, 1.0],
    or None if extraction fails.
    """
    cmd = [
        "ffmpeg",
        "-ss", str(start_time),
        "-i", video_path,
        "-t", str(duration),
        "-f", "s16le",         # Raw 16-bit signed little-endian PCM
        "-ac", "1",            # Mono (we don't need stereo for visualization)
        "-ar", str(SAMPLE_RATE),
        "-acodec", "pcm_s16le",
        "pipe:1",              # Output to stdout
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, check=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        # Convert raw bytes to numpy array of int16, then normalize to float
        samples = np.frombuffer(result.stdout, dtype=np.int16).astype(np.float64)
        samples /= 32768.0  # Normalize int16 range to [-1.0, 1.0]
        return samples
    except subprocess.CalledProcessError as e:
        local_logger.warning(f"    Audio extraction failed: {e.stderr[-300:]}")
        return None


def _compute_frame_magnitudes(
    audio_samples: np.ndarray,
    total_frames: int,
) -> list:
    """
    Compute FFT magnitude spectrum for each video frame.

    For each frame, we take a window of audio samples centered on that
    frame's timestamp, apply a Hann window (reduces spectral leakage),
    compute the FFT, and extract magnitudes for NUM_BARS frequency bins
    spread across the FREQ_LOW to FREQ_HIGH range.

    Returns:
        List of numpy arrays, one per frame. Each array has NUM_BARS
        magnitude values normalized to [0.0, 1.0].
    """
    # Precompute which FFT bins correspond to our frequency range
    freqs = np.fft.rfftfreq(FFT_SIZE, 1.0 / SAMPLE_RATE)
    # Map NUM_BARS bars to logarithmically-spaced frequency bands
    # WHY log scale? Human hearing is logarithmic — each octave doubles
    # in frequency. Log spacing gives equal visual weight to bass and treble.
    log_low = math.log10(FREQ_LOW)
    log_high = math.log10(FREQ_HIGH)
    bar_edges = np.logspace(log_low, log_high, NUM_BARS + 1)

    # Find the FFT bin indices for each bar's frequency range
    bar_bin_ranges = []
    for i in range(NUM_BARS):
        low_bin = np.searchsorted(freqs, bar_edges[i])
        high_bin = np.searchsorted(freqs, bar_edges[i + 1])
        # Ensure at least one bin per bar
        if high_bin <= low_bin:
            high_bin = low_bin + 1
        bar_bin_ranges.append((low_bin, min(high_bin, len(freqs) - 1)))

    # Hann window for smooth FFT (reduces clicks/pops at window edges)
    window = np.hanning(FFT_SIZE)

    # Track the global max for normalization across all frames
    all_magnitudes = []
    global_max = 1e-10  # Avoid division by zero

    # Smoothed magnitudes from previous frame (for temporal smoothing)
    prev_mags = np.zeros(NUM_BARS)

    for frame_idx in range(total_frames):
        # Find the center sample for this frame
        center_sample = int(frame_idx * HOP_SIZE)
        start = center_sample - FFT_SIZE // 2
        end = start + FFT_SIZE

        # Extract the audio window, zero-padding if we're near the edges
        if start < 0:
            chunk = np.zeros(FFT_SIZE)
            chunk[-start:] = audio_samples[:end]
        elif end > len(audio_samples):
            chunk = np.zeros(FFT_SIZE)
            remaining = len(audio_samples) - start
            chunk[:remaining] = audio_samples[start:start + remaining]
        else:
            chunk = audio_samples[start:end].copy()

        # Apply Hann window and compute FFT
        windowed = chunk * window
        fft_result = np.abs(np.fft.rfft(windowed))

        # Average the FFT magnitudes within each bar's frequency range
        bar_mags = np.zeros(NUM_BARS)
        for i, (lo, hi) in enumerate(bar_bin_ranges):
            if hi > lo:
                bar_mags[i] = np.mean(fft_result[lo:hi])
            else:
                bar_mags[i] = fft_result[lo] if lo < len(fft_result) else 0

        # Temporal smoothing: blend with previous frame
        # This makes bars rise and fall smoothly instead of flickering
        bar_mags = prev_mags * SMOOTHING_DECAY + bar_mags * (1 - SMOOTHING_DECAY)
        prev_mags = bar_mags.copy()

        frame_max = np.max(bar_mags)
        if frame_max > global_max:
            global_max = frame_max

        all_magnitudes.append(bar_mags)

    # Normalize all frames to [0.0, 1.0] using the global max
    # This ensures consistent bar heights across the entire Short
    normalized = []
    for mags in all_magnitudes:
        normalized.append(mags / global_max)

    return normalized


# =============================================================================
# RADIAL BAR RENDERING
# =============================================================================

def _draw_radial_bars(
    magnitudes: np.ndarray,
    canvas_size: int,
    inner_radius: int,
    outer_radius: int,
) -> Image.Image:
    """
    Draw radial frequency bars on a transparent RGBA canvas.

    Each bar is a tapered trapezoid radiating outward from the center.
    Bar length is proportional to the FFT magnitude for that frequency.
    Bars are evenly distributed around the full 360 degrees.

    Args:
        magnitudes:    Array of NUM_BARS float values in [0.0, 1.0].
        canvas_size:   Width and height of the output image in pixels.
        inner_radius:  Where bars start (pixels from center).
        outer_radius:  Maximum extent of bars (pixels from center).

    Returns:
        PIL Image (RGBA) with radial bars drawn on transparent background.
    """
    # Create transparent canvas
    img = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    center_x = canvas_size // 2
    center_y = canvas_size // 2
    max_bar_length = outer_radius - inner_radius

    angle_step = 360.0 / NUM_BARS
    half_width_deg = BAR_WIDTH_DEGREES / 2.0

    for i in range(NUM_BARS):
        # Mirror: left and right halves are symmetric.
        # Frequencies run 0→24 clockwise from 12 o'clock to 6 o'clock,
        # then mirror back 23→0 from 6 o'clock to 12 o'clock.
        # Result: bass at top, treble at bottom, left = right.
        freq_idx = min(i, NUM_BARS - i) if i > 0 else 0
        mag = min(magnitudes[freq_idx] * SENSITIVITY, 1.0)

        # Bar length: minimum + scaled by magnitude
        bar_length = BAR_MIN_LENGTH + int(mag * (max_bar_length - BAR_MIN_LENGTH))
        bar_outer = inner_radius + bar_length

        # Angle for this bar (start from top, go clockwise)
        angle_deg = i * angle_step - 90  # -90 so bar 0 is at 12 o'clock
        angle_rad = math.radians(angle_deg)

        # Alpha based on magnitude — louder bars are more opaque
        alpha = int(BAR_ALPHA_MIN + mag * (BAR_ALPHA_MAX - BAR_ALPHA_MIN))

        # Draw the bar as a polygon (tapered: wider at base, narrower at tip)
        # Inner edge (wider)
        inner_half_w = math.radians(half_width_deg * 1.2)
        # Outer edge (narrower)
        outer_half_w = math.radians(half_width_deg * 0.7)

        # Four corners of the bar polygon
        points = [
            # Inner-left
            (center_x + inner_radius * math.cos(angle_rad - inner_half_w),
             center_y + inner_radius * math.sin(angle_rad - inner_half_w)),
            # Outer-left
            (center_x + bar_outer * math.cos(angle_rad - outer_half_w),
             center_y + bar_outer * math.sin(angle_rad - outer_half_w)),
            # Outer-right
            (center_x + bar_outer * math.cos(angle_rad + outer_half_w),
             center_y + bar_outer * math.sin(angle_rad + outer_half_w)),
            # Inner-right
            (center_x + inner_radius * math.cos(angle_rad + inner_half_w),
             center_y + inner_radius * math.sin(angle_rad + inner_half_w)),
        ]

        color = (*BAR_COLOR, alpha)
        draw.polygon(points, fill=color)

    # Add a soft glow effect by blurring a copy and compositing it behind
    glow = img.copy()
    glow = glow.filter(ImageFilter.GaussianBlur(radius=3))
    # Composite: glow behind, sharp bars on top
    result = Image.alpha_composite(glow, img)

    return result


# =============================================================================
# VIDEO COMPOSITION — Pipe frames to FFmpeg
# =============================================================================

def _render_composite(
    video_path: str,
    start_time: float,
    duration: float,
    ball_path: str,
    frame_magnitudes: list,
    eq_size: int,
    ball_size: int,
    inner_radius: int,
    outer_radius: int,
    output_path: str,
    local_logger,
) -> bool:
    """
    Render the final composited Golfquilizer Short.

    Strategy: Render each radial bar frame as a PNG, save them as a
    transparent video, then use FFmpeg to composite everything:
      Layer 1: Golf course (cropped 9:16)
      Layer 2: Radial bar overlay (transparent, centered)
      Layer 3: Golf ball PNG (centered on ball, tee hangs below)

    We write bar frames to a temporary directory and use FFmpeg's image
    sequence input to avoid piping raw RGBA (which can be unreliable
    on Windows with large frame counts).
    """
    total_frames = len(frame_magnitudes)

    # Create temp directory for bar overlay frames
    temp_dir = tempfile.mkdtemp(prefix="golfquilizer_")
    frames_pattern = os.path.join(temp_dir, "bar_%05d.png")

    try:
        # --- Render all bar overlay frames ---
        for frame_idx in range(total_frames):
            bar_img = _draw_radial_bars(
                magnitudes=frame_magnitudes[frame_idx],
                canvas_size=eq_size,
                inner_radius=inner_radius,
                outer_radius=outer_radius,
            )
            bar_img.save(
                os.path.join(temp_dir, f"bar_{frame_idx:05d}.png"),
                format="PNG",
            )

            # Log progress every 5 seconds of video
            if frame_idx > 0 and frame_idx % (FPS * 5) == 0:
                pct = int(frame_idx / total_frames * 100)
                local_logger.info(f"    Drawing frames: {pct}%...")

        local_logger.info("    Drawing frames: 100%")
        local_logger.info("    Compositing with FFmpeg...")

        # --- Build FFmpeg composite command ---
        # Input 0: source video (cropped to 9:16)
        # Input 1: bar overlay frames (transparent PNGs at 30fps)
        # Input 2: golf ball PNG (static image)
        #
        # ox/oy move the whole visualizer together.
        # bx/by nudge only the ball independently for fine alignment with the ring.
        ox = config.GOLFQUILIZER_OFFSET_X
        oy = config.GOLFQUILIZER_OFFSET_Y
        bx = config.GOLFQUILIZER_BALL_OFFSET_X
        by = config.GOLFQUILIZER_BALL_OFFSET_Y

        filter_complex = (
            # Crop source video to 9:16 vertical
            f"[0:v]crop=607:1080:(iw-607)/2:0,"
            f"scale={config.SHORTS_WIDTH}:{config.SHORTS_HEIGHT}:flags=lanczos[base];"

            # Scale bar overlay to match the eq_size
            f"[1:v]format=rgba,scale={eq_size}:{eq_size}:flags=lanczos[bars];"

            # Scale golf ball PNG, keep aspect ratio
            f"[2:v]format=rgba,scale={ball_size}:-1:flags=lanczos[ball];"

            # Overlay bar ring first (behind the ball)
            f"[base][bars]overlay=(main_w-overlay_w)/2+{ox}:(main_h-overlay_h)/2+{oy}:format=auto[with_bars];"

            # Overlay golf ball on top (in front of the bars)
            f"[with_bars][ball]overlay="
            f"(main_w-overlay_w)/2+{ox+bx}:"
            f"(main_h-overlay_h)/2+{oy+by}"
            f":format=auto[out]"
        )

        cmd = [
            "ffmpeg", "-y",
            # Input 0: source video
            "-ss", str(start_time),
            "-i", video_path,
            # Input 1: bar overlay frame sequence
            "-framerate", str(FPS),
            "-i", frames_pattern,
            # Input 2: golf ball PNG (looped as static image)
            "-i", ball_path,
            # Duration limit
            "-t", str(duration),
            # Filter graph
            "-filter_complex", filter_complex,
            # Output mapping
            "-map", "[out]",
            "-map", "0:a",
            # Encoding
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-t", str(duration),
            "-movflags", "+faststart",
            "-shortest",
            output_path,
        ]

        result = subprocess.run(
            cmd, capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

        if result.returncode != 0:
            local_logger.warning(
                f"    FFmpeg composite failed: {result.stderr[-500:]}"
            )
            return False

        return True

    finally:
        # Clean up temp frames
        import shutil
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass
