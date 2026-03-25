# =============================================================================
# pipeline/orchestrator.py — Claude-Powered Prompt Decomposition
# =============================================================================
# PURPOSE:
#   Take a simple scene description like "Misty dawn, links-style course,
#   coastal cliffs" and expand it into detailed, structured prompts for
#   every downstream stage: image generation, video animation, music,
#   ambient sounds, and thumbnail.
#
# WHY Claude for this? Because turning "misty dawn golf course" into a perfect
# Midjourney prompt, 10 specific animation descriptions, and a YouTube title
# is a creative task that requires language understanding. Claude does this
# far better than any template-based approach.
#
# HOW IT WORKS:
#   1. We send Claude a detailed system prompt explaining exactly what format
#      we need the output in (JSON)
#   2. We send Claude the user's scene description as the user message
#   3. Claude returns a JSON object with all the prompts we need
#   4. We parse and return that JSON
# =============================================================================

import json       # For parsing Claude's JSON response
import time       # For retry delays
import logging    # For progress messages
import random     # For randomly deciding whether to include a character
import os         # For reading the system prompt file

import anthropic  # The official Anthropic Python SDK — makes Claude API calls easy

import config     # Our configuration settings (API keys, style suffix, etc.)

logger = logging.getLogger("fairway.orchestrator")


def load_system_prompt() -> str:
    """
    Load the orchestrator system prompt from the prompts/ directory.

    WHY a separate file? Keeping prompts in .txt files makes them easy to
    edit without touching Python code. You can tweak the art direction
    instructions without worrying about breaking any code.

    Returns:
        The system prompt as a string, with the STYLE_SUFFIX substituted in.
    """
    prompt_path = os.path.join("prompts", "orchestrator_system.txt")

    if not os.path.exists(prompt_path):
        # If the file is missing, fall back to the inline default
        logger.warning(
            f"  ⚠️ System prompt file not found at {prompt_path}. "
            "Using inline fallback prompt."
        )
        return _get_inline_system_prompt()

    with open(prompt_path, "r", encoding="utf-8") as f:
        prompt_text = f.read()

    # Replace the {STYLE_SUFFIX} placeholder with the actual suffix from config
    return prompt_text.replace("{STYLE_SUFFIX}", config.STYLE_SUFFIX)


def _get_inline_system_prompt() -> str:
    """
    Fallback system prompt used if the prompts/orchestrator_system.txt file
    is missing. Identical in content to the file version.

    Returns:
        The complete system prompt string.
    """
    return f"""You are a creative director for "Fairway Frequencies", a LoFi Golf YouTube channel.
Your job is to decompose a simple scene description into detailed prompts for an AI video pipeline.

CRITICAL OUTPUT FORMAT:
You MUST respond with ONLY valid JSON. No markdown, no explanation, no code blocks.
The JSON must exactly match the schema shown below.

THE ART STYLE:
Every image you describe must be an illustrated anime/Ghibli background painting.
NOT photorealistic. NOT cartoonish. Think Studio Ghibli film backgrounds —
lush, painted, vibrant, detailed, with clean linework and warm natural lighting.

IMAGE COMPOSITION REQUIREMENTS (very important for animation to look good):
- Clear foreground elements (flowers, grass detail, a bench, the putting green)
- Rich middle ground (the course itself, bunkers, paths, water features)
- Atmospheric background (sky, clouds, distant trees, hills, ocean)
- At least ONE naturally-moving element: flag pin, water feature, trees, flowers
- At least 30% of the frame should be sky/clouds (clouds carry most of the animation)

IMAGE PROMPT LANGUAGE:
- USE: "painted sky", "illustrated foliage", "stylized clouds", "concept art lighting"
- NEVER USE: "4K", "photorealistic", "DSLR", "photograph", "realistic", "cinema"

ANIMATION PROMPT LANGUAGE:
- USE: "gentle animated motion", "leaves drifting", "subtle parallax", "soft breeze animation"
- ALL motion must be SUBTLE. Think "breathing painting" not "action movie"
- No camera movement, no zoom, no panning — just organic natural motion in the scene

STYLE SUFFIX (MUST be appended to the image_prompt and thumbnail_prompt):
{config.STYLE_SUFFIX}

OUTPUT JSON SCHEMA:
{{
  "image_prompt": "string — ONE detailed image prompt WITH the style suffix appended at the end",
  "has_character": boolean,
  "character_description": "string — if has_character is true, describe the foreground figure",
  "base_video_prompt": "string — base animation direction for all 10 clips",
  "animation_variations": [
    {{
      "prompt": "Tripod shot, fixed camera, no zoom, no camera movement. [scene-specific element animation]. Static background, original composition maintained.",
      "negative_prompt": "camera shake, camera movement, camera pan, camera tilt, zoom, tracking shot, dolly, handheld, shaky cam, motion blur, scene change"
    }}
    ... 6 objects total, one per clip
  ],
  "music_prompt": "string — LoFi music description for Mubert API",
  "ambience_keywords": ["string — 3-5 keywords for ambient sound search on Freesound"],
  "thumbnail_prompt": "string — same scene, slightly more vibrant, with style suffix",
  "mood": "string — one word: calm, warm, nostalgic, dramatic, cozy, peaceful, etc.",
  "time_of_day": "string — dawn, morning, midday, afternoon, golden_hour, dusk, night",
  "season": "string — spring, summer, autumn, winter"
}}"""


