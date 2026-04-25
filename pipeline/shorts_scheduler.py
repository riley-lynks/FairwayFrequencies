# =============================================================================
# pipeline/shorts_scheduler.py — YouTube Shorts Scheduler
# =============================================================================
# Tracks every generated Short across all pipeline runs and automatically
# schedules them to YouTube following the weekly posting pattern:
#
#   Sun  — Long-form video publishes
#   Mon  — Standalone short from the video that just released (9am EST)
#   Tue  — Standalone short from the video that just released (9am EST)
#   Wed  — Teaser short for NEXT Sunday's video: "Dropping Sunday" (9am EST)
#   Thu  — Archive short from an older video (9am EST)
#   Fri  — Archive short from an older video (9am EST)
#   Sat  — Teaser short for NEXT Sunday's video: "Dropping tomorrow" (9am EST)
#
# USAGE:
#   python fairway.py --schedule-shorts           # Schedule next 4 weeks
#   python fairway.py --schedule-shorts --weeks 6 # Schedule next 6 weeks
#   python fairway.py --schedule-shorts --dry-run # Preview without uploading
#
# HOW IT WORKS:
#   1. seed_tracker()      — Scans output/archive/ for all shorts, registers
#                            any not yet in output/shorts_tracker.json
#   2. schedule_weeks()    — Assigns shorts to daily slots across N weeks,
#                            uploading each to YouTube with a scheduled publishAt
#   3. Status lifecycle:   unused → scheduled → posted
# =============================================================================

import json
import logging
import os
import random
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path

logger = logging.getLogger("fairway.shorts_scheduler")

TRACKER_PATH = "output/shorts_tracker.json"
VIDEO_TRACKER_PATH = "output/video_tracker.json"
ARCHIVE_DIR = "output/archive"

POST_HOUR_EST = 9   # 9am EST for all short posts
EST = timezone(timedelta(hours=-5))

TOKEN_FILE = ".youtube_token.json"
YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube"]

try:
    from googleapiclient.discovery import build as _yt_build
    from googleapiclient.http import MediaFileUpload
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.oauth2.credentials import Credentials
    GOOGLE_LIBS_AVAILABLE = True
except ImportError:
    GOOGLE_LIBS_AVAILABLE = False


# =============================================================================
# TITLE / DESCRIPTION TEMPLATES
# =============================================================================

# Standalone shorts: use the hook templates from shorts_gen.py
STANDALONE_HOOKS = {
    "warm_grade": [
        "This golf course hits different",
        "POV: You found the perfect study spot ⛳",
        "When the vibes are just right",
        "Put this on and let the world fade away",
        "The view from the fairway",
    ],
    "ken_burns": [
        "Take a walk through this painted golf course",
        "The most peaceful place on earth",
        "Somewhere between a painting and a dream",
        "Let your eyes wander across the fairway",
        "Every frame is a painting",
    ],
    "bloom_fade": [
        "POV: Golden hour on the fairway",
        "This is what peace looks like",
        "The light on this golf course is unreal",
        "Save this for when you need to breathe",
        "When the light hits the green just right",
    ],
    "cool_mist": [
        "Studio Ghibli golf course, anyone?",
        "If golf courses were anime backgrounds",
        "Can you hear the birds?",
        "The peaceful side of golf",
        "This golf course feels like a dream",
    ],
    "golfquilizer": [
        "Watch the music come alive on the fairway",
        "When the lofi beats match the vibes",
        "The golf ball is feeling this track",
        "POV: The fairway has its own heartbeat",
        "Feel the rhythm of the course",
    ],
}

STANDALONE_DESCRIPTION = (
    "Relaxing LoFi golf beats to study, work, or unwind.\n"
    "New holes every week on Fairway Frequencies.\n\n"
    "#lofi #golf #shorts #studymusic #lofimusic #golfvibes #chillbeats #lofibeats"
)

TEASER_SUNDAY_TITLE = "New LoFi Golf Hole Dropping This Sunday 🎵 | Fairway Frequencies #shorts"
TEASER_SUNDAY_DESCRIPTION = (
    "New hole dropping this Sunday 🎵\n\n"
    "Follow Fairway Frequencies so you don't miss it ↓\n\n"
    "#lofi #golf #shorts #comingsoon #lofimusic #golfvibes #chillbeats"
)

TEASER_TOMORROW_TITLE = "New LoFi Golf Hole Dropping Tomorrow 🎵 | Fairway Frequencies #shorts"
TEASER_TOMORROW_DESCRIPTION = (
    "New hole dropping tomorrow 🎵\n\n"
    "Follow Fairway Frequencies so you don't miss it ↓\n\n"
    "#lofi #golf #shorts #comingsoon #lofimusic #golfvibes #chillbeats"
)


