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
    from google.auth.transport.requests import Request
    GOOGLE_LIBS_AVAILABLE = True
except ImportError:
    GOOGLE_LIBS_AVAILABLE = False

# OAuth scopes required for YouTube upload
YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube"]

# Where to store the OAuth token after first login
TOKEN_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".youtube_token.json")


def next_optimal_publish_time(
    tracker_file: str = "output/video_tracker.json",
    scene_stem_prefix: str = None,
) -> datetime:
    """
    Calculate the next optimal YouTube publish time, skipping already-booked slots.

    Target: Sunday at 9am EST.
    Sunday morning is peak time for lofi/study music listeners — they front-load
    focus sessions (journaling, study prep) before the week starts. A 9am upload
    indexes by the time the audience settles in, then accumulates watch time
    passively throughout the day as background music.

    Checks the video tracker to avoid scheduling two videos on the same Sunday.
    When scene_stem_prefix is provided (e.g. the shared stem for jazz/hiphop AB
    variants), also blocks any Sunday within 14 days of another video with that
    same scene — keeping AB variants at least two weeks apart.

    Returns:
        A timezone-aware datetime for the next available Sunday at 9am EST.
    """
    est = timezone(timedelta(hours=-5))  # EST (UTC-5)
    now = datetime.now(est)
    target_hour = 9   # 9am EST

    booked_dates = set()
    scene_blocked_dates = set()

    if os.path.exists(tracker_file):
        try:
            with open(tracker_file, "r") as f:
                tracker = json.load(f)
            for entry in tracker:
                pa = entry.get("publish_at")
                if not pa:
                    continue
                dt = datetime.strptime(pa[:19], "%Y-%m-%dT%H:%M:%S")
                if dt > now.replace(tzinfo=None):
                    booked_dates.add(dt.date())

                # Block Sundays within ±14 days of any same-scene variant
                if scene_stem_prefix:
                    stem = entry.get("video_stem", "")
                    if stem and stem.startswith(scene_stem_prefix):
                        anchor = dt.date()
                        for offset in range(-14, 15):
                            blocked = anchor + timedelta(days=offset)
                            scene_blocked_dates.add(blocked)
        except Exception:
            pass  # Tracker unreadable — proceed without it

    for days_ahead in range(90):  # Look up to ~3 months ahead
        candidate = now + timedelta(days=days_ahead)
        if candidate.weekday() == 6:  # Sunday
            publish_dt = candidate.replace(
                hour=target_hour, minute=0, second=0, microsecond=0
            )
            d = publish_dt.date()
            if publish_dt > now and d not in booked_dates and d not in scene_blocked_dates:
                return publish_dt

    # Fallback: 7 days from now at 9am (should never hit this)
    return (now + timedelta(days=7)).replace(
        hour=target_hour, minute=0, second=0, microsecond=0
    )


def get_youtube_client(client_id: str, client_secret: str):
    """Public wrapper so other modules (e.g. shorts_scheduler) can reuse auth."""
    return _get_youtube_client(client_id, client_secret)


def upload_to_youtube(
    video_path: str,
    thumbnail_path: str,
    metadata: dict,
    client_id: str,
    client_secret: str,
    logger: logging.Logger = None,
    video_stem: str = None,
    scene_stem_prefix: str = None,
    genre: str = None,
    scene_prompt: str = None,
    playlists: dict = None,
) -> str:
    """
    Upload the video to YouTube as a private scheduled video.

    On first run, this will open a browser window for OAuth authentication.
    After that, the token is saved locally and reused automatically.

    Args:
        video_path:     Path to the final MP4 video.
        thumbnail_path: Path to the thumbnail image.
        metadata:       Dict with title, description, tags.
        client_id:      YouTube OAuth client ID.
        client_secret:  YouTube OAuth client secret.
        logger:         Logger for progress messages.
        video_stem:     Filename stem for tracker linkage.
        scene_stem_prefix: Shared prefix across AB variants (blocks same-scene doubles).
        genre:          "Jazz" or "HipHop" — used to pick the genre playlist.
        scene_prompt:   Original scene description — used to pick morning/evening playlist.
        playlists:      Dict with optional keys: jazz, hiphop, morning, evening (playlist IDs).

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
    publish_at = next_optimal_publish_time(scene_stem_prefix=scene_stem_prefix)
    publish_at_str = publish_at.strftime("%Y-%m-%dT%H:%M:%S%z")
    publish_day = publish_at.strftime("%A %B {day} at %I:%M%p EST").format(day=publish_at.day)

    # Prepare the video metadata for the YouTube API
    # YouTube uses numeric category IDs — 10 = Music
    body = {
        "snippet": {
            "title": metadata.get("title", "Fairway Frequencies — LoFi Golf")[:100],
            "description": metadata.get("description", "")[:5000],
            "tags": _sanitize_tags(metadata.get("tags", [])),
            "categoryId": metadata.get("category", "10"),
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus": "private",       # Private until publish time
            "publishAt": publish_at_str,       # YouTube auto-publishes at this time
            "selfDeclaredMadeForKids": False,  # Not children's content
            "containsSyntheticMedia": False,   # No real people, events, or realistic-looking scenes
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

    # Add to playlists
    if playlists:
        _assign_playlists(youtube, video_id, genre, scene_prompt, playlists, local_logger)

    # Track the video ID for the analytics dashboard
    _save_video_to_tracker(video_id, metadata.get("title", ""), publish_at_str, video_stem)

    return video_url


def _sanitize_tags(tags: list) -> list:
    """Enforce YouTube's 500 total-character tag limit (each tag also ≤ 30 chars)."""
    result, total = [], 0
    for tag in tags:
        tag = tag[:30]
        if total + len(tag) > 500:
            break
        result.append(tag)
        total += len(tag)
    return result


