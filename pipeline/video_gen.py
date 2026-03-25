# =============================================================================
# pipeline/video_gen.py — Kling AI Video Generation (Primary)
# =============================================================================
# PURPOSE:
#   Take the ONE base image and generate 10 animation clips from it using
#   Kling 2.6's image-to-video API. Each clip shows the same scene but with
#   slightly different subtle animation (different cloud movement, wind, etc.).
#
# WHY 10 clips from the SAME image? This is the core v3 "Living Painting"
# concept. When all clips share the same base composition, the 2-second
# crossfades between them are nearly invisible — the scene stays identical,
# only the animation differs. Result: one seamless, living painting for hours.
#
# WHY Kling? Kling 2.6 offers:
#   - 120-second clips (longest available — fewer clips needed)
#   - Best quality image-to-video for illustrated/anime style
#   - Direct API (no markup, full feature access)
#   - Reasonable cost per minute of video
#
# KLING AUTH: Kling uses JWT (JSON Web Token) authentication.
#   A JWT is like a digital "badge" that expires after 30 minutes.
#   We create a new one for each API call to stay fresh.
#
# API DOCS: https://platform.klingai.com/docs
# =============================================================================

import os         # For file operations
import time       # For polling delays and JWT timestamps
import logging    # For progress messages
import base64     # For encoding the image to send to Kling
import requests   # For HTTP API calls

# PyJWT is the library for creating JWT tokens (for Kling authentication)
# Install with: pip install PyJWT
import jwt

import config     # Our settings

logger = logging.getLogger("fairway.video_gen")

# Kling API endpoints (verify at https://platform.klingai.com/docs if these change)
KLING_BASE_URL = "https://api.klingai.com/v1"
KLING_SUBMIT_URL = f"{KLING_BASE_URL}/videos/image2video"
KLING_STATUS_URL = f"{KLING_BASE_URL}/videos/image2video"  # + /{task_id}

# Polling settings
POLL_INTERVAL = 10     # Check status every 10 seconds
MAX_WAIT_SECONDS = 600 # Wait up to 10 minutes per clip (they typically take 2-4 min)

# Minimum clips needed to proceed with video assembly
MIN_CLIPS_REQUIRED = 4  # Minimum to proceed (out of NUM_ANIMATION_CLIPS total)


