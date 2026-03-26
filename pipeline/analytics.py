# =============================================================================
# pipeline/analytics.py — YouTube Analytics Report
# =============================================================================
# PURPOSE:
#   Pull channel-level and per-video metrics from the YouTube Analytics API
#   and return a clean summary dict for display in the control panel UI.
#
# REQUIRES:
#   - YouTube OAuth credentials (same as youtube_upload.py)
#   - Scopes: youtube.readonly + yt-analytics.readonly
#   - pip install google-api-python-client google-auth-oauthlib
#
# VIDEO TRACKER:
#   Uploaded video IDs are saved to output/video_tracker.json by youtube_upload.py.
#   We read that file to pull per-video stats. If it doesn't exist yet, we fall
#   back to channel-level lifetime totals only.
# =============================================================================

import os
import json
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("fairway.analytics")

try:
    from googleapiclient.discovery import build
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    GOOGLE_LIBS_AVAILABLE = True
except ImportError:
    GOOGLE_LIBS_AVAILABLE = False

# OAuth scopes — read-only, so no write permissions are granted
ANALYTICS_SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]

TOKEN_FILE = ".youtube_analytics_token.json"
VIDEO_TRACKER_FILE = "output/video_tracker.json"


def fetch_analytics(client_id: str, client_secret: str) -> dict:
    """
    Pull a high-level YouTube analytics report for the channel.

    Returns a dict with:
        channel: { views, watch_hours, subscribers, videos_uploaded }
        videos:  [ { id, title, views, watch_hours, avg_view_pct, likes, url } ]
        period:  "Last 28 days"
        fetched_at: ISO timestamp

    Raises RuntimeError if credentials are missing or API calls fail.
    """
    if not GOOGLE_LIBS_AVAILABLE:
        raise RuntimeError(
            "YouTube API libraries not installed.\n"
            "Run: pip install google-api-python-client google-auth-oauthlib"
        )

    if not client_id or not client_secret:
        raise RuntimeError(
            "YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET must be set in .env"
        )

    youtube, yt_analytics = _get_clients(client_id, client_secret)

    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=28)
    start_str = start_date.isoformat()
    end_str = end_date.isoformat()

    # ── Channel-level totals (last 28 days) ──────────────────────────────────
    channel_stats = _fetch_channel_stats(yt_analytics, start_str, end_str)

    # ── Per-video stats for our uploaded videos ───────────────────────────────
    tracked_videos = _load_tracked_videos()
    video_stats = []

    for entry in tracked_videos:
        vid_id = entry.get("video_id")
        if not vid_id:
            continue
        try:
            stats = _fetch_video_stats(yt_analytics, youtube, vid_id, start_str, end_str)
            video_stats.append(stats)
        except Exception as e:
            logger.warning(f"  Could not fetch stats for {vid_id}: {e}")

    # Sort videos by views descending
    video_stats.sort(key=lambda v: v.get("views", 0), reverse=True)

    return {
        "channel": channel_stats,
        "videos": video_stats,
        "period": "Last 28 days",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def _fetch_channel_stats(yt_analytics, start_str: str, end_str: str) -> dict:
    """Pull aggregate channel metrics for the date range."""
    response = yt_analytics.reports().query(
        ids="channel==MINE",
        startDate=start_str,
        endDate=end_str,
        metrics="views,estimatedMinutesWatched,subscribersGained,subscribersLost",
        dimensions="",
    ).execute()

    row = response.get("rows", [[0, 0, 0, 0]])[0]
    views = int(row[0])
    minutes_watched = int(row[1])
    subs_gained = int(row[2])
    subs_lost = int(row[3])

    return {
        "views": views,
        "watch_hours": round(minutes_watched / 60, 1),
        "subscribers_gained": subs_gained,
        "subscribers_lost": subs_lost,
        "net_subscribers": subs_gained - subs_lost,
    }


def _fetch_video_stats(yt_analytics, youtube, video_id: str,
                       start_str: str, end_str: str) -> dict:
    """Pull per-video metrics and basic metadata."""
    # Analytics metrics for this specific video
    response = yt_analytics.reports().query(
        ids="channel==MINE",
        startDate=start_str,
        endDate=end_str,
        metrics="views,estimatedMinutesWatched,averageViewPercentage,likes",
        filters=f"video=={video_id}",
        dimensions="",
    ).execute()

    row = response.get("rows", [[0, 0, 0.0, 0]])[0]
    views = int(row[0])
    minutes_watched = int(row[1])
    avg_view_pct = round(float(row[2]), 1)
    likes = int(row[3])

    # Basic metadata from Data API (title, published date)
    title = video_id  # fallback
    published_at = ""
    try:
        meta_response = youtube.videos().list(
            part="snippet",
            id=video_id,
        ).execute()
        items = meta_response.get("items", [])
        if items:
            title = items[0]["snippet"]["title"]
            published_at = items[0]["snippet"].get("publishedAt", "")[:10]
    except Exception:
        pass

    return {
        "video_id": video_id,
        "title": title,
        "published": published_at,
        "views": views,
        "watch_hours": round(minutes_watched / 60, 1),
        "avg_view_pct": avg_view_pct,
        "likes": likes,
        "url": f"https://youtu.be/{video_id}",
    }


def _load_tracked_videos() -> list:
    """Load the list of uploaded video IDs from output/video_tracker.json."""
    if not os.path.exists(VIDEO_TRACKER_FILE):
        return []
    try:
        with open(VIDEO_TRACKER_FILE, "r") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _get_clients(client_id: str, client_secret: str):
    """
    Build authenticated YouTube Data API + Analytics API clients.

    Uses a separate token file from the upload flow so analytics can work
    independently (e.g. even before any video has been uploaded this session).
    """
    credentials = None

    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "r") as f:
                token_data = json.load(f)
            credentials = Credentials.from_authorized_user_info(token_data, ANALYTICS_SCOPES)
        except Exception:
            credentials = None

    if not credentials or not credentials.valid:
        client_config = {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        }
        flow = InstalledAppFlow.from_client_config(client_config, ANALYTICS_SCOPES)
        logger.info("  Opening browser for YouTube Analytics authentication...")
        credentials = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w") as f:
            json.dump(json.loads(credentials.to_json()), f)

    youtube = build("youtube", "v3", credentials=credentials)
    yt_analytics = build("youtubeAnalytics", "v2", credentials=credentials)

    return youtube, yt_analytics