_LATE_NIGHT_KEYWORDS = {
    "night", "moonlit", "midnight", "late night", "nighttime", "stars", "starlit",
    "after dark", "dusk", "evening",
}


def _detect_time_of_day(scene_prompt: str) -> str:
    """Return 'evening' for clearly nighttime scenes, 'morning' for everything else."""
    if not scene_prompt:
        return "morning"
    lower = scene_prompt.lower()
    if any(kw in lower for kw in _LATE_NIGHT_KEYWORDS):
        return "evening"
    return "morning"


def _assign_playlists(
    youtube,
    video_id: str,
    genre: str,
    scene_prompt: str,
    playlists: dict,
    local_logger: logging.Logger,
):
    """Insert video_id into the appropriate genre and time-of-day playlists."""
    targets = []

    genre_key = (genre or "").lower()  # "jazz" or "hiphop"
    if genre_key == "hiphop":
        genre_key = "hiphop"
    playlist_id = playlists.get(genre_key)
    if playlist_id:
        targets.append((genre_key, playlist_id))

    tod = _detect_time_of_day(scene_prompt)
    if tod:
        tod_id = playlists.get(tod)
        if tod_id:
            targets.append((tod, tod_id))

    for label, pid in targets:
        try:
            youtube.playlistItems().insert(
                part="snippet",
                body={
                    "snippet": {
                        "playlistId": pid,
                        "resourceId": {"kind": "youtube#video", "videoId": video_id},
                    }
                },
            ).execute()
            local_logger.info(f"  ✓ Added to playlist: {label} ({pid})")
        except Exception as e:
            local_logger.warning(f"  ⚠️ Could not add to {label} playlist: {e}")


def list_channel_playlists(client_id: str, client_secret: str) -> list[dict]:
    """Fetch all playlists for the authenticated channel. Returns list of {id, title}."""
    youtube = _get_youtube_client(client_id, client_secret)
    results = []
    page_token = None
    while True:
        resp = youtube.playlists().list(
            part="snippet",
            mine=True,
            maxResults=50,
            pageToken=page_token,
        ).execute()
        for item in resp.get("items", []):
            results.append({"id": item["id"], "title": item["snippet"]["title"]})
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return results


def _save_video_to_tracker(video_id: str, title: str, publish_at: str, video_stem: str = None):
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
        entry = {
            "video_id": video_id,
            "title": title,
            "uploaded_at": datetime.now(timezone(timedelta(hours=-5))).isoformat(),
            "publish_at": publish_at,
        }
        if video_stem:
            entry["video_stem"] = video_stem
        existing.append(entry)
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

    # Silently refresh expired token using the saved refresh token
    if credentials and not credentials.valid and credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
            with open(TOKEN_FILE, "w") as f:
                json.dump(json.loads(credentials.to_json()), f)
            logger.debug("  YouTube token refreshed silently")
        except Exception as e:
            logger.warning(f"  Token refresh failed: {e}. Re-authenticating...")
            credentials = None

    # If still no valid credentials, do the full OAuth flow (first run only)
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
