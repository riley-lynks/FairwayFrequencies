# =============================================================================
# config.py — Fairway Frequencies Configuration
# =============================================================================
# This file is the SINGLE SOURCE OF TRUTH for every setting in the pipeline.
# Think of it as the control panel for your video factory.
#
# HOW TO USE:
#   - Change values here to customize your videos
#   - All your API keys go in the .env file (NOT here — that keeps them secret)
#   - Every setting has a comment explaining what it does and why
#
# After changing settings, just re-run fairway.py — no restart needed.
# =============================================================================

import os
from dotenv import load_dotenv  # reads your .env file and makes API keys available

# Load API keys from the .env file into the environment.
# This must happen BEFORE we try to read any API key values below.
# WHY: We store API keys in .env (not this file) so they don't accidentally
# get shared. The .env file is listed in .gitignore.
load_dotenv(override=True)  # override=True forces .env values to win even if the
                            # variable already exists in the system environment

# =============================================================================
# API KEYS — Read from .env file
# =============================================================================
# os.getenv("KEY_NAME") reads the value from your .env file.
# If the key is missing, it returns None (we check for that at startup).

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")   # Claude — prompt decomposition + metadata
BFL_API_KEY = os.getenv("BFL_API_KEY")               # Black Forest Labs — Flux 2 image gen
MUBERT_API_KEY = os.getenv("MUBERT_API_KEY")         # Mubert — LoFi music generation
FREESOUND_API_KEY = os.getenv("FREESOUND_API_KEY")   # Freesound — ambient golf sounds
YOUTUBE_CLIENT_ID = os.getenv("YOUTUBE_CLIENT_ID")   # YouTube — auto-upload (optional)
YOUTUBE_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET")  # YouTube — auto-upload (optional)

# =============================================================================
# ART STYLE — The Most Important Setting
# =============================================================================
# This suffix is automatically appended to EVERY image prompt in the pipeline.
# WHY: Consistency is everything for a YouTube channel brand. Every video
# should look like it belongs to the same world. This suffix forces every
# AI image to use the same anime/Ghibli aesthetic, no matter what scene
# prompt the user provides.
#
# DO NOT change this unless you want to completely rebrand the channel.
# Every word here was carefully chosen:
#   - "detailed anime background painting" = the core style instruction
#   - "Studio Ghibli inspired" = the specific aesthetic reference
#   - "vibrant saturated colors" = rich, not washed-out
#   - "clean linework" = not photorealistic, illustrated
#   - "16:9 widescreen composition" = correct YouTube aspect ratio
#   - "no text, no UI elements" = clean image, no watermarks/UI

STYLE_SUFFIX = (
    "in the style of a detailed anime background painting, "
    "Studio Ghibli inspired, vibrant saturated colors, clean linework, "
    "lush detailed landscape, warm natural lighting, soft puffy clouds, "
    "visible brushstroke texture, concept art quality, "
    "16:9 widescreen composition, no text, no UI elements"
)

# =============================================================================
# IMAGE GENERATION — Which path to use
# =============================================================================
# "midjourney" = YOU generate images in Midjourney and drop them in
#                assets/midjourney_images/. Best quality for this art style.
#                The pipeline will print the exact Midjourney prompt to copy.
#
# "flux"       = Fully automated. Pipeline calls Black Forest Labs' Flux 2 API.
#                Slightly lower quality for this art style, but hands-off.
#
# WHY separate paths? Midjourney still produces the best anime/Ghibli
# landscapes of any AI image tool. But it requires manual steps. Flux
# is almost as good and runs while you sleep.

IMAGE_SOURCE = "midjourney"  # "midjourney" or "flux"

# =============================================================================
# CHARACTER FIGURE — Lofi Girl-style foreground character
# =============================================================================
# Controls whether a figure appears in the foreground of the scene.
# Like the iconic Lofi Girl, a character makes the video feel inhabited and cozy.
#
# "always"  = always include a character
# "never"   = pure landscape, no character
# "random"  = 40% chance of including a character (good variety across videos)

