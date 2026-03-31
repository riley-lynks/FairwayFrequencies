# =============================================================================
# upload.py — Standalone YouTube Upload
# =============================================================================
# Uploads any un-uploaded videos sitting in the output/ folder.
# Run this directly: python upload.py
#
# On first run, a browser will open to authenticate with your YouTube account.
# After that, credentials are saved to .youtube_token.json and reused.
# =============================================================================

import os
import sys
import json
import logging
import glob

from dotenv import load_dotenv

# Add the project root to path so we can import pipeline modules
sys.path.insert(0, os.path.dirname(__file__))
from pipeline.youtube_upload import upload_to_youtube

# Load .env for API keys
load_dotenv()

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("upload")


def find_pending_videos(output_dir: str = "output") -> list[dict]:
    """
    Find all videos in output/ that have a matching metadata + thumbnail
    and haven't been uploaded yet (not in video_tracker.json).
    """
    # Load already-uploaded video IDs from the tracker
    tracker_file = os.path.join(output_dir, "video_tracker.json")
    uploaded_titles = set()
    if os.path.exists(tracker_file):
        try:
            with open(tracker_file, encoding="utf-8") as f:
                tracker = json.load(f)
            uploaded_titles = {v.get("title", "") for v in tracker}
        except Exception:
            pass

    # Find all .mp4 files in output/ (not subdirectories)
    pending = []
    for mp4_path in glob.glob(os.path.join(output_dir, "*.mp4")):
        base = mp4_path[:-4]  # strip .mp4
        metadata_path = base + "_metadata.json"
        thumbnail_path = base + "_thumbnail.png"

        if not os.path.exists(metadata_path):
            logger.warning(f"  Skipping {os.path.basename(mp4_path)} — no metadata file found")
            continue

        with open(metadata_path, encoding="utf-8") as f:
            metadata = json.load(f)

        title = metadata.get("title", "")
        if title in uploaded_titles:
            logger.info(f"  Already uploaded: {title}")
            continue

        pending.append({
            "video_path": mp4_path,
            "thumbnail_path": thumbnail_path if os.path.exists(thumbnail_path) else None,
            "metadata": metadata,
        })

    return pending


def main():
    client_id     = os.getenv("YOUTUBE_CLIENT_ID")
    client_secret = os.getenv("YOUTUBE_CLIENT_SECRET")

    if not client_id or not client_secret:
        logger.error("YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET must be set in .env")
        sys.exit(1)

    logger.info("━" * 60)
    logger.info("  Fairway Frequencies — YouTube Upload")
    logger.info("━" * 60)

    pending = find_pending_videos()

    if not pending:
        logger.info("  Nothing to upload — all videos already uploaded!")
        return

    logger.info(f"  Found {len(pending)} video(s) to upload:\n")
    for i, v in enumerate(pending, 1):
        size_gb = os.path.getsize(v["video_path"]) / (1024 ** 3)
        logger.info(f"  {i}. {v['metadata'].get('title', 'Unknown')}")
        logger.info(f"     File: {os.path.basename(v['video_path'])} ({size_gb:.2f}GB)")
        logger.info(f"     Thumbnail: {'✓' if v['thumbnail_path'] else '✗ missing'}\n")

    logger.info("━" * 60)

    for v in pending:
        try:
            url = upload_to_youtube(
                video_path=v["video_path"],
                thumbnail_path=v["thumbnail_path"],
                metadata=v["metadata"],
                client_id=client_id,
                client_secret=client_secret,
                logger=logger,
            )
            logger.info(f"\n  ✓ Done: {url}\n")
        except Exception as e:
            logger.error(f"\n  ✗ Upload failed: {e}\n")

    logger.info("━" * 60)
    logger.info("  Upload complete!")
    logger.info("━" * 60)


if __name__ == "__main__":
    main()