# =============================================================================
# TRACKER I/O
# =============================================================================

def _load_tracker() -> dict:
    if os.path.exists(TRACKER_PATH):
        try:
            with open(TRACKER_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"shorts": []}


def _save_tracker(data: dict):
    os.makedirs("output", exist_ok=True)
    with open(TRACKER_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _load_video_tracker() -> list:
    if os.path.exists(VIDEO_TRACKER_PATH):
        try:
            with open(VIDEO_TRACKER_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


# =============================================================================
# ARCHIVE SCANNING
# =============================================================================

def _read_video_title(video_folder: str) -> str:
    """Read the scene title from the archive metadata.json for a video folder."""
    folder_path = os.path.join(ARCHIVE_DIR, video_folder)
    if not os.path.isdir(folder_path):
        return "Fairway Frequencies"
    for fname in os.listdir(folder_path):
        if fname.endswith("_metadata.json"):
            try:
                with open(os.path.join(folder_path, fname), "r", encoding="utf-8") as f:
                    meta = json.load(f)
                return meta.get("title", "Fairway Frequencies")
            except Exception:
                pass
    return "Fairway Frequencies"


def seed_tracker() -> int:
    """
    Scan output/archive/ for all shorts and register any not yet tracked.
    Handles two archive layouts:
      Standard:    Video_X/shorts/<stem>/short_N_*.mp4
      Legacy:      Video_X/<stem>/short_N_*.mp4  (no shorts/ subdirectory)
    Returns the count of newly added shorts.
    """
    tracker = _load_tracker()
    existing_paths = {s["file_path"] for s in tracker["shorts"]}
    new_shorts = []

    # Scan both the archive and the main output dir (for recently generated, not-yet-archived videos)
    scan_roots = []
    if os.path.isdir(ARCHIVE_DIR):
        for folder in sorted(os.listdir(ARCHIVE_DIR)):
            scan_roots.append((ARCHIVE_DIR, folder))
    output_dir = "output"
    if os.path.isdir(output_dir):
        for folder in sorted(os.listdir(output_dir)):
            if folder.startswith("Video_") and os.path.isdir(os.path.join(output_dir, folder)):
                scan_roots.append((output_dir, folder))

    if not scan_roots:
        logger.warning("No video folders found to scan.")
        return 0

    for base_dir, video_folder in scan_roots:
        folder_path = os.path.join(base_dir, video_folder)
        if not os.path.isdir(folder_path):
            continue

        # Collect (stem_folder, stem_path) pairs from both layouts
        stem_dirs = []

        # Layout 1: Video_X/shorts/<stem>/
        shorts_subdir = os.path.join(folder_path, "shorts")
        if os.path.isdir(shorts_subdir):
            for stem_folder in sorted(os.listdir(shorts_subdir)):
                stem_path = os.path.join(shorts_subdir, stem_folder)
                if os.path.isdir(stem_path):
                    stem_dirs.append((stem_folder, stem_path, "shorts"))

        # Layout 2: Video_X/<stem>/ where stem starts with "fairway_"
        for stem_folder in sorted(os.listdir(folder_path)):
            if not stem_folder.startswith("fairway_"):
                continue
            stem_path = os.path.join(folder_path, stem_folder)
            if not os.path.isdir(stem_path):
                continue
            if any(f.startswith("short_") and f.endswith(".mp4") for f in os.listdir(stem_path)):
                stem_dirs.append((stem_folder, stem_path, "direct"))

        for stem_folder, stem_path, layout in stem_dirs:
            lower = stem_folder.lower()
            if lower.endswith("_jazz"):
                genre = "jazz"
            elif lower.endswith("_hiphop"):
                genre = "hiphop"
            else:
                genre = "single"

            for mp4_file in sorted(os.listdir(stem_path)):
                if not mp4_file.startswith("short_") or not mp4_file.endswith(".mp4"):
                    continue

                if layout == "shorts":
                    file_path = "/".join([base_dir, video_folder, "shorts", stem_folder, mp4_file])
                else:
                    file_path = "/".join([base_dir, video_folder, stem_folder, mp4_file])

                if file_path in existing_paths:
                    continue

                name_parts = mp4_file.replace(".mp4", "").split("_", 2)
                effect_num = int(name_parts[1]) if len(name_parts) > 1 and name_parts[1].isdigit() else 0
                effect = name_parts[2] if len(name_parts) > 2 else "unknown"

                short_id = f"{video_folder}__{stem_folder}__{mp4_file.replace('.mp4', '')}"

                new_shorts.append({
                    "id": short_id,
                    "video_folder": video_folder,
                    "video_stem": stem_folder,
                    "genre": genre,
                    "effect": effect,
                    "effect_num": effect_num,
                    "file_path": file_path,
                    "status": "unused",
                    "short_type": None,
                    "scheduled_for": None,
                    "youtube_short_id": None,
                    "linked_video_id": None,
                    "linked_video_publish_at": None,
                })
                existing_paths.add(file_path)

    if new_shorts:
        tracker["shorts"].extend(new_shorts)
        _save_tracker(tracker)
        logger.info(f"  Seeded {len(new_shorts)} new shorts into tracker")
    else:
        logger.info("  Tracker up to date — no new shorts found in archive")

    _link_shorts_to_videos(tracker)

    return len(new_shorts)


def _link_shorts_to_videos(tracker: dict):
    """
    For each short whose video_stem matches a video_tracker entry's video_stem,
    populate linked_video_id and linked_video_publish_at.
    """
    video_tracker = _load_video_tracker()
    stem_map = {
        v["video_stem"]: v
        for v in video_tracker
        if v.get("video_stem")
    }
    if not stem_map:
        return

    changed = False
    for short in tracker["shorts"]:
        if short.get("linked_video_id"):
            continue
        # short.video_stem is the full stem including genre suffix
        # video_tracker.video_stem is also the full stem including genre suffix
        matched = stem_map.get(short["video_stem"])
        if matched:
            short["linked_video_id"] = matched["video_id"]
            short["linked_video_publish_at"] = matched["publish_at"]
            changed = True

    if changed:
        _save_tracker(tracker)


# =============================================================================
# SHORT SELECTION
# =============================================================================

def _unused_shorts(tracker: dict) -> list:
    return [s for s in tracker["shorts"] if s["status"] == "unused"]


def _pick_short(
    pool: list,
    prefer_video_stem: str = None,
    prefer_folder: str = None,
    exclude_ids: set = None,
    exclude_folders: set = None,
    released_before: date = None,
) -> dict | None:
    """
    Pick one short from the pool according to preference/exclusion rules.

    Priority order:
    1. Preferred video_stem (exact match for linking to a specific video)
    2. Preferred video_folder (post-release or teaser for a specific folder)
    3. Any short not in excluded folders
    4. Any short at all (fallback)

    released_before: if set, excludes shorts from videos whose linked_video_publish_at
    is after this date. Shorts with no linked publish date are always eligible.
    """
    exclude_ids = exclude_ids or set()
    exclude_folders = exclude_folders or set()

    candidates = [s for s in pool if s["id"] not in exclude_ids]

    if released_before is not None:
        def _is_released(s):
            pub = s.get("linked_video_publish_at")
            if not pub:
                return False  # unlinked = unknown release date, exclude from archive fill
            try:
                return datetime.strptime(pub[:10], "%Y-%m-%d").date() <= released_before
            except Exception:
                return False
        candidates = [s for s in candidates if _is_released(s)]

    # Tier 1: preferred stem match
    if prefer_video_stem:
        tier1 = [s for s in candidates if s["video_stem"] == prefer_video_stem]
        if tier1:
            return random.choice(tier1)

    # Tier 2: preferred folder
    if prefer_folder:
        tier2 = [
            s for s in candidates
            if s["video_folder"] == prefer_folder
            and s["video_folder"] not in exclude_folders
        ]
        if tier2:
            return random.choice(tier2)

    # Tier 3: any short not in excluded folders
    tier3 = [s for s in candidates if s["video_folder"] not in exclude_folders]
    if tier3:
        return random.choice(tier3)

    # Tier 4: fallback — any unused short
    return random.choice(candidates) if candidates else None


def _find_video_for_sunday(sunday: date, video_tracker: list) -> dict | None:
    """Find the video_tracker entry scheduled to publish on the given Sunday."""
    for v in video_tracker:
        pa = v.get("publish_at")
        if not pa:
            continue
        try:
            publish_date = datetime.strptime(pa[:10], "%Y-%m-%d").date()
            if publish_date == sunday:
                return v
        except Exception:
            continue
    return None


# =============================================================================
# METADATA GENERATION
# =============================================================================

def _generate_short_metadata(short: dict, slot_type: str, video_title: str) -> tuple[str, str]:
    """Return (title, description) for a short based on its slot type."""
    if slot_type == "teaser_sunday":
        return TEASER_SUNDAY_TITLE, TEASER_SUNDAY_DESCRIPTION

    if slot_type == "teaser_tomorrow":
        return TEASER_TOMORROW_TITLE, TEASER_TOMORROW_DESCRIPTION

    # Standalone — use effect-specific hook
    effect = short.get("effect", "warm_grade")
    hooks = STANDALONE_HOOKS.get(effect, STANDALONE_HOOKS["warm_grade"])
    hook = random.choice(hooks)
    title = f"{hook} | Fairway Frequencies #shorts"
    title = title[:100]  # YouTube title limit
    return title, STANDALONE_DESCRIPTION


# =============================================================================
# YOUTUBE UPLOAD
# =============================================================================

def _upload_short_to_youtube(
    file_path: str,
    title: str,
    description: str,
    publish_at: datetime,
    youtube,
) -> str:
    """
    Upload one short to YouTube as a private scheduled video.
    Returns the YouTube video ID.
    YouTube auto-classifies videos under 60s in 9:16 as Shorts.
    """
    publish_at_str = publish_at.strftime("%Y-%m-%dT%H:%M:%S%z")

    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": ["lofi", "golf", "shorts", "studymusic", "lofimusic", "golfvibes",
                     "chillbeats", "lofibeats", "fairwayfrequencies"],
            "categoryId": "10",
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus": "private",
            "publishAt": publish_at_str,
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True,
        },
    }

    media = MediaFileUpload(
        file_path,
        mimetype="video/mp4",
        resumable=True,
        chunksize=1024 * 1024 * 20,  # 20MB chunks (shorts are small)
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            logger.debug(f"    Upload progress: {int(status.progress() * 100)}%")

    video_id = response.get("id")
    if not video_id:
        raise RuntimeError(f"Short upload completed but no video ID returned: {response}")
    return video_id


# =============================================================================
# MAIN SCHEDULER
# =============================================================================

def schedule_weeks(
    weeks_ahead: int = 4,
    client_id: str = None,
    client_secret: str = None,
    dry_run: bool = False,
) -> list[dict]:
    """
    Seed the tracker, build the weekly schedule for the next N weeks,
    upload shorts to YouTube, and update the tracker.

    Args:
        weeks_ahead:   How many future weeks to schedule.
        client_id:     YouTube OAuth client ID (required unless dry_run).
        client_secret: YouTube OAuth client secret (required unless dry_run).
        dry_run:       If True, print the schedule without uploading anything.

    Returns:
        List of scheduled slot dicts (for logging/review).
    """
    seed_tracker()
    tracker = _load_tracker()
    video_tracker = _load_video_tracker()

    if not dry_run and (not client_id or not client_secret):
        raise RuntimeError(
            "YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET are required for uploading.\n"
            "Add --dry-run to preview the schedule without uploading."
        )

    youtube = None
    if not dry_run:
        if not GOOGLE_LIBS_AVAILABLE:
            raise RuntimeError(
                "YouTube upload libraries not installed.\n"
                "Run: pip install google-api-python-client google-auth-oauthlib"
            )
        youtube = _get_client(client_id, client_secret)

    # Find the next Monday on or after today
    today = date.today()
    days_until_monday = (7 - today.weekday()) % 7
    if days_until_monday == 0:
        days_until_monday = 0  # today is already Monday
    first_monday = today + timedelta(days=days_until_monday)

    scheduled_slots = []
    pool = _unused_shorts(tracker)

    for week_offset in range(weeks_ahead):
        week_monday = first_monday + timedelta(weeks=week_offset)
        last_sunday = week_monday - timedelta(days=1)
        next_sunday = week_monday + timedelta(days=6)

        last_video = _find_video_for_sunday(last_sunday, video_tracker)
        next_video = _find_video_for_sunday(next_sunday, video_tracker)

        # Determine preferred folders/stems for each slot tier
        last_stem = last_video.get("video_stem") if last_video else None
        next_stem = next_video.get("video_stem") if next_video else None

        # For folder-level selection when stem isn't available
        last_folder = _folder_for_stem(last_stem) if last_stem else None
        next_folder = _folder_for_stem(next_stem) if next_stem else None

        used_ids = set()
        used_folders = set()

        def pick(prefer_stem=None, prefer_folder=None, exclude_folders=None, released_before=None):
            s = _pick_short(
                pool,
                prefer_video_stem=prefer_stem,
                prefer_folder=prefer_folder,
                exclude_ids=used_ids,
                exclude_folders=exclude_folders or used_folders,
                released_before=released_before,
            )
            if s:
                used_ids.add(s["id"])
                used_folders.add(s["video_folder"])
                pool.remove(s)
            return s

        # Mon/Tue: post-release standalones — prefer last Sunday's video, but
        # always restrict fallback to shorts from videos released by the slot date
        mon_date = week_monday + timedelta(days=0)
        tue_date = week_monday + timedelta(days=1)
        mon_short = pick(prefer_stem=last_stem, prefer_folder=last_folder, released_before=mon_date)
        tue_short = pick(prefer_stem=last_stem, prefer_folder=last_folder, released_before=tue_date)

        # Wed/Sat: teasers for next Sunday's video — skip entirely if no video is scheduled
        if next_video is None:
            wed_short = None
            sat_short = None
        else:
            wed_short = pick(prefer_stem=next_stem, prefer_folder=next_folder)
            # Sat: prefer same folder as Wed (same upcoming hole) — explicitly allow Wed's folder
            sat_prefer_folder = next_folder or (wed_short["video_folder"] if wed_short else None)
            sat_short = _pick_short(
                pool,
                prefer_video_stem=next_stem,
                prefer_folder=sat_prefer_folder,
                exclude_ids=used_ids,
                exclude_folders=used_folders - ({wed_short["video_folder"]} if wed_short else set()),
            )
            if sat_short:
                used_ids.add(sat_short["id"])
                used_folders.add(sat_short["video_folder"])
                pool.remove(sat_short)

        # Thu/Fri: archive — only from videos already released by the slot date
        thu_date = week_monday + timedelta(days=3)
        fri_date = week_monday + timedelta(days=4)
        thu_short = pick(released_before=thu_date)
        fri_short = pick(released_before=fri_date)

        day_slots = [
            (week_monday + timedelta(days=0), mon_short, "standalone"),
            (week_monday + timedelta(days=1), tue_short, "standalone"),
            (week_monday + timedelta(days=2), wed_short, "teaser_sunday"),
            (week_monday + timedelta(days=3), thu_short, "standalone"),
            (week_monday + timedelta(days=4), fri_short, "standalone"),
            (week_monday + timedelta(days=5), sat_short, "teaser_tomorrow"),
        ]

        for slot_date, short, slot_type in day_slots:
            publish_at = datetime(
                slot_date.year, slot_date.month, slot_date.day,
                POST_HOUR_EST, 0, 0, tzinfo=EST,
            )

            if publish_at.date() < today:
                continue  # Never schedule in the past

            if short is None:
                logger.warning(f"  No available short for {slot_date} ({slot_type}) — slot skipped")
                continue

            video_title = _read_video_title(short["video_folder"])
            title, description = _generate_short_metadata(short, slot_type, video_title)

            slot_info = {
                "date": slot_date.isoformat(),
                "slot_type": slot_type,
                "short_id": short["id"],
                "file": short["file_path"],
                "title": title,
                "video_folder": short["video_folder"],
                "effect": short["effect"],
                "genre": short["genre"],
            }

            if dry_run:
                logger.info(
                    f"  [DRY RUN] {slot_date} ({slot_type}): "
                    f"{short['video_folder']} / {short['effect']} / {short['genre']}"
                )
                logger.info(f"            Title: {title}")
                scheduled_slots.append(slot_info)
                continue

            logger.info(
                f"  Uploading {slot_date} ({slot_type}): "
                f"{short['video_folder']} / {short['effect']} / {short['genre']}"
            )

            try:
                yt_id = _upload_short_to_youtube(
                    file_path=short["file_path"],
                    title=title,
                    description=description,
                    publish_at=publish_at,
                    youtube=youtube,
                )
                short["status"] = "scheduled"
                short["short_type"] = slot_type
                short["scheduled_for"] = publish_at.isoformat()
                short["youtube_short_id"] = yt_id
                slot_info["youtube_short_id"] = yt_id
                logger.info(f"    ✓ Scheduled: https://youtu.be/{yt_id}")
            except Exception as e:
                logger.error(f"    ✗ Upload failed: {e}")

            scheduled_slots.append(slot_info)

        # Save tracker after each week so progress isn't lost on errors
        _save_tracker(tracker)

    return scheduled_slots


def _folder_for_stem(video_stem: str) -> str | None:
    """
    Find the Video_X folder that contains a given video_stem in its shorts directory.
    Used when a stem is known but the folder isn't (e.g., from video_tracker).
    """
    if not video_stem or not os.path.isdir(ARCHIVE_DIR):
        return None
    for folder in os.listdir(ARCHIVE_DIR):
        shorts_dir = os.path.join(ARCHIVE_DIR, folder, "shorts")
        if os.path.isdir(os.path.join(shorts_dir, video_stem)):
            return folder
    return None


def _normalize_title(title: str) -> str:
    """Strip channel branding and formatting for fuzzy comparison."""
    t = title.lower()
    for prefix in [
        "fairway frequencies — ", "fairway frequencies - ",
        "lofi study music • ", "lofi study music - ",
    ]:
        t = t.replace(prefix, "")
    t = t.split("|")[0].split("•")[0].strip()
    # Remove common suffixes like "2 hours", "chill lofi golf ⛳"
    for suffix in ["chill lofi golf", "lofi golf", "2 hours", "1 hour", "⛳"]:
        t = t.replace(suffix, "")
    return t.strip()


def _stem_timestamp(stem: str) -> datetime | None:
    """Extract the datetime embedded in a video stem filename."""
    import re
    m = re.search(r"(\d{8}_\d{6})", stem)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y%m%d_%H%M%S")
        except ValueError:
            pass
    return None


def backfill_video_links(dry_run: bool = False) -> list[dict]:
    """
    Match video_tracker.json entries (which lack video_stem) to archive folders
    by fuzzy title comparison, then update both trackers with the link.

    Uses stem timestamp proximity to disambiguate multiple archive videos with
    the same title (e.g. jazz/hiphop AB-test pairs).

    Args:
        dry_run: If True, print proposed matches without saving anything.

    Returns:
        List of match result dicts for reporting.
    """
    video_tracker = _load_video_tracker()
    unlinked = [v for v in video_tracker if not v.get("video_stem")]

    if not unlinked:
        logger.info("  All tracker videos already have video_stem — nothing to backfill.")
        return []

    # Build map of all archive stems: [(video_folder, stem, title, stem_dt)]
    archive_index = []
    for folder in sorted(os.listdir(ARCHIVE_DIR)):
        folder_path = os.path.join(ARCHIVE_DIR, folder)
        if not os.path.isdir(folder_path):
            continue
        for fname in sorted(os.listdir(folder_path)):
            if not fname.endswith("_metadata.json"):
                continue
            stem = fname.replace("_metadata.json", "")
            try:
                with open(os.path.join(folder_path, fname), encoding="utf-8") as f:
                    meta = json.load(f)
                title = meta.get("title", "")
                archive_index.append((folder, stem, title, _stem_timestamp(stem)))
            except Exception:
                pass

    results = []
    used_stems = set()  # Prevent two tracker entries from claiming the same stem

    for entry in unlinked:
        entry_norm = _normalize_title(entry["title"])

        # Score all archive stems against this tracker entry
        scored = []
        for folder, stem, title, stem_dt in archive_index:
            if stem in used_stems:
                continue
            archive_norm = _normalize_title(title)
            score = SequenceMatcher(None, entry_norm, archive_norm).ratio()
            scored.append((score, stem_dt, folder, stem, title))

        if not scored:
            results.append({"entry": entry, "match": None, "confidence": 0})
            continue

        # Sort by score desc, then by proximity of stem timestamp to upload time
        try:
            upload_dt = datetime.strptime(entry["uploaded_at"][:19], "%Y-%m-%dT%H:%M:%S")
        except Exception:
            upload_dt = None

        def sort_key(item):
            score, stem_dt, *_ = item
            if upload_dt and stem_dt:
                secs = abs((stem_dt - upload_dt).total_seconds())
            else:
                secs = float("inf")
            return (-score, secs)

        scored.sort(key=sort_key)
        best_score, _, best_folder, best_stem, best_title = scored[0]

        result = {
            "entry": entry,
            "match_folder": best_folder,
            "match_stem": best_stem,
            "match_title": best_title,
            "confidence": best_score,
        }
        results.append(result)

        if best_score >= 0.65:
            used_stems.add(best_stem)
            if not dry_run:
                entry["video_stem"] = best_stem

    if not dry_run:
        # Save updated video_tracker.json
        os.makedirs("output", exist_ok=True)
        with open(VIDEO_TRACKER_PATH, "w", encoding="utf-8") as f:
            json.dump(video_tracker, f, indent=2, ensure_ascii=False)

        # Re-seed and re-link shorts
        seed_tracker()
        logger.info("  Tracker updated and shorts re-linked.")

    return results


def print_backfill_report(results: list[dict]):
    """Print a human-readable backfill match report."""
    print(f"\n  Backfill Report — {len(results)} tracker videos")
    print(f"  {'─' * 70}")
    for r in results:
        entry = r["entry"]
        pub = entry.get("publish_at", "")[:10]
        entry_title = entry["title"][:45]
        if r.get("match_stem"):
            conf = r["confidence"]
            icon = "✓" if conf >= 0.65 else "?"
            print(f"  {icon} [{pub}] {entry_title:<45}")
            print(f"      → {r['match_folder']} / {r['match_stem'][-40:]}")
            print(f"        Archive title: {r['match_title'][:55]}  ({conf:.0%})")
        else:
            print(f"  ✗ [{pub}] {entry_title:<45}  (no archive match found)")
    print()


def _get_client(client_id: str, client_secret: str):
    """
    Get an authenticated YouTube API client with full access (upload + read).
    Shared by both the importer and the shorts uploader.
    Opens a browser on first run — make sure to sign in as your CHANNEL account.
    """
    if not GOOGLE_LIBS_AVAILABLE:
        raise RuntimeError(
            "YouTube libraries not installed.\n"
            "Run: pip install google-api-python-client google-auth-oauthlib"
        )

    credentials = None
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "r") as f:
                credentials = Credentials.from_authorized_user_info(
                    json.load(f), YOUTUBE_SCOPES
                )
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
        flow = InstalledAppFlow.from_client_config(client_config, YOUTUBE_SCOPES)
        logger.info("  Opening browser for YouTube authentication...")
        logger.info("  IMPORTANT: Sign in as the Google account that OWNS Fairway Frequencies.")
        logger.info("  If you see multiple accounts, pick the one you use in YouTube Studio.")
        credentials = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            json.dump(json.loads(credentials.to_json()), f)
        logger.info(f"  Credentials saved to {TOKEN_FILE}")

    return _yt_build("youtube", "v3", credentials=credentials)


