# =============================================================================
# pipeline/scene_tracker.py — Scene Usage History
# =============================================================================
# PURPOSE:
#   After each successful pipeline run, record which scene was used and when.
#   The analytics dashboard reads this to power the "Next Scene" recommendation,
#   flagging scenes you've already done and how long ago.
#
# FILE: output/scene_history.json
#   [ { "scene_id": "misty_dawn_links", "scene_name": "Misty Dawn Links",
#       "prompt": "...", "used_at": "2026-03-25T14:30:00" }, ... ]
# =============================================================================

import os
import json
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("fairway.scene_tracker")

SCENE_HISTORY_FILE = os.path.join("output", "scene_history.json")


def log_scene_use(prompt: str, scene_library: list = None):
    """
    Record that a scene was used in a pipeline run.

    Tries to match the prompt to a known scene ID from the library.
    If it doesn't match a library scene (i.e. it's a free-text prompt),
    it's still logged under scene_id="custom".

    Args:
        prompt:        The scene prompt used in the run (may be a scene ID or free text).
        scene_library: List of scene dicts from scene_library.json (for ID matching).
    """
    os.makedirs(os.path.dirname(SCENE_HISTORY_FILE), exist_ok=True)

    # Try to match the prompt to a known scene ID
    scene_id = "custom"
    scene_name = prompt[:60]

    if scene_library:
        prompt_lower = prompt.lower().strip()
        for scene in scene_library:
            # Exact match on scene ID (UI sends the ID directly)
            if scene.get("id", "").lower() == prompt_lower:
                scene_id = scene["id"]
                scene_name = scene.get("name", scene_id)
                break
            # Partial match on scene description (free-text run)
            if scene.get("description", "").lower()[:40] in prompt_lower:
                scene_id = scene["id"]
                scene_name = scene.get("name", scene_id)
                break

    entry = {
        "scene_id":   scene_id,
        "scene_name": scene_name,
        "prompt":     prompt,
        "used_at":    datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
    }

    history = load_scene_history()

    # Move to front (most recent first), avoid exact duplicates on same day
    today = entry["used_at"][:10]
    history = [h for h in history if not (h["scene_id"] == scene_id and h["used_at"][:10] == today)]
    history.insert(0, entry)

    try:
        with open(SCENE_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)
        logger.info(f"  ✓ Scene logged: {scene_name} ({scene_id})")
    except Exception as e:
        logger.warning(f"  Could not save scene history: {e}")


def load_scene_history() -> list:
    """
    Load all past scene runs from scene_history.json.

    Returns:
        List of history entries, most recent first.
        Empty list if the file doesn't exist yet.
    """
    if not os.path.exists(SCENE_HISTORY_FILE):
        return []
    try:
        with open(SCENE_HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def get_used_scene_ids() -> dict:
    """
    Return a dict of scene_id → days_ago for all scenes in history.

    Useful for the UI to show "used 5 days ago" badges and for the
    recommendation engine to weight toward unused scenes.

    Returns:
        { "misty_dawn_links": 3, "golden_hour_masters": 12, ... }
    """
    history = load_scene_history()
    now = datetime.now(timezone.utc)
    result = {}

    for entry in history:
        sid = entry.get("scene_id")
        if not sid or sid == "custom":
            continue
        if sid in result:
            continue  # Already have the most recent use (list is newest-first)
        try:
            used_at = datetime.fromisoformat(entry["used_at"].replace("Z", "+00:00"))
            days_ago = (now - used_at).days
            result[sid] = days_ago
        except Exception:
            result[sid] = 999

    return result
