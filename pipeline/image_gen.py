# =============================================================================
# pipeline/image_gen.py — Flux 2 Image Generation (Automated Path)
# =============================================================================
# PURPOSE:
#   When IMAGE_SOURCE = "flux" in config.py, this module generates the ONE
#   base image using Black Forest Labs' Flux 2 API.
#
# WHY Flux for the automated path? BFL (Black Forest Labs) makes Flux,
# the best open-weights image model. Their API gives direct access at the
# best price with no markup. For anime/Ghibli style, Midjourney is better,
# but Flux is the best fully-automated option.
#
# HOW THE BFL API WORKS (it's a 2-step process):
#   Step 1: POST your request → get back a task ID
#   Step 2: GET results using that task ID, polling until it's "Ready"
#   This is called an "async" API — you submit work and check back later.
#
# API DOCS: https://api.bfl.ml/docs
# =============================================================================

import os          # For file operations
import time        # For polling delays
import requests    # For making HTTP API calls
import logging     # For progress messages
import base64      # For encoding/decoding image data

import config      # Our settings

logger = logging.getLogger("fairway.image_gen")

# BFL API endpoints (current as of March 2026 — check docs if these change)
BFL_BASE_URL = "https://api.bfl.ml/v1"
BFL_SUBMIT_URL = f"{BFL_BASE_URL}/flux-pro-1.1"   # Submit generation request
BFL_RESULT_URL = f"{BFL_BASE_URL}/get_result"      # Poll for result

# How often to check if the image is ready (seconds)
# WHY 3 seconds? Flux typically takes 10-30 seconds. Checking every 3s gives
# us fast feedback without hammering the API unnecessarily.
POLL_INTERVAL = 3

# Maximum total time to wait for an image (seconds)
# WHY 300s (5 min)? Images usually finish in under 60s, but we're generous
# to handle server load spikes. If it takes longer, something is wrong.
MAX_WAIT_SECONDS = 300


def generate_images(
    image_prompt: str,
    run_dir: str,
    api_key: str,
) -> str:
    """
    Generate the base image using Flux 2 via the Black Forest Labs API.

    In v3, we generate ONE base image that will be the visual world of the
    entire video. The viewer will look at this image for 2-3 hours, so it
    must be excellent. We generate 3 variations (different seeds) and pick
    the best one automatically based on file size as a proxy for detail.

    Args:
        image_prompt: The full image prompt with style suffix already included.
        run_dir:      Directory to save the downloaded image.
        api_key:      BFL API key (from .env file).

    Returns:
        Path to the downloaded base image file.

    Raises:
        RuntimeError: If fewer than 1 image succeeds after all retries.
        ValueError:   If the API key is missing.
    """
    if not api_key:
        raise ValueError(
            "BFL_API_KEY is not set in your .env file.\n"
            "Get your key at: https://api.bfl.ml/\n"
            "Or switch to Midjourney: set IMAGE_SOURCE = 'midjourney' in config.py"
        )

    logger.info("  Submitting image generation to Black Forest Labs (Flux 2)...")
    logger.debug(f"  Prompt: {image_prompt[:100]}...")

    # Generate 3 variations from the same prompt using different seeds.
    # WHY 3? Without a human to pick the best image (like in Midjourney),
    # we generate a few and auto-select. More variations = better chance
    # of getting an excellent result. 3 is a good balance of quality vs cost.
    num_variations = 3
    successful_images = []

    for i in range(num_variations):
        logger.info(f"  Generating variation {i+1}/{num_variations}...")
        try:
            image_path = _generate_single_image(
                prompt=image_prompt,
                run_dir=run_dir,
                api_key=api_key,
                filename=f"base_image_v{i+1}.jpg",
            )
            successful_images.append(image_path)
            logger.info(f"  ✓ Variation {i+1} complete: {image_path}")
        except Exception as e:
            logger.warning(f"  ⚠️ Variation {i+1} failed: {e}")

    if not successful_images:
        raise RuntimeError(
            "All Flux image generation attempts failed.\n"
            "Check your BFL_API_KEY and try again.\n"
            "Or switch to Midjourney: set IMAGE_SOURCE = 'midjourney' in config.py"
        )

    # Auto-select the best image by file size as a proxy for detail/quality.
    # WHY file size? A more detailed, higher-quality JPEG tends to be larger
    # because there's more visual information to compress. This is a simple
    # heuristic that works reasonably well.
    if len(successful_images) > 1:
        best_image = max(successful_images, key=lambda p: os.path.getsize(p))
        logger.info(f"  Auto-selected best variation: {os.path.basename(best_image)}")
    else:
        best_image = successful_images[0]

    return best_image


