# =============================================================================
# server.py — Fairway Frequencies Web Server
# =============================================================================
# PURPOSE:
#   This is the bridge between the browser UI (fairway_control_panel.jsx)
#   and the Python pipeline (fairway.py + all pipeline/ modules).
#
# HOW IT WORKS:
#   1. You run: python server.py
#   2. A local web server starts at http://localhost:5000
#   3. Open that URL in your browser — you see the Fairway Frequencies UI
#   4. The UI calls this server's API endpoints (instead of simulating)
#   5. This server runs your actual Python pipeline in the background
#
# WHY Flask? Flask is the simplest Python web framework. It lets you write
# "if someone visits this URL, run this Python function and return the result"
# in just a few lines. Perfect for local tooling.
#
# USAGE:
#   python server.py
#   Then open: http://localhost:5000
# =============================================================================

import os           # File operations
import sys          # For finding the Python interpreter
import json         # JSON responses
import uuid         # Unique run IDs
import threading    # Background pipeline execution
import subprocess   # Running fairway.py as a subprocess
import glob         # Finding output files
import time         # Timestamps
import re           # Parsing log messages
from datetime import datetime

# Flask — the web server library
# Install with: pip install flask flask-cors
from flask import Flask, request, jsonify, send_from_directory, Response
from flask_cors import CORS  # Allows the browser to call our API

# Load config (reads .env file automatically)
import config

# =============================================================================
# APP SETUP
# =============================================================================

# Set working directory to the project root (where fairway.py lives)
# WHY: All pipeline modules assume they run from the project root
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJECT_ROOT)

# Ensure WinGet-installed tools (ffmpeg, etc.) are on the PATH for subprocesses.
# WinGet installs symlinks to %LOCALAPPDATA%\Microsoft\WinGet\Links, which may
# not be inherited by CREATE_NO_WINDOW subprocesses on a fresh Windows install.
_winget_links = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Links")
if _winget_links and _winget_links not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _winget_links + os.pathsep + os.environ.get("PATH", "")

app = Flask(__name__, static_folder=PROJECT_ROOT)
CORS(app)  # Allow cross-origin requests (needed for browser → localhost API calls)

# =============================================================================
# IN-MEMORY RUN TRACKING
# =============================================================================
# Stores the state of each pipeline run.
# Key: run_id (a unique string like "abc123")
# Value: { status: "running"|"complete"|"failed", logs: [...], run_dir: "..." }
#
# WHY in-memory? This is a local tool. There's no need for a database.
# Runs are only tracked until the server restarts.

runs = {}  # { run_id: { status, logs, run_dir } }
runs_lock = threading.Lock()  # Prevents race conditions when two things write runs at once

# Where to find the Python executable (same Python running this server)
# WHY sys.executable? It guarantees we use the same Python (and same installed packages)
# that's running the server, not some other Python on the system.
PYTHON = sys.executable

# =============================================================================
# STATIC FILE ROUTES
# =============================================================================

@app.route("/")
def index():
    """Serve the main HTML page (which loads the React UI)."""
    return send_from_directory(PROJECT_ROOT, "index.html")


@app.route("/fairway_control_panel.jsx")
def serve_jsx():
    """Serve the React component JSX file. Babel in the browser compiles it."""
    return send_from_directory(PROJECT_ROOT, "fairway_control_panel.jsx",
                               mimetype="text/plain")  # Browser's Babel handles JSX


# =============================================================================
# VIDEO CLIPS API
# =============================================================================

@app.route("/api/kling-clips", methods=["GET"])
def list_video_clip_sets():
    """Return all clip set subfolders found in assets/video_clips/."""
    from pipeline.video_import import list_clip_sets
    sets = list_clip_sets()
    result = []
    for s in sets:
        label = s["name"] if s["name"] else "Root folder"
        result.append({
            "name": s["name"],
            "count": s["count"],
            "label": f"{label} ({s['count']} clip{'s' if s['count'] != 1 else ''})",
        })
    return jsonify({"sets": result})


# =============================================================================
# PROMPT GENERATION API
# =============================================================================