def generate_animation_clips(
    base_image_path: str,
    base_video_prompt: str,
    animation_variations: list,
    num_clips: int,
    clips_dir: str,
    kling_access_key: str,
    kling_secret_key: str,
    logger: logging.Logger = None,
) -> list:
    """
    Generate multiple animation clips from the same base image using Kling.

    This is Stage 3 of the pipeline. We call Kling's image-to-video endpoint
    once for each of the 10 animation variations. Each call uses the SAME
    base image but a DIFFERENT animation prompt variation. This creates 10
    versions of the same scene, each with slightly different subtle motion.

    Args:
        base_image_path:      Path to the base image file (the ONE image we generated).
        base_video_prompt:    Base animation direction from the orchestrator.
        animation_variations: List of 10 unique animation prompt variations.
        num_clips:            How many clips to generate (default: 10).
        clips_dir:            Directory to save the downloaded clips.
        kling_access_key:     Kling API access key.
        kling_secret_key:     Kling API secret key.
        logger:               Logger instance for progress messages.

    Returns:
        List of paths to successfully downloaded clip files.

    Raises:
        RuntimeError: If fewer than MIN_CLIPS_REQUIRED clips succeed.
    """
    local_logger = logger or logging.getLogger("fairway.video_gen")

    if not kling_access_key or not kling_secret_key:
        raise ValueError(
            "KLING_ACCESS_KEY and KLING_SECRET_KEY must be set in your .env file.\n"
            "Get your keys at: https://platform.klingai.com/\n"
            "Or switch to Luma: set VIDEO_MODEL = 'luma' in config.py"
        )

    # Load the base image and encode it as base64
    # WHY base64? The Kling API accepts images as base64-encoded strings
    # embedded in the JSON request body. Base64 converts binary image data
    # into text characters that can be safely included in JSON.
    local_logger.info(f"  Loading base image: {base_image_path}")
    image_b64 = _encode_image_to_base64(base_image_path)
    local_logger.info(f"  Image loaded and encoded ({len(image_b64)//1024}KB base64)")

    # Submit all clips (don't wait — we'll poll for completion after)
    # WHY submit all then poll? Starting all 10 jobs simultaneously means they
    # can run in parallel on Kling's servers, cutting total wait time roughly in half.
    submitted_tasks = []

    for i in range(num_clips):
        # Combine the base prompt with this clip's unique animation variation
        variation = animation_variations[i] if i < len(animation_variations) else animation_variations[i % len(animation_variations)]
        full_prompt = f"{base_video_prompt}. {variation}"

        local_logger.info(f"  Submitting clip {i+1}/{num_clips}: {variation[:60]}...")

        try:
            task_id = _submit_clip(
                image_b64=image_b64,
                prompt=full_prompt,
                access_key=kling_access_key,
                secret_key=kling_secret_key,
            )
            submitted_tasks.append({"index": i + 1, "task_id": task_id, "variation": variation})
            local_logger.info(f"  ✓ Clip {i+1} submitted (task: {task_id})")

        except Exception as e:
            local_logger.warning(f"  ⚠️ Clip {i+1} submission failed: {e}")

        # Small delay between submissions to be respectful to the API
        # WHY wait? Submitting 10 requests at once can trigger rate limits.
        # 2 seconds between submissions is barely noticeable but much safer.
        if i < num_clips - 1:
            time.sleep(2)

    if not submitted_tasks:
        raise RuntimeError(
            "All clip submissions failed. Check your Kling API keys and connection."
        )

    local_logger.info(f"\n  {len(submitted_tasks)}/{num_clips} clips submitted. Waiting for completion...")
    local_logger.info("  (Kling typically takes 2–4 minutes per clip)")

    # Now poll all submitted tasks until they complete
    successful_clips = []

    for task_info in submitted_tasks:
        clip_num = task_info["index"]
        task_id = task_info["task_id"]

        local_logger.info(f"  Waiting for clip {clip_num}/{num_clips}...")

        try:
            video_url = _poll_for_completion(
                task_id=task_id,
                access_key=kling_access_key,
                secret_key=kling_secret_key,
                clip_num=clip_num,
            )

            # Download the completed clip
            clip_filename = f"clip_{clip_num:02d}.mp4"
            clip_path = os.path.join(clips_dir, clip_filename)
            _download_video(url=video_url, save_path=clip_path)

            successful_clips.append(clip_path)
            local_logger.info(f"  ✓ Clip {clip_num} downloaded: {clip_filename}")

        except Exception as e:
            local_logger.warning(f"  ⚠️ Clip {clip_num} failed: {e}")

    # Check if we got enough clips to proceed
    if len(successful_clips) < MIN_CLIPS_REQUIRED:
        raise RuntimeError(
            f"Only {len(successful_clips)} of {num_clips} clips succeeded "
            f"(minimum {MIN_CLIPS_REQUIRED} required).\n"
            "Check the logs for error details. Common issues:\n"
            "  - Kling API rate limit (wait a few minutes and --resume)\n"
            "  - Image content was flagged (try a different image)\n"
            "  - API keys expired (check platform.klingai.com)"
        )

    local_logger.info(f"\n  ✓ {len(successful_clips)}/{num_clips} clips ready")
    return successful_clips


def _generate_jwt_token(access_key: str, secret_key: str) -> str:
    """
    Generate a JWT (JSON Web Token) for Kling API authentication.

    WHY JWT? Kling uses JWT instead of simple API keys for security.
    A JWT is a cryptographically signed token that:
    - Contains who you are (access_key as the "issuer")
    - Has an expiry time (30 minutes from now)
    - Is signed with your secret key so it can't be faked

    The token must be fresh for each request — we create a new one each time.

    Args:
        access_key: Your Kling access key.
        secret_key: Your Kling secret key (used to sign the token).

    Returns:
        A JWT token string to use in the Authorization header.
    """
    now = int(time.time())  # Current Unix timestamp (seconds since Jan 1, 1970)

    payload = {
        "iss": access_key,  # "issuer" — identifies who you are
        "exp": now + 1800,  # Expires in 30 minutes (1800 seconds)
        "nbf": now - 5,     # "not before" — valid starting 5 seconds ago
                             # WHY -5? Accounts for tiny clock differences between
                             # your machine and Kling's servers.
    }

    # Sign the payload with the secret key using the HS256 algorithm
    # HS256 = HMAC-SHA256 — a standard cryptographic signing method
    token = jwt.encode(payload, secret_key, algorithm="HS256")

    return token


def _encode_image_to_base64(image_path: str) -> str:
    """
    Read an image file and encode it as a base64 string.

    WHY base64? The Kling API expects the image embedded in the JSON
    request body. JSON is text-only, but images are binary data.
    Base64 encoding converts binary → text so it fits in JSON.

    Args:
        image_path: Path to the image file.

    Returns:
        Base64-encoded string of the image data.
    """
    with open(image_path, "rb") as f:  # "rb" = read in binary mode
        image_data = f.read()

    return base64.b64encode(image_data).decode("utf-8")