INCLUDE_CHARACTER = "random"

# These are the character descriptions that get included in image prompts.
# The orchestrator picks one randomly when a character is included.
# WHY back-turned / side view? This is the classic Lofi Girl aesthetic —
# the viewer looks WITH the character at the scene, not AT the character.
# It creates a sense of shared contemplation.
CHARACTER_OPTIONS = [
    "a golfer sitting on a wooden bench overlooking the course, "
    "back turned to viewer, looking out at the fairway, wearing a light jacket",

    "a person sitting in a golf cart at rest, side view, "
    "watching the scenery, relaxed posture, soft afternoon light",

    "a caddy leaning against a golf bag, reading a book, "
    "side profile view, seated under a tree near the green",

    "a lone figure sitting cross-legged under a large oak tree near the fairway, "
    "back to viewer, looking out at the misty course",
]

# =============================================================================
# VIDEO DURATION
# =============================================================================
# Target length of the final YouTube video in hours.
# WHY 2.0 hours? LoFi study/relaxation videos perform best at 2–3 hours.
# Viewers use them as background music during long work sessions.
# 2.0 is the minimum recommended. 3.0 is even better for algorithm retention.

TARGET_DURATION_HOURS = 2.0  # Final video length (hours). Try 2.0 or 3.0.

# =============================================================================
# VIDEO SETTINGS
# =============================================================================
VIDEO_RESOLUTION = "1920x1080"  # 1080p — standard YouTube quality
VIDEO_WIDTH = 1920               # Pixel width (used by FFmpeg)
VIDEO_HEIGHT = 1080              # Pixel height (used by FFmpeg)
VIDEO_FPS = 30                   # Frames per second — smooth without being too large
VIDEO_BITRATE = "10M"            # Output video bitrate. 8M–12M is good for YouTube.

# =============================================================================
# VIDEO CLIPS — Manual Workflow
# =============================================================================
# Generate clips externally (Veo, Kling, Runway, Pika, etc.) and drop them
# into this folder. The pipeline reads them and assembles the final video.
#
# WORKFLOW:
#   1. Generate your clips in your preferred tool (Veo, Kling, etc.)
#   2. Save them to a named subfolder: assets/video_clips/my_scene/
#   3. Run: python fairway.py "scene description" --clips-folder my_scene

VIDEO_CLIPS_DIR = "./assets/video_clips/"  # Where you save your generated clips

# =============================================================================
# ANIMATION CLIPS — v3 Living Painting System
# =============================================================================
# In v3, we generate ONE base image and then create multiple short animation
# clips from that SAME image. Each clip shows the same scene but with
# slightly different motion (clouds moving differently, flag waving more, etc.).
#
# WHY: When you loop 10 clips from the same base image, the transitions
# between clips are nearly invisible — the composition is identical, only
# the animation differs. This creates the illusion of one endless, living painting.

NUM_ANIMATION_CLIPS = 6   # How many Kling clips to generate (and how many prompts
                           # --prompts-only prints). More clips = more variety in
                           # the loop. 6 is a good balance of variety vs. effort.

# Seconds of crossfade overlap between clips at loop points.
# WHY 2 seconds? Short enough to be invisible (the composition doesn't change),
# long enough to smooth out any motion discontinuity between clips.
# Since all clips share the same base image, even a 1-second fade is nearly invisible.
LOOP_BLEND_SECONDS = 2  # Crossfade duration between animation clips (seconds)

# =============================================================================
# ANIMATION PROMPT STRUCTURE — Camera-Lock Format
# =============================================================================
# Kling weighs the BEGINNING of prompts most heavily. Camera lock instructions
# MUST come first to prevent camera shake. Each variation follows this template:
#
#   1. Camera lock  → "Tripod shot, fixed camera, no zoom, no camera movement."
#   2. Element anim → What specific scene elements move (and how).
#   3. Static lock  → "Static background, original composition maintained."
#
# The negative_prompt is sent to Kling's separate "Negative Prompt" field —
# it actively suppresses camera movement even when the positive prompt is followed.
# =============================================================================

