# =============================================================================
# pipeline/animation_from_image.py — Vision-grounded Kling animation prompts
# =============================================================================
# PURPOSE:
#   Take an already-generated image (from Gemini, Flux, MJ, etc.) and produce
#   3 Kling animation prompts that reference what's ACTUALLY visible in the
#   frame, not what the original text prompt described. Image generators drift
#   from their prompts (puddles requested, no puddles rendered) — this stage
#   re-grounds the motion plan on the real pixels.
#
# OUTPUT:
#   Three prompt strings in the same "Tripod shot, fixed camera..." format the
#   pipeline already uses, each focused on a different primary motion source
#   (clouds / foliage / light) with a constant flag-pin flutter.
# =============================================================================

import base64
import json
import logging
import os
import anthropic

import config

logger = logging.getLogger("fairway.animation_from_image")


_SYSTEM_PROMPT = """You are an animation director for "Fairway Frequencies", a LoFi Golf YouTube channel that publishes long-form animated golf course paintings. The video pipeline animates a still image into 3 short looping clips using Kling AI.

You will be shown one image — the actual frame that will be animated. Your job is to write THREE Kling animation prompts that reference ONLY what is visible in this image. Do NOT invent elements (no puddles, no birds, no blossoms, no people) unless you can clearly see them in the frame.

PROMPT FORMAT — every prompt MUST follow this template:
"Tripod shot, fixed camera, no zoom, no camera movement. [primary motion description grounded in what is visible]. The flag pin [specific flag motion]. [optional 1-2 secondary subtle motions]. Static background, original composition maintained."

REQUIRED RULES:
1. EVERY prompt must include subtle motion on the golf flag pin — gentle ripple of the flag fabric, soft sway in the breeze, fabric wavering. The flag is NEVER motionless. Vary the flag wording across the 3 prompts (e.g. "flag fluttering softly", "flag fabric rippling in a gentle breeze", "flag pin's fabric swaying slowly").
2. Each prompt has a DIFFERENT primary motion focus. Pick three distinct sources from what's actually visible. Examples of acceptable primary focuses (only use those that are actually in the image):
   - cloud drift / cloud morphing in the sky
   - tree canopy sway / leaf flutter
   - light shifts — golden light moving across the fairway, sun rays through branches
   - water motion (only if water is visible — pond, puddle, ocean, stream)
   - grass / wildflower motion
   - distant figures / cart movement (only if visible)
   - falling petals / leaves (only if blossoms or autumn trees are visible)
3. All motion must be SUBTLE — "breathing painting" not action movie. Use words like: gently, slowly, softly, faintly, imperceptibly, lazily.
4. NO camera motion, NO zoom, NO panning, NO scene changes. The "Tripod shot..." preamble and "Static background, original composition maintained." closer are mandatory.
5. Each prompt is 1-3 sentences total (not counting the preamble/closer).
6. Do NOT mention elements that aren't in the image. If the original text prompt asked for puddles but you don't see puddles, don't write about puddles.

OUTPUT FORMAT — respond with ONLY valid JSON, no markdown, no code fences:
{
  "prompts": [
    "Tripod shot, fixed camera, no zoom, no camera movement. [prompt 1]. Static background, original composition maintained.",
    "Tripod shot, fixed camera, no zoom, no camera movement. [prompt 2]. Static background, original composition maintained.",
    "Tripod shot, fixed camera, no zoom, no camera movement. [prompt 3]. Static background, original composition maintained."
  ],
  "visible_elements": ["short", "list", "of", "key", "elements", "you", "actually", "see"]
}

The visible_elements field is for debugging — list the 5-10 most prominent things in the frame so the user can verify you're grounding on the real image."""


def _read_image_b64(image_path: str) -> tuple[str, str]:
    """Return (media_type, base64_data) for the given image path."""
    ext = os.path.splitext(image_path)[1].lower().lstrip(".")
    media_type = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}.get(ext, "image/png")
    with open(image_path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode("utf-8")
    return media_type, data


def generate_prompts_from_image(
    image_path: str,
    api_key: str = None,
    claude_model: str = None,
    scene_hint: str = "",
) -> dict:
    """
    Generate 3 Kling animation prompts grounded on a real image.

    Args:
        image_path:   Local filesystem path to the image to ground on.
        api_key:      Anthropic API key. Defaults to config.ANTHROPIC_API_KEY.
        claude_model: Claude model id. Defaults to config.CLAUDE_MODEL.
        scene_hint:   Optional one-line description of mood/time-of-day. Used
                      only as flavor — the image is the source of truth.

    Returns:
        {
          "prompts": [str, str, str],
          "visible_elements": [str, ...],
        }

    Raises:
        FileNotFoundError, ValueError, anthropic.APIError on failure. Caller
        is responsible for handling these and reporting to the UI.
    """
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")

    api_key = api_key or config.ANTHROPIC_API_KEY
    claude_model = claude_model or config.CLAUDE_MODEL
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is not configured")

    media_type, image_b64 = _read_image_b64(image_path)

    user_text = (
        "Look at the attached image carefully. List what you actually see, then write "
        "3 distinct Kling animation prompts grounded only on visible elements. "
        "Every prompt must include subtle flag-pin motion. Return ONLY the JSON object."
    )
    if scene_hint:
        user_text += f"\n\nScene hint (use only as supplementary context): {scene_hint}"

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=claude_model,
        max_tokens=1500,
        system=[{
            "type": "text",
            "text": _SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": image_b64},
                },
                {"type": "text", "text": user_text},
            ],
        }],
    )

    text = response.content[0].text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        end = len(lines) - 1 if lines[-1].strip().startswith("```") else len(lines)
        text = "\n".join(lines[1:end])

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Claude returned non-JSON response: {e}\n---\n{text[:500]}")

    prompts = data.get("prompts") or []
    if not isinstance(prompts, list) or len(prompts) < 3:
        raise ValueError(f"Expected 3 prompts, got {len(prompts) if isinstance(prompts, list) else 0}")

    return {
        "prompts": [str(p).strip() for p in prompts[:3]],
        "visible_elements": data.get("visible_elements") or [],
    }