@app.route("/api/generate-prompt", methods=["POST"])
def generate_prompt_api():
    """
    Generate a full orchestrated Midjourney prompt using Claude.

    This is the server-side version of the UI's local prompt generation.
    It calls the orchestrator module which uses Claude to create a richly
    detailed, scene-appropriate prompt with all art style guidelines.

    Request body:
        { scene: "scene description", character: "random|always|never", stylize: 750 }

    Returns:
        JSON: {
            mj_prompt: "the full Midjourney prompt",
            orchestration: { full Claude response },
            error: "..." (if something went wrong)
        }
    """
    data = request.get_json() or {}
    scene = data.get("scene", "").strip()
    character_mode = data.get("character", "random")
    stylize = data.get("stylize", 750)

    if not scene:
        return jsonify({"error": "No scene description provided"}), 400

    # If no Anthropic key is set, build prompts locally without Claude.
    if not config.ANTHROPIC_API_KEY:
        from pipeline.orchestrator import get_current_art_style
        art_style = get_current_art_style()
        image_prompt = f"Elevated wide view of a {scene}, {art_style['style_suffix']}"
        mj_prompt = f"{image_prompt} --ar 16:9 --v 7 --s {stylize}"
        orchestration = {
            "image_prompt": image_prompt,
            "base_video_prompt": f"Slow cinematic motion across {scene}",
            "animation_variations": config.ANIMATION_VARIATIONS[:config.NUM_ANIMATION_CLIPS],
        }
        return jsonify({
            "mj_prompt": mj_prompt,
            "orchestration": orchestration,
            "source": "local",
        })

    try:
        from pipeline.orchestrator import decompose_prompt

        app.logger.info(f"Generating prompts via Claude for: {scene[:50]}...")

        orchestration = decompose_prompt(
            scene_prompt=scene,
            character_mode=character_mode,
            style_suffix=config.STYLE_SUFFIX,
            animation_variations=config.ANIMATION_VARIATIONS,
        )

        mj_prompt = orchestration["image_prompt"] + f" --ar 16:9 --v 7 --s {stylize}"

        return jsonify({
            "mj_prompt": mj_prompt,
            "orchestration": orchestration,
            "source": "claude",
        })

    except Exception as e:
        app.logger.error(f"Prompt generation failed: {e}")
        return jsonify({"error": str(e)}), 500


# =============================================================================
# IMAGE-GROUNDED ANIMATION PROMPTS API
# =============================================================================