def _should_include_character(character_mode: str) -> bool:
    """
    Decide whether this video should include a foreground character figure.

    WHY a function? The character_mode can be "always", "never", or "random",
    and we want consistent logic for resolving "random" to an actual boolean.

    Args:
        character_mode: "always", "never", or "random"

    Returns:
        True if a character should be included, False otherwise.
    """
    if character_mode == "always":
        return True
    elif character_mode == "never":
        return False
    else:
        # "random" mode: 40% chance of including a character
        # WHY 40%? Gives a good mix — some videos have the Lofi Girl aesthetic,
        # others are pure landscape. Both styles perform well on YouTube.
        return random.random() < 0.40


def decompose_prompt(
    scene_prompt: str,
    character_mode: str,
    style_suffix: str,
    animation_variations: list,
) -> dict:
    """
    Decompose a scene prompt into structured sub-prompts for the pipeline.

    If ANTHROPIC_API_KEY is set, Claude generates rich custom prompts tailored
    to the specific scene. If no key is set, we fall back to the pre-written
    defaults from config.py — the pipeline runs perfectly, just with the same
    10 animation variations every time instead of scene-specific ones.

    Args:
        scene_prompt:         User's scene description, e.g. "Misty dawn links course"
        character_mode:       "always", "never", or "random"
        style_suffix:         The anime/Ghibli style suffix to append to image prompts
        animation_variations: Default animation variations from config (used as fallback)

    Returns:
        A dict matching the orchestration JSON schema.
    """
    # If no Anthropic API key is configured, skip Claude entirely and use defaults.
    # WHY: All 10 animation variations are already pre-written in config.py.
    # The video quality is identical — Claude just makes them more scene-specific.
    if not config.ANTHROPIC_API_KEY:
        logger.info(
            "  No ANTHROPIC_API_KEY set — using built-in defaults for animation prompts.\n"
            "  (Add a Claude API key to get scene-specific animation descriptions)"
        )
        return _build_fallback_orchestration(scene_prompt, character_mode, style_suffix, animation_variations)

    include_character = _should_include_character(character_mode)
    character_note = ""

    if include_character:
        # Pick a random character option from config
        character_option = random.choice(config.CHARACTER_OPTIONS)
        character_note = (
            f"\n\nCHARACTER: Include a foreground figure in the image prompt. "
            f"Use this description as the base: {character_option}\n"
            "The character must be in the FOREGROUND, with their back turned or side view, "
            "looking out at the course — never facing the camera."
        )

    # Build the user message that we send to Claude
    user_message = f"""Scene description: "{scene_prompt}"
Include character figure: {include_character}{character_note}

Please decompose this into the full orchestration JSON for the Fairway Frequencies pipeline.
The image must have excellent composition for animation — rich foreground, middle ground, and sky."""

    logger.debug(f"  Calling Claude ({config.CLAUDE_MODEL}) for prompt decomposition...")
    logger.debug(f"  Include character: {include_character}")

    # Load the system prompt (from file or inline fallback)
    system_prompt = load_system_prompt()

    # Call the Claude API with retry logic
    orchestration = _call_claude_with_retry(
        system_prompt=system_prompt,
        user_message=user_message,
        stage_name="orchestration",
    )

    # Validate the response has all required fields
    required_fields = [
        "image_prompt", "has_character", "base_video_prompt",
        "animation_variations", "music_prompt", "ambience_keywords",
        "thumbnail_prompt", "mood", "time_of_day", "season"
    ]

    missing = [f for f in required_fields if f not in orchestration]
    if missing:
        raise ValueError(
            f"Claude's orchestration response is missing required fields: {missing}\n"
            "Try running again — this is usually a one-time fluke."
        )

    # Ensure we have exactly NUM_ANIMATION_CLIPS animation variations.
    # Each variation must be an object {"prompt": "...", "negative_prompt": "..."}.
    # If Claude returned strings (old format or schema mismatch), upgrade them.
    target_count = config.NUM_ANIMATION_CLIPS
    variations = orchestration.get("animation_variations", [])

    # Upgrade any plain strings to the object format
    upgraded = []
    for v in variations:
        if isinstance(v, str):
            upgraded.append({
                "prompt": v,
                "negative_prompt": config.DEFAULT_NEGATIVE_PROMPT,
            })
        else:
            upgraded.append(v)
    orchestration["animation_variations"] = upgraded

    if len(orchestration["animation_variations"]) < target_count:
        logger.warning(
            f"  ⚠️ Claude only returned {len(orchestration['animation_variations'])} "
            f"animation variations (expected {target_count}). Padding with defaults from config."
        )
        while len(orchestration["animation_variations"]) < target_count:
            idx = len(orchestration["animation_variations"]) % len(animation_variations)
            orchestration["animation_variations"].append(animation_variations[idx])

    orchestration["animation_variations"] = orchestration["animation_variations"][:target_count]

    logger.debug(f"  Orchestration complete. Mood: {orchestration.get('mood')}, "
                 f"Time: {orchestration.get('time_of_day')}")

    return orchestration


