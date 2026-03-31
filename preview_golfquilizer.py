"""
Quick preview tool for the Golfquilizer.

Generates a single still frame so you can visually tune the ball size
and ring alignment without waiting for a full 45-second render.

Usage:
    python preview_golfquilizer.py              # Default ball_size (450)
    python preview_golfquilizer.py 400          # Try ball_size=400
    python preview_golfquilizer.py 500          # Try ball_size=500

Output: output/golfquilizer_preview.png
"""

import sys
import subprocess
import os
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

# Reuse constants from the pipeline
sys.path.insert(0, os.path.dirname(__file__))
import config
from pipeline.golfquilizer import (
    NUM_BARS, BAR_WIDTH_DEGREES, BAR_MIN_LENGTH, BAR_COLOR,
    BAR_ALPHA_MIN, BAR_ALPHA_MAX,
)
import math


def main():
    ball_size = int(sys.argv[1]) if len(sys.argv) > 1 else config.GOLFQUILIZER_BALL_SIZE
    eq_size = config.GOLFQUILIZER_SIZE

    inner_radius = 196  # just outside ball outer stroke edge
    outer_radius = eq_size // 2 - 10

    print(f"Ball size: {ball_size}px (ball circle ~{int(ball_size * 0.55)}px)")
    print(f"Bars: {inner_radius}px to {outer_radius}px (length: {outer_radius - inner_radius}px)")
    print(f"Halo size: {eq_size}px")
    print()

    # Extract a single frame from the video
    video = None
    for f in os.listdir(config.OUTPUT_DIR):
        if f.startswith("fairway_") and f.endswith(".mp4"):
            video = os.path.join(config.OUTPUT_DIR, f)
            break

    if not video:
        print("No video found in output/ — using a solid green background")
        bg = Image.new("RGB", (config.SHORTS_WIDTH, config.SHORTS_HEIGHT), (100, 160, 60))
    else:
        print(f"Using: {video}")
        # Extract and crop a frame to 9:16
        cmd = [
            "ffmpeg", "-y", "-ss", "60", "-i", video,
            "-frames:v", "1",
            "-vf", f"crop=607:1080:(iw-607)/2:0,scale={config.SHORTS_WIDTH}:{config.SHORTS_HEIGHT}:flags=lanczos",
            "output/golfquilizer_bg.png",
        ]
        subprocess.run(cmd, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        bg = Image.open("output/golfquilizer_bg.png").convert("RGBA")

    # Draw fake bars at various magnitudes (simulate a beat)
    bar_canvas = Image.new("RGBA", (eq_size, eq_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(bar_canvas)
    center = eq_size // 2
    max_bar_len = outer_radius - inner_radius
    angle_step = 360.0 / NUM_BARS

    for i in range(NUM_BARS):
        # Mirror: use same freq_idx logic as the real renderer
        freq_idx = min(i, NUM_BARS - i) if i > 0 else 0
        mag = 0.3 + 0.7 * abs(math.sin(freq_idx * 0.3))
        bar_length = BAR_MIN_LENGTH + int(mag * (max_bar_len - BAR_MIN_LENGTH))
        bar_outer = inner_radius + bar_length

        angle_deg = i * angle_step - 90
        angle_rad = math.radians(angle_deg)
        alpha = int(BAR_ALPHA_MIN + mag * (BAR_ALPHA_MAX - BAR_ALPHA_MIN))

        half_w = math.radians(BAR_WIDTH_DEGREES / 2)
        inner_hw = half_w * 1.2
        outer_hw = half_w * 0.7

        points = [
            (center + inner_radius * math.cos(angle_rad - inner_hw),
             center + inner_radius * math.sin(angle_rad - inner_hw)),
            (center + bar_outer * math.cos(angle_rad - outer_hw),
             center + bar_outer * math.sin(angle_rad - outer_hw)),
            (center + bar_outer * math.cos(angle_rad + outer_hw),
             center + bar_outer * math.sin(angle_rad + outer_hw)),
            (center + inner_radius * math.cos(angle_rad + inner_hw),
             center + inner_radius * math.sin(angle_rad + inner_hw)),
        ]
        draw.polygon(points, fill=(*BAR_COLOR, alpha))

    # Add glow
    glow = bar_canvas.copy().filter(ImageFilter.GaussianBlur(radius=3))
    bar_canvas = Image.alpha_composite(glow, bar_canvas)

    # Load golf ball
    ball_path = config.GOLFQUILIZER_BALL_WHITE
    if not os.path.exists(ball_path):
        ball_path = config.GOLFQUILIZER_BALL_BLACK
    ball_img = Image.open(ball_path).convert("RGBA")
    ball_img = ball_img.resize((ball_size, int(ball_size * ball_img.size[1] / ball_img.size[0])),
                                Image.LANCZOS)

    # Composite onto background
    result = bg.copy().convert("RGBA")
    frame_cx = config.SHORTS_WIDTH // 2
    frame_cy = config.SHORTS_HEIGHT // 2

    # ox/oy move everything together; bx/by nudge only the ball for fine alignment.
    ox = config.GOLFQUILIZER_OFFSET_X
    oy = config.GOLFQUILIZER_OFFSET_Y
    bx = config.GOLFQUILIZER_BALL_OFFSET_X
    by = config.GOLFQUILIZER_BALL_OFFSET_Y

    # Bars first (behind), then ball on top (in front)
    bar_x = frame_cx - eq_size // 2 + ox
    bar_y = frame_cy - eq_size // 2 + oy
    result.paste(bar_canvas, (bar_x, bar_y), bar_canvas)

    ball_x = frame_cx - ball_img.size[0] // 2 + ox + bx
    ball_y = frame_cy - ball_img.size[1] // 2 + oy + by
    result.paste(ball_img, (ball_x, ball_y), ball_img)

    # Draw reference circles for debugging
    debug = result.copy()
    debug_draw = ImageDraw.Draw(debug)
    # Ball center marker
    ball_center_y = frame_cy - int(ball_img.size[1] * 0.215)
    ring_center_y = bar_y + eq_size // 2

    out_path = "output/golfquilizer_preview.png"
    debug.save(out_path)
    print(f"\nSaved: {out_path}")
    print(f"\nTry different sizes:  python preview_golfquilizer.py {ball_size - 50}")
    print(f"                      python preview_golfquilizer.py {ball_size + 50}")


if __name__ == "__main__":
    main()