@app.route("/api/animation-prompts-from-image", methods=["POST"])
def animation_prompts_from_image_api():
    """
    Generate 3 Kling animation prompts grounded on an uploaded image.

    Use case: user generates an image in Gemini/Flux outside this UI, the
    image diverges from the original text prompt, and they want fresh motion
    prompts that match what's actually in the frame.

    Request:
        multipart/form-data with:
          - image: the file (required)
          - scene_hint: optional flavor string

    Returns:
        { prompts: [str, str, str], visible_elements: [str, ...] }
    """
    if "image" not in request.files:
        return jsonify({"error": "No image file provided"}), 400

    file = request.files["image"]
    if not file.filename:
        return jsonify({"error": "Empty filename"}), 400

    if not config.ANTHROPIC_API_KEY:
        return jsonify({"error": "ANTHROPIC_API_KEY is not set — cannot run vision call"}), 400

    # Save to a temp path so the pipeline module can read it as a regular file
    import tempfile
    ext = os.path.splitext(file.filename)[1].lower() or ".png"
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        return jsonify({"error": f"Unsupported image type: {ext}"}), 400

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        file.save(tmp.name)
        tmp_path = tmp.name

    try:
        from pipeline.animation_from_image import generate_prompts_from_image
        scene_hint = (request.form.get("scene_hint") or "").strip()

        app.logger.info(f"Generating image-grounded animation prompts for {file.filename}")
        result = generate_prompts_from_image(
            image_path=tmp_path,
            api_key=config.ANTHROPIC_API_KEY,
            claude_model=config.CLAUDE_MODEL,
            scene_hint=scene_hint,
        )
        return jsonify(result)
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 400
    except ValueError as e:
        return jsonify({"error": str(e)}), 502
    except Exception as e:
        app.logger.error(f"Image-grounded prompt generation failed: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# =============================================================================
# PIPELINE EXECUTION API
# =============================================================================

@app.route("/api/run-pipeline", methods=["POST"])
def run_pipeline():
    """
    Start the Fairway Frequencies pipeline in a background thread.

    The pipeline runs asynchronously — we return immediately with a run_id,
    and the UI polls /api/pipeline-status/{run_id} for updates.

    WHY async? The pipeline takes 30–60 minutes. We can't hold a browser
    connection open for that long. Instead we:
    1. Start the pipeline in a background thread
    2. Return a run_id to the browser
    3. Browser polls for status every 2 seconds

    Request body:
        {
            scene: "scene description",
            duration: 2,
            no_ambience: false,
            character: "random",
            images: "midjourney"
        }

    Returns:
        JSON: { run_id: "abc123", message: "Pipeline started" }
    """
    data = request.get_json() or {}
    # Use (val or "") pattern instead of get("key", "") because JSON null becomes
    # Python None, and None.strip() would crash Flask with a 500 HTML response.
    scene = (data.get("scene") or "").strip()
    duration = float(data.get("duration") or config.TARGET_DURATION_HOURS)
    no_ambience = bool(data.get("no_ambience") or False)
    upload = bool(data.get("upload") or False)
    ab_test = bool(data.get("ab_test") or False)
    character = data.get("character") or config.INCLUDE_CHARACTER
    clips_folder  = (data.get("clips_folder")   or "").strip()

    if not scene:
        return jsonify({"error": "No scene description provided"}), 400

    # Create a unique ID for this run
    run_id = uuid.uuid4().hex[:8]

    # Initialize run state
    with runs_lock:
        runs[run_id] = {
            "status": "running",
            "logs": [],
            "started_at": datetime.now().isoformat(),
            "scene": scene[:80],
        }

    # Build the fairway.py command
    cmd = [PYTHON, "-X", "utf8", "fairway.py", scene,
           "--duration", str(duration)]

    if clips_folder:
        cmd.extend(["--clips-folder", clips_folder])

    if no_ambience:
        cmd.append("--no-ambience")

    if character != "random":
        cmd.extend(["--character", character])

    if not upload:
        cmd.append("--no-upload")

    if ab_test:
        cmd.append("--ab-test")

    app.logger.info(f"Starting pipeline run {run_id}: {' '.join(cmd[:5])}...")

    # Start the pipeline in a background thread
    thread = threading.Thread(
        target=_execute_pipeline_thread,
        args=(run_id, cmd),
        name=f"Pipeline-{run_id}",
        daemon=True,  # Dies when the server exits (don't leave orphaned processes)
    )
    thread.start()

    return jsonify({
        "run_id": run_id,
        "message": "Pipeline started",
        "command": " ".join(cmd),
    })


def _execute_pipeline_thread(run_id: str, cmd: list):
    """
    Run the fairway.py pipeline as a subprocess and capture its output.

    This runs in a background thread. It:
    1. Launches fairway.py as a child process
    2. Reads its stdout/stderr line by line in real time
    3. Parses each line into a structured log entry
    4. Updates the in-memory runs dict so the UI can poll for updates
    5. Sets the final status (complete or failed)

    Args:
        run_id: The unique ID for this run (used to update runs dict).
        cmd:    The full command to run (list of strings).
    """
    try:
        # Launch the subprocess
        # stdout=PIPE: capture output instead of printing to console
        # stderr=STDOUT: merge stderr into stdout (one stream to read)
        # CREATE_NO_WINDOW: Windows-only flag that prevents a CMD window
        #   from flashing on screen when the subprocess starts.
        #   Without this, every pipeline run pops up a black console window.
        creation_flags = 0
        if sys.platform == "win32":
            creation_flags = subprocess.CREATE_NO_WINDOW

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",  # Don't crash on weird characters
            cwd=PROJECT_ROOT,
            creationflags=creation_flags,
        )

        # Read output line by line as it comes in
        # WHY line by line? We want real-time updates, not wait for the whole process
        for raw_line in process.stdout:
            line = raw_line.rstrip()
            if not line:
                continue

            # Parse the log line into structured data
            log_entry = _parse_log_line(line)

            with runs_lock:
                runs[run_id]["logs"].append(log_entry)

        # Wait for the process to finish and get exit code
        process.wait()

        final_status = "complete" if process.returncode == 0 else "failed"

        with runs_lock:
            runs[run_id]["status"] = final_status
            runs[run_id]["finished_at"] = datetime.now().isoformat()

            # Add a clear final message
            if final_status == "complete":
                runs[run_id]["logs"].append({
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "stage": "11/11",
                    "msg": "Pipeline complete! Check the output/ folder for your video.",
                    "done": True,
                })
            else:
                runs[run_id]["logs"].append({
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "stage": "ERR",
                    "msg": f"Pipeline failed (exit code {process.returncode}). Check logs for details.",
                    "done": False,
                    "error": True,
                })

    except Exception as e:
        app.logger.error(f"Pipeline thread error for run {run_id}: {e}")
        with runs_lock:
            runs[run_id]["status"] = "failed"
            runs[run_id]["logs"].append({
                "time": datetime.now().strftime("%H:%M:%S"),
                "stage": "ERR",
                "msg": f"Fatal error: {e}",
                "done": False,
                "error": True,
            })


