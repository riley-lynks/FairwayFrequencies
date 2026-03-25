# =============================================================================
# pipeline/video_gen_luma.py — Luma Ray 3 Video Generation (Backup)
# =============================================================================
# PURPOSE:
#   Backup video generator used when Kling is unavailable or configured.
#   Uses Luma's Dream Machine API to generate animation clips from the base image.
#
# WHY a backup? API services go down. Kling can have outages or rate limit you.
# Having Luma as a fallback means your pipeline never completely stops working.
# You can also set VIDEO_MODEL = "luma" in config.py to always use Luma.
#
# LUMA vs KLING:
#   - Luma clips: 5-10 seconds each (much shorter than Kling's 120s)
#   - This means we need more clips (40 instead of 10) for a 2-hour video
#   - Luma's "key frame" feature is great: set start and end frame to the same
#     image for a seamless "breathing" animation loop
#
# API DOCS: https://lumalabs.ai/dream-machine/api/docs
# =============================================================================

import os
import time
import logging
import requests
import base64
import tempfile

import config

logger = logging.getLogger("fairway.video_gen_luma")

# Luma API endpoints (verify at https://lumalabs.ai/dream-machine/api/docs)
LUMA_BASE_URL = "https://api.lumalabs.ai/dream-machine/v1"
LUMA_SUBMIT_URL = f"{LUMA_BASE_URL}/generations"
LUMA_STATUS_URL = f"{LUMA_BASE_URL}/generations"  # + /{id}

POLL_INTERVAL = 8
MAX_WAIT_SECONDS = 300  # Luma is faster than Kling, 5 min should be plenty
MIN_CLIPS_REQUIRED = 6


def generate_clips_luma(
    base_image_path: str,
    base_video_prompt: str,
    animation_variations: list,
    num_clips: int,
    clips_dir: str,
    api_key: str,
    logger: logging.Logger = None,
) -> list:
    """
    Generate animation clips using Luma Ray 3 as a backup to Kling.

    Luma produces shorter clips (5-10 seconds), so we generate more of them.
    Luma's key strength for our use case: the "key frame" feature lets us
    set the same image as both start and end frame, creating a gentle
    "breathing" animation that loops naturally.

    Args:
        base_image_path:      Path to the base image.
        base_video_prompt:    Base animation direction.
        animation_variations: List of animation prompt variations.
        num_clips:            Number of clips to generate.
        clips_dir:            Directory to save clips.
        api_key:              Luma API key.
        logger:               Logger instance.

    Returns:
        List of paths to downloaded clip files.

    Raises:
        RuntimeError: If fewer than MIN_CLIPS_REQUIRED clips succeed.
    """
    local_logger = logger or logging.getLogger("fairway.video_gen_luma")

    if not api_key:
        raise ValueError(
            "LUMA_API_KEY is not set in your .env file.\n"
            "Get your key at: https://lumalabs.ai/\n"
            "Or use Kling: set VIDEO_MODEL = 'kling' in config.py"
        )

    local_logger.info("  Using Luma Ray 3 (backup video generator)")
    local_logger.info(f"  Generating {num_clips} animation clips...")

    # Upload the base image to get a URL that Luma can access
    # WHY upload? Luma's API takes image URLs, not base64 data.
    # We upload to their upload endpoint to get a hosted URL.
    image_url = _upload_image_to_luma(base_image_path, api_key, local_logger)
    local_logger.info(f"  Image uploaded to Luma: {image_url[:60]}...")

    # Submit all clips
    submitted_tasks = []
    for i in range(num_clips):
        variation = animation_variations[i] if i < len(animation_variations) else animation_variations[i % len(animation_variations)]
        full_prompt = f"{base_video_prompt}. {variation}"

        local_logger.info(f"  Submitting clip {i+1}/{num_clips}...")

        try:
            task_id = _submit_luma_clip(
                image_url=image_url,
                prompt=full_prompt,
                api_key=api_key,
            )
            submitted_tasks.append({"index": i + 1, "task_id": task_id})
            local_logger.info(f"  ✓ Clip {i+1} submitted (id: {task_id})")

        except Exception as e:
            local_logger.warning(f"  ⚠️ Clip {i+1} submission failed: {e}")

        if i < num_clips - 1:
            time.sleep(1)

    if not submitted_tasks:
        raise RuntimeError("All Luma clip submissions failed.")

    # Poll for completion and download
    successful_clips = []

    for task_info in submitted_tasks:
        clip_num = task_info["index"]
        task_id = task_info["task_id"]

        local_logger.info(f"  Waiting for clip {clip_num}/{num_clips}...")

        try:
            video_url = _poll_luma_completion(task_id, api_key, clip_num)
            clip_path = os.path.join(clips_dir, f"clip_{clip_num:02d}.mp4")
            _download_video(video_url, clip_path)
            successful_clips.append(clip_path)
            local_logger.info(f"  ✓ Clip {clip_num} downloaded")

        except Exception as e:
            local_logger.warning(f"  ⚠️ Clip {clip_num} failed: {e}")

    if len(successful_clips) < MIN_CLIPS_REQUIRED:
        raise RuntimeError(
            f"Only {len(successful_clips)}/{num_clips} Luma clips succeeded "
            f"(minimum {MIN_CLIPS_REQUIRED} required)."
        )

    local_logger.info(f"  ✓ {len(successful_clips)}/{num_clips} Luma clips ready")
    return successful_clips