def import_channel_videos(
    client_id: str,
    client_secret: str,
    dry_run: bool = False,
) -> list[dict]:
    """
    Fetch all videos from the authenticated YouTube channel, import any that
    are missing from video_tracker.json, and attempt to link them to archive
    folders by title.

    Covers:
    - Scheduled private videos (publishAt set, not yet public)
    - Already-published public videos

    Args:
        client_id:     YouTube OAuth client ID.
        client_secret: YouTube OAuth client secret.
        dry_run:       If True, report what would be imported without saving.

    Returns:
        List of import result dicts for reporting.
    """
    youtube = _get_client(client_id, client_secret)
    video_tracker = _load_video_tracker()
    known_ids = {v["video_id"] for v in video_tracker}

    # ── Step 1: get the uploads playlist ID for this channel ──────────────────
    logger.info("  Fetching channel uploads playlist...")
    ch_resp = youtube.channels().list(part="contentDetails", mine=True).execute()
    items = ch_resp.get("items", [])
    if not items:
        raise RuntimeError("No channel found for this account.")
    uploads_playlist = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    logger.info(f"  Uploads playlist: {uploads_playlist}")

    # ── Step 2: page through all videos in the uploads playlist ───────────────
    all_video_ids = []
    next_page = None
    while True:
        kwargs = dict(
            part="snippet",
            playlistId=uploads_playlist,
            maxResults=50,
        )
        if next_page:
            kwargs["pageToken"] = next_page
        resp = youtube.playlistItems().list(**kwargs).execute()
        for item in resp.get("items", []):
            vid_id = item["snippet"]["resourceId"]["videoId"]
            if vid_id not in known_ids:
                all_video_ids.append(vid_id)
        next_page = resp.get("nextPageToken")
        if not next_page:
            break

    logger.info(f"  Found {len(all_video_ids)} videos not yet in tracker")

    if not all_video_ids:
        return []

    # ── Step 3: fetch full details in batches of 50 ───────────────────────────
    channel_videos = []
    for i in range(0, len(all_video_ids), 50):
        batch = all_video_ids[i:i + 50]
        resp = youtube.videos().list(
            part="snippet,status",
            id=",".join(batch),
        ).execute()
        for v in resp.get("items", []):
            status = v.get("status", {})
            snippet = v.get("snippet", {})
            publish_at = status.get("publishAt") or snippet.get("publishedAt")
            channel_videos.append({
                "video_id": v["id"],
                "title": snippet.get("title", ""),
                "privacy": status.get("privacyStatus", ""),
                "publish_at": publish_at,
                "uploaded_at": snippet.get("publishedAt", ""),
            })

    # ── Step 4: match to archive folders by title ─────────────────────────────
    archive_index = []
    for folder in sorted(os.listdir(ARCHIVE_DIR)):
        folder_path = os.path.join(ARCHIVE_DIR, folder)
        if not os.path.isdir(folder_path):
            continue
        for fname in sorted(os.listdir(folder_path)):
            if not fname.endswith("_metadata.json"):
                continue
            stem = fname.replace("_metadata.json", "")
            try:
                with open(os.path.join(folder_path, fname), encoding="utf-8") as f:
                    meta = json.load(f)
                archive_index.append((folder, stem, meta.get("title", ""), _stem_timestamp(stem)))
            except Exception:
                pass

    used_stems = {v.get("video_stem") for v in video_tracker if v.get("video_stem")}

    results = []
    new_entries = []

    for cv in channel_videos:
        cv_norm = _normalize_title(cv["title"])

        scored = [
            (SequenceMatcher(None, cv_norm, _normalize_title(t)).ratio(), stem_dt, folder, stem, t)
            for folder, stem, t, stem_dt in archive_index
            if stem not in used_stems
        ]

        best_match = None
        best_confidence = 0.0
        if scored:
            try:
                cv_upload_dt = datetime.strptime(cv["uploaded_at"][:19], "%Y-%m-%dT%H:%M:%S")
            except Exception:
                cv_upload_dt = None

            def _key(item):
                score, stem_dt, *_ = item
                secs = abs((stem_dt - cv_upload_dt).total_seconds()) if cv_upload_dt and stem_dt else float("inf")
                return (-score, secs)

            scored.sort(key=_key)
            best_score, _, best_folder, best_stem, best_title = scored[0]
            best_match = {"folder": best_folder, "stem": best_stem, "title": best_title}
            best_confidence = best_score

        result = {
            "video_id": cv["video_id"],
            "title": cv["title"],
            "privacy": cv["privacy"],
            "publish_at": cv["publish_at"],
            "uploaded_at": cv["uploaded_at"],
            "match": best_match,
            "confidence": best_confidence,
        }
        results.append(result)

        if not dry_run:
            entry = {
                "video_id": cv["video_id"],
                "title": cv["title"],
                "uploaded_at": cv["uploaded_at"],
                "publish_at": cv["publish_at"],
            }
            if best_match and best_confidence >= 0.65:
                entry["video_stem"] = best_match["stem"]
                used_stems.add(best_match["stem"])
            new_entries.append(entry)

    if not dry_run and new_entries:
        video_tracker.extend(new_entries)
        os.makedirs("output", exist_ok=True)
        with open(VIDEO_TRACKER_PATH, "w", encoding="utf-8") as f:
            json.dump(video_tracker, f, indent=2, ensure_ascii=False)
        logger.info(f"  Saved {len(new_entries)} new entries to video_tracker.json")
        seed_tracker()

    return results


