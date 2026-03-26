# =============================================================================
# pipeline/youtube_upload.py — Optional YouTube Upload
# =============================================================================
# PURPOSE:
#   Automatically upload the finished video to your YouTube channel.
#   This is OPTIONAL — only runs when you add --upload to the command.
#   Videos are uploaded as "unlisted" by default (only people with the link
#   can see it), giving you a chance to review before making it public.
#
# WHY upload as unlisted? You probably want to:
#   1. Review the video on YouTube (to see how it looks in the player)
#   2. Check the thumbnail displays correctly
#   3. Edit the title/description in YouTube Studio if needed
#   4. THEN change visibility to "public"
#   Unlisted keeps you in control.
#
# SETUP REQUIRED:
#   YouTube upload requires OAuth 2.0 authentication (more complex than API keys).
#   See README.md Section 9 for detailed setup steps.
#   You need: Google Cloud project, YouTube Data API v3 enabled, OAuth credentials.
#
# AI CONTENT DISCLOSURE:
#   YouTube requires disclosure of AI-generated content for realistic content.
#   While our anime/illustrated style is clearly not meant to look real,
#   we disclose AI use proactively as best practice.
# =============================================================================

import os
import json
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("fairway.youtube_upload")

# Google API client libraries (optional dependencies)
# These are only imported if you actually use --upload
# WHY optional imports? If users don't set up YouTube API,
# the rest of the pipeline still works — we don't want import errors
# to break a successful video generation.
try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.oauth2.credentials import Credentials
    GOOGLE_LIBS_AVAILABLE = True
except ImportError:
    GOOGLE_LIBS_AVAILABLE = False

# OAuth scopes required for YouTube upload
YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

# Where to store the OAuth token after first login
TOKEN_FILE = ".youtube_token.json"


def next_optimal_publish_time() -> datetime:
    """
    Calculate the next optimal YouTube publish time.

    Target: Thursday or Friday between 6–9pm EST.
    Study/lofi music audiences are most active late week evenings.

    Returns:
        A timezone-aware datetime for the next Thu or Fri at 7pm EST.
    """
    est = timezone(timedelta(hours=-5))  # EST (UTC-5); accounts for standard time
    now = datetime.now(est)
    target_hour = 19  # 7pm EST

    # Weekday numbers: 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri
    target_days = [3, 4]  # Thursday, Friday

    for days_ahead in range(7):
        candidate = now + timedelta(days=days_ahead)
        if candidate.weekday() in target_days:
            publish_dt = candidate.replace(
                hour=target_hour, minute=0, second=0, microsecond=0
            )
            # If that slot is in the past today, skip to next target day
            if publish_dt > now:
                return publish_dt

    # Fallback: 7 days from now at 7pm (should never hit this)
    return (now + timedelta(days=7)).replace(
        hour=target_hour, minute=0, second=0, microsecond=0
    )