def _upload_image_to_luma(image_path: str, api_key: str, local_logger) -> str:
    """
    Upload an image to Luma and get back a URL.

    Luma's API takes image URLs (not base64), so we need to upload first.
    Luma provides an upload endpoint that returns a hosted URL.

    Args:
        image_path:   Local path to the image file.
        api_key:      Luma API key.
        local_logger: Logger.

    Returns:
        URL of the uploaded image.
    """
    local_logger.debug("  Uploading image to Luma...")

    # Request an upload URL from Luma
    upload_response = requests.post(
        f"{LUMA_BASE_URL}/generations/file_upload",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"file_type": "image"},
        timeout=30,
    )

    if upload_response.status_code not in (200, 201):
        # Fall back to using a local HTTP server approach or just pass the path
        # Since we can't always get an upload endpoint, we'll try with a temp upload
        local_logger.warning(
            "  Luma upload endpoint unavailable. Trying alternative method..."
        )
        # Return a placeholder — the Luma API may accept file: URLs in some contexts
        # For production, consider hosting images on S3 or similar
        raise RuntimeError(
            "Luma image upload failed. Please host your base image online "
            "and set IMAGE_SOURCE = 'flux' which handles this automatically.\n"
            "Or use Kling (recommended): set VIDEO_MODEL = 'kling' in config.py"
        )

    upload_data = upload_response.json()
    upload_url = upload_data.get("upload_url")
    file_url = upload_data.get("public_url") or upload_data.get("url")

    # Upload the actual image file to the signed URL
    with open(image_path, "rb") as f:
        put_response = requests.put(upload_url, data=f, timeout=60)

    if put_response.status_code not in (200, 204):
        raise RuntimeError(f"Image upload to signed URL failed: {put_response.status_code}")

    return file_url


def _submit_luma_clip(image_url: str, prompt: str, api_key: str) -> str:
    """
    Submit one generation request to Luma Dream Machine.

    We use the "key frames" feature to set the same image as both
    start and end frame. This creates a circular animation that loops
    naturally — the scene starts and ends in the same state.

    Args:
        image_url: URL of the uploaded base image.
        prompt:    Full animation prompt.
        api_key:   Luma API key.

    Returns:
        Generation ID for polling.
    """
    response = requests.post(
        LUMA_SUBMIT_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "prompt": prompt,
            "keyframes": {
                # Using the same image for both start and end creates a loop
                # WHY? The video starts and ends at the same visual state.
                # When we loop multiple clips together, the transitions are
                # extra invisible because each clip already starts where it ends.
                "frame0": {"type": "image", "url": image_url},
            },
            "loop": True,         # Tell Luma to generate a loopable animation
            "aspect_ratio": "16:9",
        },
        timeout=30,
    )

    if response.status_code not in (200, 201):
        raise RuntimeError(
            f"Luma submission failed (HTTP {response.status_code}): {response.text[:300]}"
        )

    data = response.json()
    generation_id = data.get("id")

    if not generation_id:
        raise RuntimeError(f"Luma didn't return a generation ID. Response: {data}")

    return generation_id


def _poll_luma_completion(task_id: str, api_key: str, clip_num: int) -> str:
    """
    Poll Luma until the generation is complete.

    Args:
        task_id:  Generation ID from submission.
        api_key:  Luma API key.
        clip_num: Clip number for logging.

    Returns:
        URL to download the generated video.
    """
    start_time = time.time()

    while True:
        elapsed = time.time() - start_time

        if elapsed > MAX_WAIT_SECONDS:
            raise RuntimeError(
                f"Luma clip {clip_num} timed out after {MAX_WAIT_SECONDS}s."
            )

        response = requests.get(
            f"{LUMA_STATUS_URL}/{task_id}",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15,
        )

        if response.status_code != 200:
            time.sleep(POLL_INTERVAL)
            continue

        data = response.json()
        state = data.get("state", "").lower()

        if state == "completed":
            video_url = data.get("assets", {}).get("video")
            if not video_url:
                raise RuntimeError(f"Luma shows completed but no video URL. Response: {data}")
            return video_url

        elif state == "failed":
            failure_reason = data.get("failure_reason", "Unknown error")
            raise RuntimeError(f"Luma clip {clip_num} failed: {failure_reason}")

        time.sleep(POLL_INTERVAL)


def _download_video(url: str, save_path: str):
    """
    Download a video from URL to disk.

    Args:
        url:       Video URL.
        save_path: Where to save it.
    """
    os.makedirs(os.path.dirname(save_path), exist_ok=True)

    response = requests.get(url, timeout=120, stream=True)
    if response.status_code != 200:
        raise RuntimeError(f"Video download failed (HTTP {response.status_code})")

    with open(save_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            f.write(chunk)