def print_import_report(results: list[dict]):
    """Print a human-readable import report."""
    print(f"\n  Import Report — {len(results)} new videos found on channel")
    print(f"  {'─' * 70}")
    for r in results:
        pub = (r.get("publish_at") or "")[:10]
        title = r["title"][:48]
        priv = r["privacy"]
        if r["match"] and r["confidence"] >= 0.65:
            print(f"  ✓ [{pub}] ({priv:<9}) {title}")
            print(f"      Archive match ({r['confidence']:.0%}): {r['match']['folder']} / {r['match']['stem'][-35:]}")
        else:
            conf_str = f"{r['confidence']:.0%}" if r["match"] else "no archive"
            print(f"  ? [{pub}] ({priv:<9}) {title}")
            print(f"      No archive match  ({conf_str})")
    print()


def print_tracker_summary():
    """Print a human-readable summary of the shorts tracker status."""
    tracker = _load_tracker()
    shorts = tracker["shorts"]

    total = len(shorts)
    unused = sum(1 for s in shorts if s["status"] == "unused")
    scheduled = sum(1 for s in shorts if s["status"] == "scheduled")
    posted = sum(1 for s in shorts if s["status"] == "posted")

    print(f"\n  Shorts Tracker Summary")
    print(f"  {'─' * 40}")
    print(f"  Total registered: {total}")
    print(f"  Unused (available): {unused}")
    print(f"  Scheduled: {scheduled}")
    print(f"  Posted: {posted}")

    if scheduled:
        print(f"\n  Upcoming scheduled:")
        upcoming = sorted(
            [s for s in shorts if s["status"] == "scheduled" and s.get("scheduled_for")],
            key=lambda s: s["scheduled_for"],
        )
        for s in upcoming[:10]:
            dt = s["scheduled_for"][:10]
            print(f"    {dt}  {s['short_type']:<18} {s['video_folder']} / {s['effect']} / {s['genre']}")
    print()


def reset_scheduled_shorts() -> int:
    """
    Reset all shorts with status 'scheduled' back to 'unused', clearing their
    YouTube IDs and schedule metadata. Run this after deleting the corresponding
    YouTube videos so the tracker stays in sync.

    Returns the number of shorts reset.
    """
    tracker = _load_tracker()
    count = 0
    for short in tracker["shorts"]:
        if short["status"] == "scheduled":
            short["status"] = "unused"
            short["short_type"] = None
            short["scheduled_for"] = None
            short["youtube_short_id"] = None
            count += 1
    _save_tracker(tracker)
    logger.info(f"  Reset {count} shorts from 'scheduled' to 'unused'")
    return count
