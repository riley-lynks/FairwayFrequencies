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

import json
import logging
import time
import anthropic
import config

logger = logging.getLogger("fairway.metadata_gen")


def generate_metadata(
    scene_prompt: str,
    orchestration: dict,
    api_key: str,
    claude_model: str,
    logger: logging.Logger = None,
) -> dict:
    """
    Generate YouTube metadata using Claude.

    Args:
        scene_prompt:   The original scene description.
        orchestration:  The full orchestration dict (has mood, time_of_day, etc.)
        api_key:        Anthropic API key.
        claude_model:   Claude model identifier.
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

    # Load the metadata system prompt
    try:
        with open("prompts/metadata_system.txt", "r", encoding="utf-8") as f:
            system_prompt = f.read()
    except FileNotFoundError:
        system_prompt = _get_inline_metadata_prompt()

    user_message = f"""Scene: "{scene_prompt}"
Mood: {mood}
Time of day: {time_of_day}
Season: {season}
Has character: {has_character}
Channel name: Fairway Frequencies

Generate YouTube metadata for this LoFi Golf video.
{f'Include: "{character_note}"' if character_note else ''}

Remember:
- Title should be under 70 characters
- Description should hook viewers in the first 2 lines (they appear before "...more")
- Include 20-30 relevant tags
- This is a 2-3 hour relaxation/study music video"""

    local_logger.debug("  Calling Claude for metadata generation...")

    client = anthropic.Anthropic(api_key=api_key)

    for attempt in range(config.MAX_RETRIES):
        try:
            response = client.messages.create(
                model=claude_model,
                max_tokens=2000,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
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

            local_logger.info(f"  ✓ Title: {metadata['title']}")
            return metadata

        except json.JSONDecodeError:
            # Claude returned non-JSON — build a fallback
            local_logger.warning("  ⚠️ Claude returned non-JSON metadata, using fallback")
            return _build_fallback_metadata(scene_prompt, mood, time_of_day, season, has_character)

        except Exception as e:
            local_logger.warning(f"  ⚠️ Metadata attempt {attempt+1} failed: {e}")
            if attempt < config.MAX_RETRIES - 1:
                time.sleep(config.RETRY_BASE_DELAY * (2 ** attempt))

    return _build_fallback_metadata(scene_prompt, mood, time_of_day, season, has_character)


def _build_fallback_metadata(scene_prompt, mood, time_of_day, season, has_character) -> dict:
    """Build fallback metadata without Claude if the API fails."""
    char_note = " • featuring our signature golfer" if has_character else ""
    return {
        "title": f"Fairway Frequencies — {scene_prompt[:45]} | LoFi Golf ⛳",
        "description": (
            f"Step onto the course and let the music carry you. "
            f"A {mood} {time_of_day} at a beautiful golf course{char_note}, "
            f"animated in our signature anime/Ghibli art style.\n\n"
            "✦ 2+ Hours of LoFi Golf Ambience\n"
            "✦ No ads mid-video\n"
            "✦ Perfect for studying, working, or relaxing\n\n"
            "#lofi #golf #studymusic #chillmusic #relax\n\n"
            "Fairway Frequencies — Where Golf Meets LoFi\n"
            "Subscribe for new living painting videos every week. ⛳"
        ),
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

Title formula: "Fairway Frequencies — [Scene] | [Mood keyword] Golf [Genre] ⛳"
Examples:
  "Fairway Frequencies — Misty Dawn Links Course | Chill Golf LoFi ⛳"
  "Fairway Frequencies — Cherry Blossom Golf Course | Peaceful Study Music ⛳"

Tags should include: lofi, golf, lofi golf, study music, chill music, the scene keywords,
anime, ghibli, and long-tail variations that golfers and study-music fans would search for."""