def _generate_single_image(
    prompt: str,
    run_dir: str,
    api_key: str,
    filename: str,
) -> str:
    """
    Submit one image generation request to BFL and download the result.

    The BFL API uses a submit-and-poll pattern:
      1. POST the request → get a task ID
      2. GET the result URL repeatedly until status is "Ready"
      3. Download the image from the result URL

    Args:
        prompt:    Full image prompt with style suffix.
        run_dir:   Directory to save the image.
        api_key:   BFL API key.
        filename:  What to name the downloaded file.

    Returns:
        Path to the downloaded image file.

    Raises:
        RuntimeError: If submission fails, polling times out, or download fails.
    """
    # Step 1: Submit the generation request
    # The X-Key header is how BFL authenticates requests (not a Bearer token)
    logger.debug(f"  Submitting to {BFL_SUBMIT_URL}...")

    submit_response = requests.post(
        BFL_SUBMIT_URL,
        headers={
            "X-Key": api_key,
            "Content-Type": "application/json",
        },
        json={
            "prompt": prompt,
            "width": config.VIDEO_WIDTH,    # 1920 — native YouTube 1080p width
            "height": config.VIDEO_HEIGHT,  # 1080 — native YouTube 1080p height
            # Don't set seed — letting it be random gives variety across runs
        },
        timeout=30,  # Give up if the server doesn't respond in 30 seconds
    )

    # Check if the submission succeeded
    if submit_response.status_code != 200:
        raise RuntimeError(
            f"BFL API submission failed with status {submit_response.status_code}.\n"
            f"Response: {submit_response.text[:300]}\n"
            f"Check your BFL_API_KEY and the BFL API docs at https://api.bfl.ml/docs"
        )

    submit_data = submit_response.json()
    task_id = submit_data.get("id")

    if not task_id:
        raise RuntimeError(
            f"BFL API didn't return a task ID. Response: {submit_data}"
        )

    logger.debug(f"  Task submitted. ID: {task_id}")

    # Step 2: Poll for completion
    # We keep checking the result endpoint until the status changes to "Ready"
    image_url = _poll_for_completion(task_id=task_id, api_key=api_key)

    # Step 3: Download the image
    image_path = _download_image(url=image_url, save_path=os.path.join(run_dir, filename))

    return image_path


def _poll_for_completion(task_id: str, api_key: str) -> str:
    """
    Poll the BFL API until the image generation is complete.

    BFL images take 10-60 seconds to generate. We check every POLL_INTERVAL
    seconds until it's ready. This is called "polling" — just repeatedly
    asking "is it done yet?"

    Args:
        task_id: The task ID returned by the submission step.
        api_key: BFL API key.

    Returns:
        URL of the generated image (ready to download).

    Raises:
        RuntimeError: If it times out or if the generation fails.
    """
    start_time = time.time()
    attempts = 0

    while True:
        # Check if we've been waiting too long
        elapsed = time.time() - start_time
        if elapsed > MAX_WAIT_SECONDS:
            raise RuntimeError(
                f"BFL image generation timed out after {MAX_WAIT_SECONDS}s (task: {task_id}).\n"
                "The BFL API may be overloaded. Try again in a few minutes."
            )

        attempts += 1
        # Show a progress dot every 5 polls so the user knows it's still working
        if attempts % 5 == 1:
            logger.debug(f"  Polling for result... ({elapsed:.0f}s elapsed)")

        # GET the result for this task ID
        result_response = requests.get(
            BFL_RESULT_URL,
            params={"id": task_id},
            headers={"X-Key": api_key},
            timeout=15,
        )

        if result_response.status_code != 200:
            logger.warning(f"  ⚠️ Poll returned status {result_response.status_code}, retrying...")
            time.sleep(POLL_INTERVAL)
            continue

        result_data = result_response.json()
        status = result_data.get("status")

        if status == "Ready":
            # The image is generated and ready to download
            image_url = result_data.get("result", {}).get("sample")
            if not image_url:
                raise RuntimeError(
                    f"BFL API says Ready but no image URL found. Response: {result_data}"
                )
            logger.debug(f"  Image ready after {elapsed:.0f}s")
            return image_url

        elif status in ("Error", "Failed", "Content Moderated"):
            # Something went wrong on BFL's side
            raise RuntimeError(
                f"BFL image generation failed with status '{status}'.\n"
                f"Response: {result_data}\n"
                "Try adjusting your prompt or running again."
            )

        # Status is still "Pending" or "Processing" — wait and try again
        time.sleep(POLL_INTERVAL)


def _download_image(url: str, save_path: str) -> str:
    """
    Download an image from a URL and save it to disk.

    Args:
        url:       The image URL to download from.
        save_path: Full path where the file should be saved.

    Returns:
        The save_path (so callers can chain this easily).

    Raises:
        RuntimeError: If the download fails.
    """
    logger.debug(f"  Downloading image from: {url[:60]}...")

    response = requests.get(url, timeout=60, stream=True)

    if response.status_code != 200:
        raise RuntimeError(
            f"Failed to download image (HTTP {response.status_code}).\n"
            f"URL: {url}"
        )

    # Create the directory if it doesn't exist
    os.makedirs(os.path.dirname(save_path), exist_ok=True)

    # Write the image data to disk in chunks to handle large files efficiently
    # WHY chunks? If we load the whole image into memory first, it uses more RAM.
    # Streaming (chunks) writes directly to disk without loading everything at once.
    with open(save_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

    file_size_kb = os.path.getsize(save_path) / 1024
    logger.debug(f"  Saved {file_size_kb:.0f}KB to {save_path}")

    return save_path