def _build_fallback_orchestration(
    scene_prompt: str,
    character_mode: str,
    style_suffix: str,
    animation_variations: list,
) -> dict:
    """
    Build a complete orchestration dict without calling Claude.

    Used when ANTHROPIC_API_KEY is not set. Uses the pre-written animation
    variations from config.py and infers mood/season from simple keyword
    matching on the scene description.

    Args:
        scene_prompt:         The user's scene description.
        character_mode:       "always", "never", or "random"
        style_suffix:         Anime/Ghibli style suffix from config.
        animation_variations: The 10 pre-written variations from config.

    Returns:
        A complete orchestration dict ready for the rest of the pipeline.
    """
    include_character = _should_include_character(character_mode)
    scene_lower = scene_prompt.lower()

    # Infer mood from keywords in the scene description
    mood = "calm"  # default
    if any(w in scene_lower for w in ["golden", "sunset", "warm", "glow"]):
        mood = "warm"
    elif any(w in scene_lower for w in ["rain", "cozy", "overcast", "grey"]):
        mood = "cozy"
    elif any(w in scene_lower for w in ["storm", "dramatic", "dark", "thunder"]):
        mood = "dramatic"
    elif any(w in scene_lower for w in ["autumn", "fall", "maple", "foliage"]):
        mood = "nostalgic"
    elif any(w in scene_lower for w in ["night", "moon", "star", "midnight"]):
        mood = "dreamy"
    elif any(w in scene_lower for w in ["snow", "winter", "frost", "frozen"]):
        mood = "serene"
    elif any(w in scene_lower for w in ["cherry", "blossom", "spring", "koi"]):
        mood = "peaceful"

    # Infer time of day
    time_of_day = "morning"
    if any(w in scene_lower for w in ["dawn", "sunrise", "early morning"]):
        time_of_day = "dawn"
    elif any(w in scene_lower for w in ["golden hour", "sunset", "dusk"]):
        time_of_day = "golden_hour"
    elif any(w in scene_lower for w in ["night", "moon", "star"]):
        time_of_day = "night"
    elif any(w in scene_lower for w in ["afternoon", "midday", "noon"]):
        time_of_day = "afternoon"

    # Infer season
    season = "summer"
    if any(w in scene_lower for w in ["autumn", "fall", "maple", "foliage", "orange leaves"]):
        season = "autumn"
    elif any(w in scene_lower for w in ["winter", "snow", "frost", "frozen", "holiday"]):
        season = "winter"
    elif any(w in scene_lower for w in ["spring", "cherry", "blossom", "bloom"]):
        season = "spring"

    # Build ambience keywords from scene description words
    ambience_keywords = ["golf course", "birds", "wind"]
    if any(w in scene_lower for w in ["rain", "rainy", "drizzle"]):
        ambience_keywords.append("rain")
    if any(w in scene_lower for w in ["ocean", "sea", "coastal", "waves", "cliff"]):
        ambience_keywords.append("ocean waves")
    if any(w in scene_lower for w in ["tropical", "island", "palm"]):
        ambience_keywords.append("tropical birds")

    # Build the image prompt: scene description + style suffix
    char_desc = ""
    if include_character:
        char_desc = random.choice(config.CHARACTER_OPTIONS) + ", "
    image_prompt = (
        f"{char_desc}Elevated wide view of a {scene_prompt}, {style_suffix}"
    )

    return {
        "image_prompt": image_prompt,
        "has_character": include_character,
        "character_description": char_desc.rstrip(", ") if include_character else "",
        "base_video_prompt": (
            f"Subtle ambient animation of a {scene_prompt}. "
            "Gentle natural motion — clouds drifting, foliage swaying, flag waving softly. "
            "No camera movement. Painterly, Ghibli-inspired atmosphere."
        ),
        "animation_variations": list(animation_variations[:config.NUM_ANIMATION_CLIPS]),
        "music_prompt": f"LoFi hip hop, {mood} mood, {time_of_day} vibes, relaxing, golf course ambience",
        "ambience_keywords": ambience_keywords,
        "thumbnail_prompt": f"Elevated wide view of a {scene_prompt}, vibrant colors, {style_suffix}",
        "mood": mood,
        "time_of_day": time_of_day,
        "season": season,
    }