def upload_to_youtube(
    video_path: str,
    thumbnail_path: str,
    metadata: dict,
    client_id: str,
    client_secret: str,
    logger: logging.Logger = None,
) -> str:
    """
    Upload the video to YouTube as an unlisted video.

    On first run, this will open a browser window for OAuth authentication.
    After that, the token is saved locally and reused automatically.

    Args:
        video_path:     Path to the final MP4 video.
        thumbnail_path: Path to the thumbnail image.
        metadata:       Dict with title, description, tags.
        client_id:      YouTube OAuth client ID.
        client_secret:  YouTube OAuth client secret.
        logger:         Logger for progress messages.

    Returns:
        YouTube video URL (https://youtu.be/{video_id})

    Raises:
        RuntimeError: If credentials are missing or upload fails.
    """
    local_logger = logger or logging.getLogger("fairway.youtube_upload")

    if not GOOGLE_LIBS_AVAILABLE:
        raise RuntimeError(
            "YouTube upload libraries not installed.\n"
            "Install them with: pip install google-api-python-client google-auth-oauthlib\n"
            "Or skip upload: remove the --upload flag."
        )

    if not client_id or not client_secret:
        raise RuntimeError(
            "YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET must be set in .env.\n"
            "See README.md Section 9 for YouTube API setup instructions.\n"
            "Or skip upload: remove the --upload flag."
        )

    # Authenticate with YouTube
    local_logger.info("  Authenticating with YouTube...")
    youtube = _get_youtube_client(client_id, client_secret)

    # Calculate the optimal publish time (next Thu or Fri at 7pm EST)
    publish_at = next_optimal_publish_time()
    publish_at_str = publish_at.strftime("%Y-%m-%dT%H:%M:%S%z")
    publish_day = publish_at.strftime("%A %B %-d at %-I:%M%p EST")

    # Prepare the video metadata for the YouTube API
    # YouTube uses numeric category IDs — 10 = Music
    body = {
        "snippet": {
            "title": metadata.get("title", "Fairway Frequencies — LoFi Golf")[:100],
            "description": metadata.get("description", "")[:5000],
            "tags": metadata.get("tags", [])[:500],  # YouTube tag limit
            "categoryId": metadata.get("category", "10"),
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus": "private",      # Private until publish time
            "publishAt": publish_at_str,      # YouTube auto-publishes at this time
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True,
        },
    }

    local_logger.info(f"  Uploading: {metadata.get('title', 'Fairway Frequencies Video')}")
    local_logger.info(f"  Scheduled to publish: {publish_day}")
    local_logger.info(f"  File size: {os.path.getsize(video_path) / (1024**3):.2f}GB")
    local_logger.info("  This may take several minutes for a 2-3 hour video...")

    # Create the upload request
    # MediaFileUpload with chunksize=-1 uploads the whole file at once
    # For very large files, you could set chunksize for resumable uploads
    media = MediaFileUpload(
        video_path,
        mimetype="video/mp4",
        resumable=True,          # Resumable upload handles network interruptions
        chunksize=1024 * 1024 * 50,  # 50MB chunks
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    # Execute the upload with progress tracking
    video_id = None
    response = None

    while response is None:
        status, response = request.next_chunk()
        if status:
            progress = int(status.progress() * 100)
            local_logger.info(f"  Upload progress: {progress}%")

    video_id = response.get("id")

    if not video_id:
        raise RuntimeError(f"Upload completed but no video ID returned: {response}")

    # Set the thumbnail
    if thumbnail_path and os.path.exists(thumbnail_path):
        try:
            local_logger.info("  Setting thumbnail...")
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_path, mimetype="image/png")
            ).execute()
            local_logger.info("  ✓ Thumbnail set")
        except Exception as e:
            local_logger.warning(f"  ⚠️ Thumbnail upload failed: {e}")
            local_logger.info("  (You can set the thumbnail manually in YouTube Studio)")

    video_url = f"https://youtu.be/{video_id}"
    local_logger.info(f"\n  ✓ Video uploaded and scheduled: {video_url}")
    local_logger.info(f"  Publishes automatically: {publish_day}")
    local_logger.info("  To change schedule: YouTube Studio → Videos → click the video → Visibility")

    # Track the video ID for the analytics dashboard
    _save_video_to_tracker(video_id, metadata.get("title", ""), publish_at_str)

    return video_url


def _save_video_to_tracker(video_id: str, title: str, publish_at: str):
    """Append this video to output/video_tracker.json for the analytics dashboard."""
    tracker_file = "output/video_tracker.json"
    os.makedirs("output", exist_ok=True)

    existing = []
    if os.path.exists(tracker_file):
        try:
            with open(tracker_file, "r") as f:
                existing = json.load(f)
        except Exception:
            existing = []

    # Avoid duplicates
    if not any(v.get("video_id") == video_id for v in existing):
        existing.append({
            "video_id": video_id,
            "title": title,
            "uploaded_at": datetime.now(timezone(timedelta(hours=-5))).isoformat(),
            "publish_at": publish_at,
        })
        with open(tracker_file, "w") as f:
            json.dump(existing, f, indent=2)


def _get_youtube_client(client_id: str, client_secret: str):
    """
    Get an authenticated YouTube API client.

    Uses saved credentials if available (from a previous login).
    Otherwise, opens a browser for OAuth authentication.

    WHY OAuth instead of API key? YouTube uploads REQUIRE OAuth because
    you're acting on behalf of a user account (your channel). Simple API keys
    are only for read-only public data.

    Args:
        client_id:     OAuth client ID from Google Cloud Console.
        client_secret: OAuth client secret.

    Returns:
        Authenticated YouTube API client object.
    """
    credentials = None

    # Try to load saved credentials from a previous login
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "r") as f:
                token_data = json.load(f)
            credentials = Credentials.from_authorized_user_info(token_data, YOUTUBE_SCOPES)
            logger.debug("  Loaded saved YouTube credentials")
        except Exception as e:
            logger.warning(f"  Saved YouTube credentials invalid: {e}. Re-authenticating...")
            credentials = None

    # If no valid credentials, do the OAuth flow
    if not credentials or not credentials.valid:
        # Build a temporary client secrets dict
        client_config = {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        }

        flow = InstalledAppFlow.from_client_config(client_config, YOUTUBE_SCOPES)

        # This opens a browser window for the user to log in
        # On first run, you'll see: "Fairway Frequencies wants to access your YouTube account"
        logger.info("  Opening browser for YouTube authentication...")
        logger.info("  (This only happens once — credentials are saved after)")
        credentials = flow.run_local_server(port=0)

        # Save credentials for next time
        with open(TOKEN_FILE, "w") as f:
            json.dump(json.loads(credentials.to_json()), f)
        logger.debug("  YouTube credentials saved for future runs")

    # Build the YouTube API client with the credentials
    return build("youtube", "v3", credentials=credentials)