def _parse_log_line(line: str) -> dict:
    """
    Parse a fairway.py log line into a structured dict for the UI.

    fairway.py logs look like:
        [14:32:01] [INFO] [Stage 3/11] Generating animation clips...
        [14:32:01] [INFO]   ✓ Clip 1 downloaded

    We extract:
        - time:  "14:32:01"
        - stage: "3/11" (from "[Stage X/11]" if present)
        - msg:   the actual message text
        - done:  True if it's a completion message

    Args:
        line: Raw log line from fairway.py stdout.

    Returns:
        Dict with time, stage, msg, done keys.
    """
    # Default values
    time_str = datetime.now().strftime("%H:%M:%S")
    stage = ""
    msg = line
    done = False

    # Try to extract timestamp: [HH:MM:SS]
    time_match = re.match(r"\[(\d{2}:\d{2}:\d{2})\]", line)
    if time_match:
        time_str = time_match.group(1)
        # Remove the timestamp and log level prefix
        msg = re.sub(r"^\[\d{2}:\d{2}:\d{2}\]\s*\[(?:INFO|DEBUG|WARNING|ERROR)\]\s*", "", line)

    # Try to extract stage: [Stage 3/11]
    stage_match = re.search(r"\[Stage (\d+/\d+)\]", msg)
    if stage_match:
        stage = stage_match.group(1)
        msg = re.sub(r"\[Stage \d+/\d+\]\s*", "", msg).strip()

    # Check if it's a completion or summary message
    done = any(keyword in msg for keyword in [
        "Production Complete", "complete!", "✓ Final", "video is ready",
    ])

    # Clean up the message (remove leading dashes, equal signs used as separators)
    if re.match(r"^[━=─\-]{3,}$", msg.strip()):
        msg = ""  # Skip pure separator lines

    return {
        "time": time_str,
        "stage": stage,
        "msg": msg.strip(),
        "done": done,
    }


@app.route("/api/pipeline-status/<run_id>", methods=["GET"])
def pipeline_status(run_id):
    """
    Return the current status and logs for a pipeline run.

    The UI polls this endpoint every 2 seconds to show real-time progress.

    Args:
        run_id: The run ID returned by /api/run-pipeline.

    Returns:
        JSON: {
            status: "running" | "complete" | "failed",
            logs: [{ time, stage, msg, done }],
            scene: "...",
            started_at: "..."
        }
    """
    with runs_lock:
        if run_id not in runs:
            return jsonify({"error": "Run not found"}), 404
        # Return a copy to avoid race conditions
        run_data = dict(runs[run_id])
        run_data["logs"] = list(run_data["logs"])  # Copy the list too

    return jsonify(run_data)


# =============================================================================
# STATUS / HEALTH CHECK
# =============================================================================

@app.route("/api/status", methods=["GET"])
def api_status():
    """
    Return the server status and which API keys are configured.

    The UI uses this to show a status indicator for each API service.

    Returns:
        JSON: { keys: { anthropic: bool, kling: bool, ... }, ffmpeg: bool }
    """
    import shutil as _shutil

    return jsonify({
        "server": "running",
        "keys": {
            "anthropic": bool(config.ANTHROPIC_API_KEY),
            "bfl": bool(config.BFL_API_KEY),
            "mubert": bool(config.MUBERT_API_KEY),
            "freesound": bool(config.FREESOUND_API_KEY),
        },
        "ffmpeg": bool(_shutil.which("ffmpeg")),
    })


@app.route("/api/output-files", methods=["GET"])
def list_output_files():
    """
    Return a list of completed videos in the output/ folder.

    Returns:
        JSON: { videos: [{ filename, size_gb, date }] }
    """
    output_dir = os.path.join(PROJECT_ROOT, "output")
    os.makedirs(output_dir, exist_ok=True)

    videos = []
    for filepath in glob.glob(os.path.join(output_dir, "*.mp4")):
        filename = os.path.basename(filepath)
        stat = os.stat(filepath)
        videos.append({
            "filename": filename,
            "size_gb": round(stat.st_size / (1024 ** 3), 2),
            "date": datetime.fromtimestamp(stat.st_mtime).strftime("%b %d, %Y %H:%M"),
        })

    videos.sort(key=lambda x: x["date"], reverse=True)
    return jsonify({"videos": videos})


