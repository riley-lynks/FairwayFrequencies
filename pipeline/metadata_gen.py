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
import json
import logging
import os
import time
import anthropic
import config

logger = logging.getLogger("fairway.metadata_gen")


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
        logger:         Logger for progress messages.

    Returns:
        Dict with 'title', 'description', 'tags', 'category', 'is_made_for_kids'.
    """
    local_logger = logger or logging.getLogger("fairway.metadata_gen")

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

Generate YouTube metadata for this LoFi Golf video.

Remember:
- Title should be under 70 characters
- Description must hook viewers in the first 2 lines (they appear before "...more")
- Description body must weave in searchable keyword phrases naturally (lofi, study music, golf, chill, focus music, etc.)
- Include 25-30 tags
- Provide exactly {len(stamps)} chapter names (one per timestamp: {timestamps_str})
- This is a {duration_hours}-hour relaxation/study music video"""

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
                system=system_prompt,
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
    """Fallback metadata system prompt."""
    return """You are the social media manager for "Fairway Frequencies", a LoFi Golf YouTube channel.
Your job is to write YouTube metadata that maximizes discoverability and clicks.

The channel concept: Long-form (2-3 hour) animated anime/Ghibli golf course scenes with LoFi music.
The audience: Students, remote workers, golfers who use lo-fi as focus/relaxation music.

Output ONLY valid JSON with these fields:
{
  "title": "string — under 70 chars, compelling, includes key terms",
  "description": "string — hooks in first 2 lines, includes keywords, channel CTA",
  "tags": ["array", "of", "20-30", "tags"]
}

Title formula: "[Mood/Time] + [Golf Element] + [LoFi Keyword] + [Duration] ⛳"
Examples:
  "Misty Morning Golf Course | Chill Lofi Beats | 2 Hours ⛳"
  "Golden Hour Fairway | Study Music Lofi | 2 Hours ⛳"
  "Moonlit Links Course | Dreamy Lofi Hip Hop | 3 Hours ⛳"

Description structure:
  Line 1 (fixed): "Lofi beats and ambient sounds for studying, working, and relaxing — from the world's most peaceful golf courses. 🎵"
  Line 2: Unique 2-3 sentence scene description with keywords woven in naturally.
  Line 3 (fixed): "🔔 New scenes drop every week — subscribe so you never miss a round.\n👍 If this helped you focus or unwind, a like helps the channel grow.\n🎥 More long-form golf course sessions on the channel."
  Hashtags: #lofi #studymusic #ambientmusic #chillbeats #golfvibes + 3-5 scene-specific ones.

Tags should include: lofi, golf, lofi golf, study music, chill music, the scene keywords,
anime, ghibli, and long-tail variations that golfers and study-music fans would search for."""