def _submit_clip(
    image_b64: str,
    prompt: str,
    access_key: str,
    secret_key: str,
) -> str:
    """
    Submit one image-to-video generation request to Kling.

    Args:
        image_b64:   Base64-encoded image string.
        prompt:      Full animation prompt (base + variation).
        access_key:  Kling access key.
        secret_key:  Kling secret key.

    Returns:
        Task ID string for polling.

    Raises:
        RuntimeError: If submission fails.
    """
    # Generate a fresh JWT token for this request
    token = _generate_jwt_token(access_key, secret_key)

    response = requests.post(
        KLING_SUBMIT_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "model_name": config.KLING_MODEL,      # Set in config.py — change to upgrade
            "image": image_b64,                    # The base image (base64 encoded)
            "prompt": prompt,                      # Animation description
            "duration": config.KLING_CLIP_DURATION, # "5" or "10" seconds — set in config.py
            "aspect_ratio": "16:9",                # YouTube standard
            "cfg_scale": 0.5,                      # How closely to follow the prompt
                                                   # 0.0-1.0, 0.5 = balanced
        },
        timeout=30,
    )

    if response.status_code not in (200, 201):
        raise RuntimeError(
            f"Kling submission failed (HTTP {response.status_code}): {response.text[:300]}"
        )

    data = response.json()

    # Navigate the response structure to find the task ID
    # The Kling API wraps responses in a data object
    task_id = (
        data.get("data", {}).get("task_id")  # Standard location
        or data.get("task_id")               # Fallback location
    )

    if not task_id:
        raise RuntimeError(
            f"Kling didn't return a task ID. Response: {data}"
        )

    return task_id


def _poll_for_completion(
    task_id: str,
    access_key: str,
    secret_key: str,
    clip_num: int,
) -> str:
    """
    Poll Kling until a clip is done generating, then return its download URL.

    Args:
        task_id:    The task ID from the submission step.
        access_key: Kling access key.
        secret_key: Kling secret key.
        clip_num:   Clip number (for log messages).

    Returns:
        URL to download the generated video.

    Raises:
        RuntimeError: If the clip fails or times out.
    """
    start_time = time.time()

    while True:
        elapsed = time.time() - start_time

        if elapsed > MAX_WAIT_SECONDS:
            raise RuntimeError(
                f"Clip {clip_num} timed out after {MAX_WAIT_SECONDS}s.\n"
                "Use --resume to retry just this clip."
            )

        # Generate a fresh JWT for this poll request
        token = _generate_jwt_token(access_key, secret_key)

        response = requests.get(
            f"{KLING_STATUS_URL}/{task_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )

        if response.status_code != 200:
            logger.warning(f"  Clip {clip_num} poll returned {response.status_code}, retrying...")
            time.sleep(POLL_INTERVAL)
            continue

        data = response.json()

        # Navigate to the task status in the response
        task_data = data.get("data", data)
        status = task_data.get("task_status", "").lower()

        if status in ("succeed", "completed", "success"):
            # Find the video URL in the response
            # Kling nests it under works[0].resource_list[0].resource
            works = task_data.get("task_result", {}).get("videos", [])
            if works:
                video_url = works[0].get("url")
                if video_url:
                    logger.debug(f"  Clip {clip_num} complete after {elapsed:.0f}s")
                    return video_url

            raise RuntimeError(
                f"Clip {clip_num} shows completed but no video URL found. Response: {data}"
            )

        elif status in ("failed", "error"):
            error_msg = task_data.get("task_status_msg", "Unknown error")
            raise RuntimeError(
                f"Clip {clip_num} generation failed: {error_msg}"
            )

        # Still processing — wait and check again
        # Show elapsed time so user knows it's still working
        if int(elapsed) % 30 == 0 and elapsed > 0:
            logger.info(f"  Clip {clip_num} still processing... ({elapsed:.0f}s)")

        time.sleep(POLL_INTERVAL)


def _download_video(url: str, save_path: str):
    """
    Download a video file from a URL and save it to disk.

    Args:
        url:       Video URL to download.
        save_path: Where to save the file.
    """
    os.makedirs(os.path.dirname(save_path), exist_ok=True)

    response = requests.get(url, timeout=120, stream=True)

    if response.status_code != 200:
        raise RuntimeError(
            f"Video download failed (HTTP {response.status_code}): {url}"
        )

    with open(save_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=1024 * 1024):  # 1MB chunks
            f.write(chunk)

    size_mb = os.path.getsize(save_path) / (1024 * 1024)
    logger.debug(f"  Downloaded {size_mb:.1f}MB to {save_path}")