# =============================================================================
# SCENE GENERATION API
# =============================================================================

@app.route("/api/generate-scene", methods=["POST"])
def generate_scene():
    """
    Ask Claude to generate a fresh, seasonal golf scene prompt for this month's art style.

    Returns:
        JSON: { scene: "...", art_style: { name, short, description, accent } }
    """
    try:
        from pipeline.orchestrator import generate_scene_prompt, get_current_art_style
        from pipeline.scene_tracker import load_scene_history

        if not config.ANTHROPIC_API_KEY:
            return jsonify({"error": "ANTHROPIC_API_KEY not set in .env"}), 400

        scene, art_style = generate_scene_prompt(
            api_key=config.ANTHROPIC_API_KEY,
            claude_model=config.CLAUDE_MODEL,
            scene_history=load_scene_history(),
        )

        return jsonify({
            "scene": scene,
            "art_style": {
                "name": art_style["name"],
                "short": art_style["short"],
                "description": art_style["description"],
                "accent": art_style["accent"],
            },
        })

    except Exception as e:
        app.logger.error(f"Scene generation failed: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/current-art-style", methods=["GET"])
def current_art_style():
    """Return the art style active this month (no Claude call needed)."""
    from pipeline.orchestrator import get_current_art_style
    s = get_current_art_style()
    return jsonify({
        "name": s["name"],
        "short": s["short"],
        "description": s["description"],
        "accent": s["accent"],
    })


# =============================================================================
# SCENE HISTORY API
# =============================================================================

@app.route("/api/scene-history", methods=["GET"])
def get_scene_history():
    """
    Return the scene usage history from output/scene_history.json.

    Returns:
        JSON: {
            history: [ { scene_id, scene_name, prompt, used_at } ],
            used_ids: { scene_id: days_ago }
        }
    """
    from pipeline.scene_tracker import load_scene_history, get_used_scene_ids
    return jsonify({
        "history": load_scene_history(),
        "used_ids": get_used_scene_ids(),
    })


# =============================================================================
# ANALYTICS API
# =============================================================================

@app.route("/api/analytics", methods=["GET"])
def get_analytics():
    """
    Fetch a YouTube Analytics report for the channel.

    Pulls last-28-day totals and per-video stats for tracked uploads.
    On first call, opens a browser for OAuth authentication.

    Returns:
        JSON: {
            channel: { views, watch_hours, net_subscribers, ... },
            videos:  [ { title, views, watch_hours, avg_view_pct, likes, url } ],
            period:  "Last 28 days",
            fetched_at: "..."
        }
    """
    try:
        from pipeline.analytics import fetch_analytics

        client_id = config.YOUTUBE_CLIENT_ID
        client_secret = config.YOUTUBE_CLIENT_SECRET

        report = fetch_analytics(client_id, client_secret)
        return jsonify(report)

    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        app.logger.error(f"Analytics fetch failed: {e}")
        return jsonify({"error": str(e)}), 500


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  Fairway Frequencies Control Panel")
    print("  Living Painting Pipeline v3")
    print("=" * 60)
    print(f"\n  Server starting at:  http://localhost:5000")
    print(f"  Project root:        {PROJECT_ROOT}")
    print(f"  Python:              {PYTHON}")
    print(f"  FFmpeg:              {'found' if __import__('shutil').which('ffmpeg') else 'NOT FOUND'}")
    print(f"\n  API Keys configured:")
    print(f"    Anthropic:  {'OK' if config.ANTHROPIC_API_KEY else 'MISSING (prompts use local fallback)'}")
    print(f"    BFL/Flux:   {'OK' if config.BFL_API_KEY else '- (optional)'}")
    print(f"    Mubert:     {'OK' if config.MUBERT_API_KEY else '- (optional)'}")
    print(f"    Freesound:  {'OK' if config.FREESOUND_API_KEY else '- (optional)'}")
    print(f"\n  Video clips folder: {config.VIDEO_CLIPS_DIR}")
    print(f"    (animate in Kling, save .mp4s to a subfolder here)")
    print(f"\n  Open your browser to: http://localhost:5000")
    print("=" * 60 + "\n")

    # Run the Flask server
    # debug=False: don't auto-reload (pipeline threads would get killed on reload)
    # use_reloader=False: same reason
    # threaded=True: handle multiple browser requests at once (polling needs this)
    app.run(
        host="127.0.0.1",  # Only accessible from localhost (security)
        port=5000,
        debug=False,
        use_reloader=False,
        threaded=True,
    )