# The negative prompt string is identical for every clip — always use this.
DEFAULT_NEGATIVE_PROMPT = (
    "camera shake, camera movement, camera pan, camera tilt, zoom, "
    "tracking shot, dolly, handheld, shaky cam, motion blur, scene change"
)

# Default animation variations used when Claude is not available.
# Claude generates scene-specific versions of these during orchestration.
# Each entry is a dict with "prompt" and "negative_prompt" keys.
ANIMATION_VARIATIONS = [
    {
        "prompt": (
            "Tripod shot, fixed camera, no zoom, no camera movement. "
            "Flag waving softly in light breeze, grass swaying gently, "
            "soft ripples on water surface, flowers with subtle movement. "
            "Static background, original composition maintained."
        ),
        "negative_prompt": DEFAULT_NEGATIVE_PROMPT,
    },
    {
        "prompt": (
            "Tripod shot, fixed camera, no zoom, no camera movement. "
            "Mostly still scene, single bird flying slowly across distant sky, "
            "very subtle atmospheric shimmer. "
            "Static background, original composition maintained."
        ),
        "negative_prompt": DEFAULT_NEGATIVE_PROMPT,
    },
    {
        "prompt": (
            "Tripod shot, fixed camera, no zoom, no camera movement. "
            "Soft breeze through foliage, trees with gentle leaf flutter, "
            "flower petals drifting slowly through air. "
            "Static background, original composition maintained."
        ),
        "negative_prompt": DEFAULT_NEGATIVE_PROMPT,
    },
    {
        "prompt": (
            "Tripod shot, fixed camera, no zoom, no camera movement. "
            "Calm peaceful scene, water with gentle ripple animation, "
            "flag waving steadily, barely perceptible light shift. "
            "Static background, original composition maintained."
        ),
        "negative_prompt": DEFAULT_NEGATIVE_PROMPT,
    },
    {
        "prompt": (
            "Tripod shot, fixed camera, no zoom, no camera movement. "
            "Subtle breeze animation, grass rippling softly, "
            "leaves on trees shifting gently, small butterfly floating through foreground. "
            "Static background, original composition maintained."
        ),
        "negative_prompt": DEFAULT_NEGATIVE_PROMPT,
    },
    {
        "prompt": (
            "Tripod shot, fixed camera, no zoom, no camera movement. "
            "Very gentle overall scene breathing, soft atmospheric movement, "
            "flag gently waving, flowers swaying slightly. "
            "Static background, original composition maintained."
        ),
        "negative_prompt": DEFAULT_NEGATIVE_PROMPT,
    },
]

# =============================================================================
# AUDIO SETTINGS
# =============================================================================
MUSIC_VOLUME = 0.85      # Music loudness (0.0 = silent, 1.0 = full volume)
                          # 0.85 leaves headroom for the music to breathe

AMBIENCE_VOLUME = 0.20   # Ambient sound volume (golf course sounds, rain, birds)
                          # Keep this LOW — it should be felt, not heard prominently

INCLUDE_AMBIENCE = True  # Set to False for music-only videos (no golf sounds)
                          # Can also be overridden per-run with --no-ambience flag

# =============================================================================
# AI MODEL SETTINGS
# =============================================================================
CLAUDE_MODEL = "claude-sonnet-4-6"  # Claude model for orchestration + metadata
                                      # claude-sonnet-4-6 is fast and very capable

# =============================================================================
# RELIABILITY SETTINGS
# =============================================================================
MAX_RETRIES = 3         # How many times to retry a failed API call before giving up
RETRY_BASE_DELAY = 5    # Seconds to wait before first retry. Doubles each attempt.
                         # (5s → 10s → 20s) This is "exponential backoff" —
                         # it gives overloaded APIs time to recover.

# =============================================================================
# OUTPUT SETTINGS
# =============================================================================
OUTPUT_DIR = "./output"  # Where finished videos, thumbnails, and metadata go
LOG_DIR = "./logs"       # Where generation logs are stored for debugging