def _call_claude_with_retry(
    system_prompt: str,
    user_message: str,
    stage_name: str,
    max_tokens: int = 3000,
) -> dict:
    """
    Call the Claude API and parse the JSON response, with retry on failure.

    WHY retry? API calls can fail for many reasons: network hiccups, rate limits,
    temporary server issues. We retry up to MAX_RETRIES times with exponential
    backoff (waiting longer between each retry) to handle transient failures
    without crashing the whole pipeline.

    Args:
        system_prompt: The system prompt (Claude's instructions).
        user_message:  The user message (the specific request).
        stage_name:    Human-readable name for logging (e.g., "orchestration").
        max_tokens:    Maximum tokens Claude can use in its response.

    Returns:
        Parsed JSON response as a Python dict.

    Raises:
        RuntimeError: If all retries are exhausted.
    """
    # Create the Anthropic client — it automatically reads ANTHROPIC_API_KEY
    # from the environment (which we loaded from .env in config.py)
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    last_error = None

    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            logger.debug(f"  Claude API call attempt {attempt}/{config.MAX_RETRIES}")

            # Make the API call
            # WHY these parameters?
            #   model: claude-sonnet-4-6 is fast and highly capable for creative tasks
            #   max_tokens: 3000 is enough for our JSON response (~1000 tokens typical)
            #   temperature: default (1.0) gives creative variety
            response = client.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_message}
                ]
            )

            # Extract the text from Claude's response
            response_text = response.content[0].text.strip()

            # Claude sometimes wraps JSON in markdown code blocks even when
            # told not to. Strip those if present.
            if response_text.startswith("```"):
                # Remove the opening ``` and optional "json" language tag
                lines = response_text.split("\n")
                # Find where the JSON actually starts and ends
                start = 1 if lines[0].startswith("```") else 0
                end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
                response_text = "\n".join(lines[start:end])

            # Parse the JSON string into a Python dictionary
            parsed = json.loads(response_text)
            return parsed

        except json.JSONDecodeError as e:
            # Claude returned something that's not valid JSON
            last_error = e
            logger.warning(
                f"  ⚠️ Claude returned invalid JSON on attempt {attempt}: {e}\n"
                f"  Response was: {response_text[:200]}..."
            )

        except anthropic.RateLimitError as e:
            # We're sending too many requests — wait longer before retrying
            last_error = e
            wait_time = config.RETRY_BASE_DELAY * (2 ** attempt) * 2  # Extra wait for rate limits
            logger.warning(f"  ⚠️ Rate limit hit. Waiting {wait_time}s before retry...")
            time.sleep(wait_time)
            continue

        except anthropic.APIConnectionError as e:
            # Network issue — retry after a delay
            last_error = e
            logger.warning(f"  ⚠️ Network error on attempt {attempt}: {e}")

        except Exception as e:
            # Unexpected error — log it and retry
            last_error = e
            logger.warning(f"  ⚠️ Unexpected error on attempt {attempt}: {e}")

        # Wait before next retry (exponential backoff: 5s, 10s, 20s)
        if attempt < config.MAX_RETRIES:
            wait_time = config.RETRY_BASE_DELAY * (2 ** (attempt - 1))
            logger.info(f"  Retrying in {wait_time}s...")
            time.sleep(wait_time)

    # All retries exhausted
    raise RuntimeError(
        f"Claude API call for '{stage_name}' failed after {config.MAX_RETRIES} attempts.\n"
        f"Last error: {last_error}\n"
        f"Check your ANTHROPIC_API_KEY and internet connection."
    )


# Allow running this module directly for testing:
# python -m pipeline.orchestrator "test scene"
if __name__ == "__main__":
    import sys
    import config as cfg

    # Load the .env file for testing
    from dotenv import load_dotenv
    load_dotenv()

    test_prompt = sys.argv[1] if len(sys.argv) > 1 else "Misty dawn, links-style course, coastal cliffs"

    print(f"\nTesting orchestrator with: \"{test_prompt}\"\n")

    result = decompose_prompt(
        scene_prompt=test_prompt,
        character_mode="random",
        style_suffix=cfg.STYLE_SUFFIX,
        animation_variations=cfg.ANIMATION_VARIATIONS,
    )

    print("✓ Orchestration result:")
    print(json.dumps(result, indent=2))
