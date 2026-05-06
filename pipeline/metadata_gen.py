# =============================================================================
# pipeline/metadata_gen.py — YouTube Metadata Generation
# =============================================================================
# PURPOSE:
#   Use Claude to generate a compelling YouTube title, description, and tags
#   for the video. Good metadata is crucial for YouTube discoverability.
#
# WHY Claude for metadata? Writing 27 SEO-optimized tags, a description that
# hooks viewers in the first two lines, and a title that performs well in
# YouTube search is a skill. Claude does this better than any template.
#
# OUTPUT:
#   A JSON file saved next to the video with:
#   - title:       The YouTube video title
#   - description: Full YouTube description with timestamps/links
#   - tags:        List of 20-30 YouTube tags
#   - category:    YouTube category ID (10 = Music, 22 = People & Blogs)
#   - is_made_for_kids: False (relaxation content, not kids content)
# =============================================================================

import base64
import glob
import json
import logging
import os
import time
import anthropic
import config

logger = logging.getLogger("fairway.metadata_gen")


def _recent_longform_titles(max_n: int = 20) -> list[str]:
    """Scan output/ for long-form metadata files and return the most-recent
    N titles by file mtime, deduped. Used to feed Claude a "don't repeat
    these phrasings" list so descriptions and titles don't drift into a
    template across uploads."""
    patterns = [
        "output/archive/*/fairway_*_metadata.json",
        "output/archive/fairway_*_metadata.json",
        "output/*/fairway_*_metadata.json",
    ]
    seen_paths = set()
    files = []
    for p in patterns:
        for fp in glob.glob(p):
            if fp not in seen_paths:
                seen_paths.add(fp)
                files.append(fp)

    files.sort(key=lambda f: os.path.getmtime(f), reverse=True)

    titles: list[str] = []
    seen_titles: set[str] = set()
    for fp in files:
        try:
            with open(fp, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            continue
        title = (meta.get("title") or "").strip()
        if title and title not in seen_titles:
            titles.append(title)
            seen_titles.add(title)
            if len(titles) >= max_n:
                break
    return titles


def _chapter_timestamps(duration_hours: float) -> list[tuple[int, str]]:
    """
    Return (seconds, label) pairs at 30-minute intervals for the video duration.
    Always starts at 0:00. Minimum 3 chapters — if duration is under 1h30, we
    still produce 3 by halving the interval.
    """
    total_seconds = int(duration_hours * 3600)
    interval = 1800  # 30 minutes

    # Ensure at least 3 chapters
    while total_seconds // interval < 2:
        interval //= 2

    stamps = []
    t = 0
    while t < total_seconds:
        h = t // 3600
        m = (t % 3600) // 60
        label = f"{h}:{m:02d}:00" if h > 0 else f"{m}:00"
        stamps.append((t, label))
        t += interval
    return stamps


def _append_chapters(description: str, stamps: list[tuple[int, str]], names: list[str]) -> str:
    """Append a YouTube chapter block to the description."""
    lines = ["\n\n📍 CHAPTERS"]
    for (_, ts), name in zip(stamps, names):
        lines.append(f"{ts} {name}")
    return description + "\n".join(lines)


def generate_metadata(
    scene_prompt: str,
    orchestration: dict,
    api_key: str,
    claude_model: str,
    duration_hours: float = 2.0,
    image_path: str = None,
    genre: str = None,
    recent_titles: list = None,
    logger: logging.Logger = None,
) -> dict:
    """
    Generate YouTube metadata using Claude.

    Args:
        scene_prompt:   The original scene description.
        orchestration:  The full orchestration dict (has mood, time_of_day, etc.)
        api_key:        Anthropic API key.
        claude_model:   Claude model identifier.
        image_path:     Path to the selected base image (used for vision-based description).
        genre:          Music genre for this video (e.g. "Jazz", "HipHop"). When set,
                        Claude includes the genre in the title and thumbnail_text.
        recent_titles:  List of recently uploaded long-form titles to avoid echoing.
                        When None, scans output/ for the last 20 titles.
        logger:         Logger for progress messages.

    Returns:
        Dict with 'title', 'description', 'tags', 'category', 'is_made_for_kids'.
    """
    local_logger = logger or logging.getLogger("fairway.metadata_gen")
    if recent_titles is None:
        recent_titles = _recent_longform_titles()

    mood = orchestration.get("mood", "calm")
    time_of_day = orchestration.get("time_of_day", "morning")
    season = orchestration.get("season", "summer")
    has_character = orchestration.get("has_character", False)
    character_note = " featuring our signature golfer overlooking the course" if has_character else ""

    stamps = _chapter_timestamps(duration_hours)
    timestamps_str = ", ".join(ts for _, ts in stamps)

    system_prompt = _get_inline_metadata_prompt()

    # Map raw genre keys to human-readable display names for Claude
    _GENRE_DISPLAY = {"jazz": "Jazz", "hiphop": "Hip-Hop", "hip-hop": "Hip-Hop"}
    genre_display = _GENRE_DISPLAY.get(genre.lower(), genre) if genre else None

    _GENRE_LEAD_PHRASES = {
        "Jazz": '"Jazz to Study & Relax" or "Jazz to Relax To"',
        "Hip-Hop": '"Lofi Hip Hop Study Beats" or "Beats to Study To" or "Chill Beats to Study To"',
    }
    genre_lead_hint = _GENRE_LEAD_PHRASES.get(genre_display, "")
    genre_line = (
        f"\nMusic genre: {genre_display} — "
        f"the title MUST use one of these lead phrases for this genre: {genre_lead_hint}. "
        "Do NOT use a jazz lead phrase for hip-hop or vice versa."
    ) if genre_display and genre_lead_hint else ""

    recent_block = (
        "\n".join(f"- {t}" for t in recent_titles[:20]) if recent_titles else "(none yet)"
    )

    user_message = f"""Scene prompt: "{scene_prompt}"
Mood: {mood}
Time of day: {time_of_day}
Season: {season}
Has character: {has_character}
Video duration: {duration_hours} hours
Chapter timestamps: {timestamps_str}
Channel name: Fairway Frequencies{genre_line}

The image attached is the exact frame used in this video — base the description on what you actually see in it, not on the prompt text.
{f'Note: {character_note}.' if character_note else ''}

recent_titles (avoid echoing these phrasings, hooks, or scene words):
{recent_block}

Generate fresh YouTube metadata for this LoFi Golf video. Provide exactly {len(stamps)} chapter names (one per timestamp: {timestamps_str}). Return ONLY the JSON object."""

    local_logger.debug("  Calling Claude for metadata generation...")

    client = anthropic.Anthropic(api_key=api_key)

    # Build the message content — include the image if available
    message_content: list = []
    if image_path and os.path.exists(image_path):
        ext = os.path.splitext(image_path)[1].lower().lstrip(".")
        media_type = {"jpg": "image/jpeg", "jpeg": "image/jpeg"}.get(ext, "image/png")
        with open(image_path, "rb") as f:
            image_data = base64.standard_b64encode(f.read()).decode("utf-8")
        message_content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": image_data},
        })
        local_logger.debug(f"  Attaching image for vision: {os.path.basename(image_path)}")
    message_content.append({"type": "text", "text": user_message})

    for attempt in range(config.MAX_RETRIES):
        try:
            response = client.messages.create(
                model=claude_model,
                max_tokens=2000,
                system=[{
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": message_content}],
            )

            response_text = response.content[0].text.strip()

            # Strip markdown code blocks if present
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                start = 1
                end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
                response_text = "\n".join(lines[start:end])

            metadata = json.loads(response_text)

            # Ensure required fields exist
            if "title" not in metadata:
                metadata["title"] = f"Fairway Frequencies — {scene_prompt[:50]} | LoFi Golf ⛳"
            if "tags" not in metadata:
                metadata["tags"] = ["lofi", "golf", "relaxing music", "study music", "chill"]
            if "category" not in metadata:
                metadata["category"] = "10"  # Music category

            metadata["is_made_for_kids"] = False

            # Append chapter markers to description
            chapter_names = metadata.pop("chapter_names", None)
            if chapter_names and isinstance(chapter_names, list) and len(chapter_names) >= len(stamps):
                metadata["description"] = _append_chapters(
                    metadata.get("description", ""), stamps, chapter_names[:len(stamps)]
                )
                local_logger.info(f"  ✓ Chapters: {len(stamps)} markers added")
            else:
                # Fallback chapter names if Claude didn't return them
                metadata["description"] = _append_chapters(
                    metadata.get("description", ""), stamps,
                    _fallback_chapter_names(len(stamps), mood)
                )
                local_logger.info(f"  ✓ Chapters: {len(stamps)} fallback markers added")

            local_logger.info(f"  ✓ Title: {metadata['title']}")
            return metadata

        except json.JSONDecodeError:
            # Claude returned non-JSON — build a fallback
            local_logger.warning("  ⚠️ Claude returned non-JSON metadata, using fallback")
            return _build_fallback_metadata(scene_prompt, mood, time_of_day, season, has_character, duration_hours, genre_display)

        except Exception as e:
            local_logger.warning(f"  ⚠️ Metadata attempt {attempt+1} failed: {e}")
            if attempt < config.MAX_RETRIES - 1:
                time.sleep(config.RETRY_BASE_DELAY * (2 ** attempt))

    return _build_fallback_metadata(scene_prompt, mood, time_of_day, season, has_character, duration_hours, genre_display)


def _fallback_chapter_names(count: int, mood: str = "calm") -> list[str]:
    """Generic chapter names when Claude doesn't return them."""
    arcs = [
        "Arrival at the Course",
        "Settling Into the Round",
        "Deep in the Fairway",
        "The Back Nine",
        "Golden Hour on the Green",
        "Final Approach",
        "The 19th Hole",
    ]
    return arcs[:count] if count <= len(arcs) else (arcs + [f"Continuing…"] * (count - len(arcs)))


def _build_fallback_metadata(scene_prompt, mood, time_of_day, season, has_character,
                              duration_hours: float = 2.0, genre_display: str = None) -> dict:
    """Build fallback metadata without Claude if the API fails."""
    stamps = _chapter_timestamps(duration_hours)
    genre_phrase = f" {genre_display}" if genre_display else " Hip Hop"
    base_desc = (
        "Lofi beats and ambient sounds for studying, working, and relaxing — from the world's most peaceful golf courses. 🎵\n\n"
        f"A {mood} {time_of_day} scene at a beautiful golf course. "
        f"Pure lofi{genre_phrase} and ambient sounds for studying, deep focus, and relaxing — no interruptions, just the course.\n\n"
        "🔔 New scenes drop every week — subscribe so you never miss a round.\n"
        "👍 If this helped you focus or unwind, a like helps the channel grow.\n"
        "🎥 More long-form golf course sessions on the channel.\n\n"
        "#lofi #studymusic #ambientmusic #chillbeats #golfvibes"
    )
    description = _append_chapters(base_desc, stamps, _fallback_chapter_names(len(stamps), mood))
    genre_title = f" | {genre_display} Lofi" if genre_display else " Lofi Beats"
    thumbnail_text = f"{genre_display.upper()} LOFI" if genre_display else "STUDY MUSIC"
    return {
        "title": f"{time_of_day.title()} Golf Course{genre_title} | {int(duration_hours)} Hours ⛳",
        "thumbnail_text": thumbnail_text,
        "description": description,
        "tags": [
            "lofi", "golf", "lofi golf", "study music", "chill music",
            "relaxing music", "anime music", "ghibli music", "lo-fi hip hop",
            "lofi hip hop", "concentration music", "focus music", "work music",
            "lofi beats", "golf course", "golf aesthetic", "anime golf",
            "studio ghibli", "lofi study", "2 hour study music",
            "background music", "ambient music", "lofi chill",
            "fairway frequencies", "golf vibes", "peaceful music",
            f"{season} golf", f"{mood} music", f"{time_of_day} vibes",
        ],
        "category": "10",
        "is_made_for_kids": False,
    }


def _get_inline_metadata_prompt() -> str:
    """Long-form video metadata system prompt — written to encourage variety
    across uploads, not templated repetition. Cache-friendly so back-to-back
    AB-test calls reuse the prefix."""
    return """You are the social media manager for "Fairway Frequencies", a YouTube channel that publishes long-form (1-3 hour) animated anime/Ghibli golf course scenes set to LoFi music.

Audience: students studying, remote workers focusing, golfers winding down, anime/Ghibli fans, lofi listeners.
Voice: warm, sensory, slightly poetic, calm. Direct but not flat. Never hype-bro, never aggressive, never AI-tells like "delve into", "unleash", "dive into the world of".

You will receive structured input describing one video:
- scene_prompt: the original scene description
- mood, time_of_day, season: scene attributes
- has_character: whether the channel's signature golfer appears
- duration_hours: video length in hours
- chapter_timestamps: the timestamps that need chapter names (one per timestamp)
- genre: jazz or hiphop when set — controls a required title lead phrase
- recent_titles: titles of recently uploaded long-form videos — DO NOT reuse phrasing, hooks, sentence structure, or scene words from these
- An attached image: the actual frame used in the video. Base the description on what you SEE, not what the prompt says.

Output ONLY valid JSON, no markdown, no preamble, no code fences:
{
  "title": "string under 70 chars",
  "thumbnail_text": "2-4 word ALL CAPS phrase for thumbnail overlay",
  "description": "multi-paragraph string with hook, scene body, CTA, hashtags",
  "tags": ["array", "of", "25-30", "tags"],
  "chapter_names": ["array", "of", "exactly N labels for the chapter_timestamps provided"]
}

TITLE RULES:
- Under 70 characters total
- For jazz: title MUST contain one of "Jazz to Study & Relax" or "Jazz to Relax To"
- For hip-hop: title MUST contain one of "Lofi Hip Hop Study Beats", "Beats to Study To", or "Chill Beats to Study To"
- For untyped (no genre): use "Lofi" or "Chill Lofi" naturally
- End with ⛳ (or include it adjacent to the duration)
- Vary the structure across calls — pick a different shape than the recent_titles. Acceptable shapes:
  * "[Lead Phrase] | [Scene Element] | [Duration] ⛳"
  * "[Scene Element] • [Lead Phrase] ⛳ [Duration]"
  * "[Mood/Time] [Scene] — [Lead Phrase] | [Duration] ⛳"
  * "[Lead Phrase] for [Use Case] | [Scene] ⛳ [Duration]"
- Vary separators across calls: |, •, —, en dash. Do not always use the same one
- Do not reuse the exact word ordering of any recent_title

DESCRIPTION RULES:
The description is multi-paragraph plain text. The first 2 lines are what YouTube shows above the "...more" fold, so they must hook. There is no fixed line-1 or fixed CTA block — write fresh each time.

Structure (flexible — vary across calls):
1. HOOK (1-2 short sentences): pull the viewer into the scene. Mix patterns across calls — sometimes lead with the scene image, sometimes a sensory cue, sometimes a use case ("Settle in for a long study block"), sometimes a contrast or invitation. Do NOT always start with the same fixed phrase.
2. SCENE BODY (2-4 sentences): describe what's IN THE IMAGE — atmosphere, light, color, weather, time of day, mood. Weave search keywords in naturally: lofi, study music, focus music, chill beats, golf, anime, ghibli, plus the genre when set. Sound like a human noticed the scene, not a template.
3. CTA (2-3 lines): nudge subscribe + like + "more on the channel" — but vary the wording AND format. Sometimes use emoji bullets (🔔 👍 🎥), sometimes inline prose, sometimes a single sentence. Don't repeat any single CTA wording across recent_titles.
4. HASHTAGS (last line): 5-8 hashtags including #lofi #studymusic plus 3-5 scene-specific ones. Vary which scene-specific tags you pick.

Total description target: 600-1100 characters before the chapter block (chapters are appended programmatically).

THUMBNAIL_TEXT:
- 2-4 words, ALL CAPS
- When genre is jazz: include "JAZZ" (e.g. "JAZZ LOFI", "JAZZ STUDY", "JAZZ GOLF")
- When genre is hiphop: include "HIP HOP" or "BEATS" (e.g. "HIP HOP STUDY", "LOFI BEATS")
- When no genre: use scene-driven copy ("MISTY LINKS", "GOLDEN HOUR", "STUDY MUSIC")
- Vary across calls — do not reuse a thumbnail_text that appears in recent_titles' implied thumbnails

CHAPTER_NAMES:
- Provide EXACTLY the count of timestamps given in chapter_timestamps
- Should follow a narrative arc through the round (arrival → settling in → deep focus → golden hour → final approach, etc.)
- Use the scene's actual atmosphere — pull words from the image (e.g. "First Light at the Tee", "Mist Lifts Off the Green", "Cherry Blossoms on the 9th")
- Each chapter name 3-7 words, no leading numbers or timestamps

TAGS:
- 25-30 tags total
- Required base set: lofi, golf, lofi golf, study music, chill music, focus music, relaxing music, ambient music, fairway frequencies
- Genre-specific when set: jazz lofi / lofi hip hop / lo-fi hip hop / lofi beats
- Anime/aesthetic: anime music, ghibli music, anime golf, studio ghibli
- Scene-specific: pull 6-10 tags from the actual image and scene_prompt (e.g. coastal links, misty morning, cherry blossom, dawn fairway)
- Long-tail: "{duration_hours} hour study music", "{mood} {time_of_day} music"

Do NOT echo phrasing from recent_titles. Each upload should feel hand-written for that specific scene — not a templated fill-in-the-blank."""
