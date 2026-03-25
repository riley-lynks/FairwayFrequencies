// =============================================================================
// fairway_control_panel.jsx — Fairway Frequencies Control Panel
// =============================================================================
// WHY NO "import" STATEMENTS?
//   This file is loaded by index.html with type="text/babel" (Babel Standalone).
//   In that mode, React is already available as a global window variable —
//   loaded via <script src="https://unpkg.com/react@18/umd/..."> in index.html.
//   ES module `import` syntax doesn't work in this browser-compiled mode,
//   so instead we destructure what we need directly from the React global.
// =============================================================================

const { useState, useCallback, useRef, useEffect } = React;

// =============================================================================
// DATA — Scene library, style constants, character options
// =============================================================================

// All 20 scenes match the scene_library.json used by the Python pipeline.
// The scene `id` values are passed to `python fairway.py --scene <id>`
const SCENE_LIBRARY = [
  { id: "misty_dawn_links",     name: "Misty Dawn Links",       desc: "Scottish links course, ocean, gentle fog",           mood: "calm"       },
  { id: "golden_hour_masters",  name: "Golden Hour Masters",    desc: "Augusta-style, pink azaleas, golden light",          mood: "warm"       },
  { id: "rainy_afternoon",      name: "Rainy Afternoon",        desc: "Lush parkland, gentle rain, cozy overcast",          mood: "cozy"       },
  { id: "desert_sunrise",       name: "Desert Sunrise",         desc: "Desert course, cacti silhouettes, pink sky",         mood: "dramatic"   },
  { id: "autumn_new_england",   name: "Autumn New England",     desc: "Peak fall foliage, red maples, stone bridge",        mood: "nostalgic"  },
  { id: "tropical_paradise",    name: "Tropical Paradise",      desc: "Island course, palm trees, turquoise ocean",         mood: "bright"     },
  { id: "moonlit_fairway",      name: "Moonlit Fairway",        desc: "Starry sky, blue mist, glowing moonlight",           mood: "dreamy"     },
  { id: "winter_frost",         name: "Winter Frost",           desc: "Frost-covered, bare trees, frozen pond",             mood: "serene"     },
  { id: "cherry_blossom_japan", name: "Cherry Blossom Japan",   desc: "Cherry trees, floating petals, koi pond",            mood: "peaceful"   },
  { id: "coastal_cliffs_sunset",name: "Coastal Cliffs Sunset",  desc: "Clifftop, Pacific ocean, dramatic clouds",           mood: "epic"       },
  { id: "english_countryside",  name: "English Countryside",    desc: "Rolling hills, stone walls, sheep in distance",      mood: "charming"   },
  { id: "mountain_alpine",      name: "Mountain Alpine",        desc: "Snow-capped peaks, wildflower meadows",              mood: "majestic"   },
  { id: "foggy_practice_range", name: "Foggy Practice Range",   desc: "Driving range at dawn, flag pins in mist",           mood: "meditative" },
  { id: "storm_approaching",    name: "Storm Approaching",      desc: "Dark clouds, dramatic pre-storm golden light",       mood: "moody"      },
  { id: "lakeside_reflection",  name: "Lakeside Reflection",    desc: "Mirror-still lake, perfect reflection, sunrise",     mood: "tranquil"   },
  { id: "vintage_clubhouse",    name: "Vintage Clubhouse",      desc: "Veranda view, warm afternoon, flowers",              mood: "retro"      },
  { id: "snowy_holiday",        name: "Snowy Holiday",          desc: "Light snow, warm clubhouse lights, peaceful",        mood: "festive"    },
  { id: "summer_afternoon",     name: "Summer Afternoon",       desc: "Bright day, puffy clouds, sprinkler rainbows",       mood: "cheerful"   },
  { id: "hawaiian_volcanic",    name: "Hawaiian Volcanic",      desc: "Volcanic rock, tropical flowers, ocean breeze",      mood: "exotic"     },
  { id: "morning_dew_closeup",  name: "Morning Dew Closeup",   desc: "Intimate green view, heavy dew, spider web",         mood: "intimate"   },
];

// Short style suffix appended to MJ prompts — matches STYLE_SUFFIX in config.py
const STYLE_SUFFIX = `in the style of a detailed anime background painting, Studio Ghibli inspired, vibrant saturated colors, clean linework, lush detailed landscape, warm natural lighting, soft puffy clouds, visible brushstroke texture, concept art quality, 16:9 widescreen composition, no text, no UI elements`;

// Character poses — added to prompts ~40% of the time (matches config.py CHARACTER_POSES)
const CHARACTER_OPTIONS = [
  "a golfer sitting on a wooden bench at the edge of the green, back turned to viewer, looking out over the course, golf bag leaning against the bench",
  "a person sitting in a golf cart under a tree, side view, peacefully watching the course",
  "a caddy leaning against a golf bag under a large oak tree, reading a book, facing away from viewer",
  "a figure sitting in the grass near the green, knees up, looking out at the fairway stretching into the distance",
];

// Negative prompt — identical for every Kling clip. Sent to Kling's separate
// "Negative Prompt" field to actively suppress camera movement.
const DEFAULT_NEGATIVE_PROMPT =
  "camera shake, camera movement, camera pan, camera tilt, zoom, " +
  "tracking shot, dolly, handheld, shaky cam, motion blur, scene change";

// Default animation variation prompts — mirrors config.py ANIMATION_VARIATIONS.
// Each entry is { prompt, negative_prompt }. Used as a fallback when the server
// is unavailable. When Claude is running, the server returns scene-specific variations.
const ANIMATION_VARIATIONS = [
  { prompt: "Tripod shot, fixed camera, no zoom, no camera movement. Flag waving softly in light breeze, grass swaying gently, soft ripples on water surface, flowers with subtle movement. Static background, original composition maintained.", negative_prompt: DEFAULT_NEGATIVE_PROMPT },
  { prompt: "Tripod shot, fixed camera, no zoom, no camera movement. Mostly still scene, single bird flying slowly across distant sky, very subtle atmospheric shimmer. Static background, original composition maintained.", negative_prompt: DEFAULT_NEGATIVE_PROMPT },
  { prompt: "Tripod shot, fixed camera, no zoom, no camera movement. Soft breeze through foliage, trees with gentle leaf flutter, flower petals drifting slowly through air. Static background, original composition maintained.", negative_prompt: DEFAULT_NEGATIVE_PROMPT },
  { prompt: "Tripod shot, fixed camera, no zoom, no camera movement. Calm peaceful scene, water with gentle ripple animation, flag waving steadily, barely perceptible light shift. Static background, original composition maintained.", negative_prompt: DEFAULT_NEGATIVE_PROMPT },
  { prompt: "Tripod shot, fixed camera, no zoom, no camera movement. Subtle breeze animation, grass rippling softly, leaves on trees shifting gently, small butterfly floating through foreground. Static background, original composition maintained.", negative_prompt: DEFAULT_NEGATIVE_PROMPT },
  { prompt: "Tripod shot, fixed camera, no zoom, no camera movement. Very gentle overall scene breathing, soft atmospheric movement, flag gently waving, flowers swaying slightly. Static background, original composition maintained.", negative_prompt: DEFAULT_NEGATIVE_PROMPT },
];

// Dot colors for the scene mood badges
const MOOD_COLORS = {
  calm: "#7CB9A8", warm: "#E8A87C", cozy: "#C49B66", dramatic: "#D4726A",
  nostalgic: "#C97B4B", bright: "#7EC8A0", dreamy: "#9B8EC4", serene: "#A3C4D9",
  peaceful: "#E8B4C8", epic: "#D4876A", charming: "#8AB87F", majestic: "#7A9EC4",
  meditative: "#9CAAB5", moody: "#8A7F9E", tranquil: "#7CBCB5", retro: "#C4A06A",
  festive: "#B8585E", cheerful: "#E8C44A", exotic: "#C47A8A", intimate: "#7AAF7A",
};

// =============================================================================
// SEASON / HOLIDAY SCENE PICKER
// =============================================================================
// Returns { desc, label } based on today's date.
// Holidays take priority over seasons. All descriptions are golf-course themed
// so they work with the Midjourney + Kling prompts downstream.
function getCurrentSeasonScene() {
  const now = new Date();
  const m = now.getMonth() + 1; // 1–12
  const d = now.getDate();

  // ── Holidays (checked first — more specific than seasons) ──────────────────
  if (m === 12 && d >= 20)
    return { desc: "Golf course lightly dusted with snow, warm clubhouse windows glowing amber, Christmas wreaths on the fence posts, peaceful silent night", label: "Christmas" };
  if (m === 1 && d <= 7)
    return { desc: "New Year's morning golf course, frost on the fairways, champagne sunrise painting the sky pink and gold, crisp hopeful winter air", label: "New Year's" };
  if (m === 2 && d >= 10 && d <= 14)
    return { desc: "Valentine's Day golf course, rose bushes in full bloom along the cart path, warm pink and amber sunset over the fairway, romantic twilight", label: "Valentine's Day" };
  if (m === 3 && d >= 14 && d <= 17)
    return { desc: "St. Patrick's Day golf course, impossibly lush green fairways, shamrocks dotting the rough, Celtic morning mist rolling over the hills", label: "St. Patrick's Day" };
  if (m === 4 && d >= 7 && d <= 13)
    return { desc: "Masters Week Augusta-style golf course at peak azalea bloom, pink and white flowers lining the fairway, dappled golden Georgia afternoon light", label: "Masters Week" };
  if (m === 7 && d >= 3 && d <= 5)
    return { desc: "Fourth of July golf course, patriotic red white and blue pin flags, warm summer evening, distant fireworks beginning to glow over the treeline", label: "4th of July" };
  if (m === 10 && d >= 25)
    return { desc: "Halloween golf course at twilight, carved jack-o-lanterns lining the path, swirling autumn leaves, spooky warm glow from the old clubhouse", label: "Halloween" };
  if (m === 11 && d >= 21 && d <= 30)
    return { desc: "Thanksgiving golf course, harvest golden afternoon light, autumn leaves in amber and rust, peaceful gratitude, empty fairways in the holiday hush", label: "Thanksgiving" };

  // ── Seasons ────────────────────────────────────────────────────────────────
  // Spring: Mar 20 – Jun 20
  if ((m === 3 && d >= 20) || m === 4 || m === 5 || (m === 6 && d <= 20))
    return { desc: "Spring golf course in full bloom, cherry blossom petals drifting across fresh green fairways, morning dew on the grass, warm golden sunrise light", label: "Spring" };
  // Summer: Jun 21 – Sep 22
  if ((m === 6 && d >= 21) || m === 7 || m === 8 || (m === 9 && d <= 22))
    return { desc: "Midsummer golf course, brilliant blue sky, tall puffy cumulus clouds, sprinklers catching rainbow light across lush peak-green fairways", label: "Summer" };
  // Fall: Sep 23 – Dec 19
  if ((m === 9 && d >= 23) || m === 10 || m === 11 || (m === 12 && d <= 19))
    return { desc: "Autumn golf course at peak foliage, red and orange maples lining the fairway, crisp golden morning light filtering through the leaves, still misty air", label: "Autumn" };
  // Winter: Dec 21 – Mar 19
  return { desc: "Winter golf course, frost-tipped fairways catching the pale sunrise, bare trees with ice crystals glinting, serene silence, soft grey-blue sky", label: "Winter" };
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

function FairwayControlPanel() {
  // ---------------------------------------------------------------------------
  // STATE
  // ---------------------------------------------------------------------------
  const [tab, setTab] = useState("create");
  const [prompt, setPrompt] = useState("");
  const [selectedScene, setSelectedScene] = useState(null);
  const [includeCharacter, setIncludeCharacter] = useState("random");
  const [includeAmbience, setIncludeAmbience] = useState(true);
  const [duration, setDuration] = useState(2);
  const [stylize, setStylize] = useState(750);
  const [generatedPrompt, setGeneratedPrompt] = useState("");
  const [uploadedImages, setUploadedImages] = useState([]);
  const [selectedImage, setSelectedImage] = useState(null); // filename of the chosen base image
  const [pipelineLog, setPipelineLog] = useState([]);
  const [pipelineRunning, setPipelineRunning] = useState(false);
  const [pipelineStatus, setPipelineStatus] = useState(null); // "running" | "complete" | "error"
  const [copied, setCopied] = useState(false);
  const [klingPrompts, setKlingPrompts] = useState([]);   // 6 Kling animation prompts
  const [promptsLoading, setPromptsLoading] = useState(false); // waiting for server
  const [copiedKling, setCopiedKling] = useState(null);        // index | "all" | null
  const [klingNegativePrompt, setKlingNegativePrompt] = useState(""); // negative prompt (same for all clips)
  const [copiedNegative, setCopiedNegative] = useState(false);        // for the negative prompt copy btn
  const [promptSource, setPromptSource] = useState(null);             // "claude" | "local"
  const [uploadError, setUploadError] = useState(null);
  const [klingClipSets, setKlingClipSets] = useState([]);       // available clip sets
  const [selectedClipSet, setSelectedClipSet] = useState(null); // chosen folder name ("" = root)
  // Which AI tool the user will paste the image prompt into
  // "chatgpt" = DALL·E 3 via ChatGPT | "kling" = Kling Image Gen | "midjourney" = Midjourney
  const [imageGenTool, setImageGenTool] = useState("chatgpt");

  // Refs
  const fileInputRef = useRef(null);
  const pollingRef = useRef(null);   // stores the setInterval ID for pipeline polling
  const logEndRef = useRef(null);    // for auto-scrolling the log to the bottom

  // ---------------------------------------------------------------------------
  // refreshImages — fetch the authoritative image list from the server
  // ---------------------------------------------------------------------------
  // WHY a shared function instead of inline fetch?
  //   We need to load images in two places: on mount (to show existing files)
  //   and after every upload (to reflect what's actually on disk).
  //   Using one function both places means the UI always shows exactly what
  //   the server has — no duplicates, no stale entries, no guessing.
  const refreshImages = useCallback(() => {
    fetch('/api/images')
      .then(r => r.json())
      .then(data => {
        const images = (data.images || []).map(img => ({
          name: img.filename,
          src: `/api/images/preview/${encodeURIComponent(img.filename)}`,
          date: img.date,
          size: img.size_mb + " MB",
        }));
        setUploadedImages(images);

        // If the currently selected image was deleted from disk, clear the selection
        setSelectedImage(prev =>
          prev && images.some(img => img.name === prev) ? prev : null
        );
      })
      .catch(() => {
        // Server not running yet — fine, images stay empty
      });
  }, []);

  // Load images on mount
  useEffect(() => { refreshImages(); }, [refreshImages]);

  // ---------------------------------------------------------------------------
  // refreshClipSets — fetch the list of named clip set folders from the server
  // ---------------------------------------------------------------------------
  const refreshClipSets = useCallback(() => {
    fetch('/api/kling-clips')
      .then(r => r.json())
      .then(data => {
        const sets = data.sets || [];
        setKlingClipSets(sets);
        // Auto-select the first set if nothing is selected yet
        setSelectedClipSet(prev => {
          if (prev !== null) return prev;           // keep current selection
          if (sets.length > 0) return sets[0].name; // default to first (newest)
          return null;
        });
      })
      .catch(() => { /* server not running yet — fine */ });
  }, []);

  // Load clip sets on mount and whenever the pipeline tab is opened
  useEffect(() => { refreshClipSets(); }, [refreshClipSets]);
  useEffect(() => { if (tab === "pipeline") refreshClipSets(); }, [tab, refreshClipSets]);

  // Auto-scroll the pipeline log to the latest entry whenever a new line arrives
  useEffect(() => {
    if (logEndRef.current) {
      logEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [pipelineLog]);

  // Clean up the polling interval if the component unmounts mid-run
  useEffect(() => {
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, []);

  // ---------------------------------------------------------------------------
  // GENERATE ALL PROMPTS — Midjourney (image) + Kling (6 animation clips)
  // ---------------------------------------------------------------------------
  // HOW IT WORKS:
  //   1. POST /api/generate-prompt → server uses Claude (if key set) or local
  //      fallback to build a full orchestration object
  //   2. Response gives us: image_prompt (Midjourney) + base_video_prompt +
  //      animation_variations (6 Kling clip prompts)
  //   3. If the server is unreachable, fall back entirely to local generation
  // ---------------------------------------------------------------------------
  // formatImagePrompt — wraps a raw scene prompt for the selected image tool
  // ---------------------------------------------------------------------------
  // raw:    the clean scene description returned by Claude / local fallback
  // tool:   "chatgpt" | "kling" | "midjourney"
  // sVal:   stylize value (only used for midjourney)
  const formatImagePrompt = useCallback((raw, tool, sVal) => {
    if (tool === "chatgpt") {
      return (
        `Create a 16:9 widescreen digital illustration: ${raw}. ` +
        `Art style: detailed anime background painting, Studio Ghibli inspired, ` +
        `vibrant saturated colors, clean linework, lush detailed landscape, ` +
        `warm natural lighting, soft puffy clouds, visible brushstroke texture, ` +
        `concept art quality. No text, no logos, no UI elements, no watermarks.`
      );
    }
    if (tool === "kling") {
      return (
        `${raw}, ` +
        `anime background painting style, Studio Ghibli inspired, vibrant saturated colors, ` +
        `clean linework, warm natural lighting, soft puffy clouds, ` +
        `16:9 widescreen landscape composition, concept art quality, no text, no UI elements`
      );
    }
    // midjourney (default)
    return `${raw} --ar 16:9 --v 7 --s ${sVal}`;
  }, []);

  const generateMJPrompt = useCallback(async (overrideDesc = null) => {
    const sceneDesc = overrideDesc || prompt || (selectedScene
      ? SCENE_LIBRARY.find(s => s.id === selectedScene)?.desc
      : "");
    if (!sceneDesc) return;

    setPromptsLoading(true);
    setKlingPrompts([]);
    setKlingNegativePrompt("");
    setGeneratedPrompt("");
    setPromptSource(null);

    let imagePrompt = "";
    let klingPromptsArr = [];
    let source = "local";

    try {
      const res = await fetch('/api/generate-prompt', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scene: sceneDesc, character: includeCharacter, stylize }),
      });

      if (!res.ok) throw new Error(`Server returned ${res.status}`);

      const data = await res.json();
      if (data.error) throw new Error(data.error);

      source = data.source || "claude";

      // Use the raw image_prompt from orchestration so we can format it
      // for whichever tool is selected (ChatGPT / Kling / Midjourney).
      const orch = data.orchestration || {};
      const rawPrompt = orch.image_prompt || data.mj_prompt || `Elevated wide view of a ${sceneDesc}, ${STYLE_SUFFIX}`;
      imagePrompt = formatImagePrompt(rawPrompt, imageGenTool, stylize);

      // Animation variations are now objects { prompt, negative_prompt }.
      // Extract the positive prompts for display; the negative prompt is shared.
      const variations = orch.animation_variations || ANIMATION_VARIATIONS;
      klingPromptsArr = variations.slice(0, 6).map(v =>
        typeof v === 'object' ? v.prompt : v
      );
      // Negative prompt is the same for every clip — grab from first entry
      const negPrompt = (variations[0] && typeof variations[0] === 'object')
        ? (variations[0].negative_prompt || DEFAULT_NEGATIVE_PROMPT)
        : DEFAULT_NEGATIVE_PROMPT;
      setKlingNegativePrompt(negPrompt);

    } catch (err) {
      // Server unreachable — build everything locally
      let charDesc = "";
      if (includeCharacter === "always") {
        charDesc = CHARACTER_OPTIONS[Math.floor(Math.random() * CHARACTER_OPTIONS.length)] + ", ";
      } else if (includeCharacter === "random" && Math.random() < 0.4) {
        charDesc = CHARACTER_OPTIONS[Math.floor(Math.random() * CHARACTER_OPTIONS.length)] + ", ";
      }
      const rawLocal = `${charDesc}Elevated wide view of a ${sceneDesc}, ${STYLE_SUFFIX}`;
      imagePrompt = formatImagePrompt(rawLocal, imageGenTool, stylize);
      klingPromptsArr = ANIMATION_VARIATIONS.map(v =>
        typeof v === 'object' ? v.prompt : `${sceneDesc}. ${v}`
      );
      setKlingNegativePrompt(DEFAULT_NEGATIVE_PROMPT);
      source = "local";
    }

    setGeneratedPrompt(imagePrompt);
    setKlingPrompts(klingPromptsArr);
    setPromptSource(source);
    setPromptsLoading(false);
  }, [prompt, selectedScene, includeCharacter, stylize, imageGenTool, formatImagePrompt]);

  const copyPrompt = useCallback(() => {
    navigator.clipboard.writeText(generatedPrompt);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [generatedPrompt]);

  // Copy a single Kling prompt (by index) or all of them at once
  const copyKlingPrompt = useCallback((idx) => {
    navigator.clipboard.writeText(klingPrompts[idx]);
    setCopiedKling(idx);
    setTimeout(() => setCopiedKling(null), 2000);
  }, [klingPrompts]);

  const copyAllKlingPrompts = useCallback(() => {
    const text = klingPrompts.map((p, i) => `Clip ${i + 1}:\n${p}`).join('\n\n');
    navigator.clipboard.writeText(text);
    setCopiedKling('all');
    setTimeout(() => setCopiedKling(null), 2000);
  }, [klingPrompts]);

  const copyNegativePrompt = useCallback(() => {
    navigator.clipboard.writeText(klingNegativePrompt || DEFAULT_NEGATIVE_PROMPT);
    setCopiedNegative(true);
    setTimeout(() => setCopiedNegative(false), 2000);
  }, [klingNegativePrompt]);

  // ---------------------------------------------------------------------------
  // QUICK SCENE PICKERS — Random Scene + Today's Scene (season/holiday aware)
  // ---------------------------------------------------------------------------
  // Both buttons set the scene state then immediately generate prompts so the
  // user gets results in one click instead of two.
  const handleRandomScene = useCallback(async () => {
    const pick = SCENE_LIBRARY[Math.floor(Math.random() * SCENE_LIBRARY.length)];
    setSelectedScene(pick.id);
    setPrompt("");
    await generateMJPrompt(pick.desc);
  }, [generateMJPrompt]);

  const handleSeasonScene = useCallback(async () => {
    const { desc } = getCurrentSeasonScene();
    setPrompt(desc);
    setSelectedScene(null);
    await generateMJPrompt(desc);
  }, [generateMJPrompt]);

  // Pre-compute the season/holiday label for the button text (no date logic at render time)
  const todaySceneLabel = getCurrentSeasonScene().label;

  // ---------------------------------------------------------------------------
  // UPLOAD IMAGE — POST to server, which saves to assets/midjourney_images/
  // ---------------------------------------------------------------------------
  // WHY real upload instead of base64-in-state:
  //   The pipeline Python script reads images from disk. We need the file to
  //   actually be saved on the server before we can run the pipeline.
  const handleImageUpload = useCallback(async (e) => {
    const files = Array.from(e.target.files);
    setUploadError(null);

    for (const file of files) {
      const formData = new FormData();
      formData.append('image', file);

      try {
        const res = await fetch('/api/upload-image', {
          method: 'POST',
          body: formData,
        });
        const data = await res.json();
        if (!data.success) {
          setUploadError(data.error || 'Upload failed');
        }
      } catch (err) {
        setUploadError(`Upload failed: ${err.message}. Is the server running?`);
      }
    }

    // Refetch the full list from the server instead of manually appending.
    // WHY: The server is the source of truth. This prevents duplicates when
    // files are added directly to the folder AND via the UI drop zone.
    refreshImages();
    e.target.value = '';
  }, [refreshImages]);

  // ---------------------------------------------------------------------------
  // REMOVE IMAGE — DELETE from server disk + remove from UI state
  // ---------------------------------------------------------------------------
  const removeImage = useCallback(async (idx) => {
    const img = uploadedImages[idx];

    try {
      await fetch(`/api/images/${encodeURIComponent(img.name)}`, {
        method: 'DELETE',
      });
    } catch (err) {
      console.error('Delete failed:', err);
    }

    // Refetch from server so UI exactly matches disk
    // (refreshImages also clears selectedImage if that file is now gone)
    refreshImages();
  }, [uploadedImages, refreshImages]);

  // ---------------------------------------------------------------------------
  // RUN PIPELINE — POST to server, then poll for real-time log updates
  // ---------------------------------------------------------------------------
  // HOW IT WORKS:
  //   1. POST /api/run-pipeline → server spawns `python fairway.py` as a subprocess
  //      and returns a `run_id` (timestamp string like "20240315_143022")
  //   2. Every 2 seconds, GET /api/pipeline-status/<run_id> → server returns
  //      accumulated log lines + current status ("running" | "complete" | "error")
  //   3. When status is "complete" or "error", stop polling
  const runPipeline = useCallback(async () => {
    if (uploadedImages.length === 0 || pipelineRunning) return;

    setPipelineRunning(true);
    setPipelineStatus("running");
    setPipelineLog([]);

    // Build the arguments to pass to fairway.py.
    const args = {
      duration: duration,
      no_ambience: !includeAmbience,
      character: includeCharacter,
      scene: selectedScene || prompt,
      image_filename: selectedImage,     // tells the pipeline exactly which image to use
      clips_folder: selectedClipSet,     // which kling_clips subfolder to use
    };

    let runId = null;

    try {
      const res = await fetch('/api/run-pipeline', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(args),
      });
      const data = await res.json();

      if (!data.run_id) {
        throw new Error(data.error || 'Server did not return a run ID');
      }

      runId = data.run_id;
    } catch (err) {
      setPipelineLog([{
        time: new Date().toLocaleTimeString(),
        stage: "—",
        msg: `Failed to start pipeline: ${err.message}`,
        error: true,
      }]);
      setPipelineRunning(false);
      setPipelineStatus("error");
      return;
    }

    // Start polling every 2 seconds.
    // Server returns: { status: "running"|"complete"|"failed", logs: [{ time, stage, msg, done, error }] }
    pollingRef.current = setInterval(async () => {
      try {
        const statusRes = await fetch(`/api/pipeline-status/${runId}`);
        const status = await statusRes.json();

        // Map server log entries to display format.
        // Server uses "logs" (not "log"), "time" (not "timestamp"), "msg" (not "message")
        if (status.logs && status.logs.length > 0) {
          setPipelineLog(status.logs.map(entry => ({
            time: entry.time || new Date().toLocaleTimeString(),
            // Server sends stage like "3/11" — we prefix with "Stage "
            stage: entry.stage ? `Stage ${entry.stage}` : "—",
            msg: entry.msg,
            done: entry.done || false,
            error: entry.error || false,
          })));
        }

        // Stop polling when pipeline finishes or errors out.
        // Server uses "failed" for errors (not "error")
        if (status.status === 'complete' || status.status === 'failed') {
          clearInterval(pollingRef.current);
          pollingRef.current = null;
          setPipelineRunning(false);
          // Normalize "failed" → "error" for the UI banner
          setPipelineStatus(status.status === 'failed' ? 'error' : 'complete');
        }
      } catch (err) {
        // Network hiccup — keep polling, don't stop yet
        console.error('Polling error:', err);
      }
    }, 2000);

  }, [uploadedImages, pipelineRunning, selectedScene, prompt, duration, includeAmbience, includeCharacter]);

  // ---------------------------------------------------------------------------
  // BUILD COMMAND PREVIEW (shown in the dark box on the Run tab)
  // ---------------------------------------------------------------------------
  const commandPreview = (() => {
    const parts = ['python -X utf8 fairway.py'];
    if (selectedScene) parts.push(`--scene ${selectedScene}`);
    else if (prompt) parts.push(`"${prompt}"`);
    parts.push(`--duration ${duration}`);
    if (selectedImage) parts.push(`--image "${selectedImage}"`);
    if (selectedClipSet != null) parts.push(`--clips-folder "${selectedClipSet || '(root)'}"`);
    if (!includeAmbience) parts.push('--no-ambience');
    if (includeCharacter !== 'random') parts.push(`--character ${includeCharacter}`);
    return parts.join(' ');
  })();

  // ---------------------------------------------------------------------------
  // RENDER
  // ---------------------------------------------------------------------------
  return (
    <div style={{ fontFamily: "'DM Sans', 'Avenir', sans-serif", maxWidth: 900, margin: "0 auto", color: "var(--color-text-primary)" }}>
      {/* Google Fonts are already loaded by index.html — this link is a safety fallback */}
      <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=DM+Serif+Display&display=swap" rel="stylesheet" />

      {/* ------------------------------------------------------------------ */}
      {/* HEADER                                                              */}
      {/* ------------------------------------------------------------------ */}
      <div style={{ textAlign: "center", padding: "32px 0 24px", borderBottom: "2px solid #2D6A4F" }}>
        <div style={{ fontSize: 13, letterSpacing: 3, color: "#B08D57", fontWeight: 600, marginBottom: 6 }}>FAIRWAY FREQUENCIES</div>
        <div style={{ fontFamily: "'DM Serif Display', serif", fontSize: 28, color: "#1B4332", fontWeight: 400 }}>Control Panel</div>
        <div style={{ fontSize: 13, color: "var(--color-text-secondary)", marginTop: 6 }}>LoFi Golf · Living Painting Pipeline</div>
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* TAB BAR                                                             */}
      {/* ------------------------------------------------------------------ */}
      <div style={{ display: "flex", borderBottom: "1px solid var(--color-border-tertiary)", marginTop: 20 }}>
        {[
          { id: "create",   label: "Create & Prompt" },
          { id: "upload",   label: "Upload Images" },
          { id: "pipeline", label: "Run Pipeline" },
        ].map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} style={{
            flex: 1, padding: "12px 0", fontSize: 14, fontWeight: tab === t.id ? 600 : 400,
            background: "none", border: "none", cursor: "pointer",
            color: tab === t.id ? "#2D6A4F" : "var(--color-text-secondary)",
            borderBottom: tab === t.id ? "2px solid #2D6A4F" : "2px solid transparent",
            transition: "all 0.2s", fontFamily: "inherit"
          }}>{t.label}</button>
        ))}
      </div>

      {/* ================================================================== */}
      {/* TAB: CREATE & PROMPT                                                */}
      {/* ================================================================== */}
      {tab === "create" && (
        <div style={{ padding: "24px 0" }}>

          {/* ── Quick Start row ─────────────────────────────────────────── */}
          <div style={{ display: "flex", gap: 10, marginBottom: 24 }}>
            <button
              onClick={handleRandomScene}
              disabled={promptsLoading}
              style={{
                flex: 1, padding: "11px 0", fontSize: 13, fontWeight: 600,
                borderRadius: 8, border: "1px solid #2D6A4F", cursor: promptsLoading ? "not-allowed" : "pointer",
                background: "var(--color-background-secondary)", color: "#2D6A4F",
                fontFamily: "inherit", transition: "all 0.2s", letterSpacing: 0.2,
              }}
            >
              🎲 Random Scene
            </button>
            <button
              onClick={handleSeasonScene}
              disabled={promptsLoading}
              style={{
                flex: 1, padding: "11px 0", fontSize: 13, fontWeight: 600,
                borderRadius: 8, border: "1px solid #B08D57", cursor: promptsLoading ? "not-allowed" : "pointer",
                background: "var(--color-background-secondary)", color: "#B08D57",
                fontFamily: "inherit", transition: "all 0.2s", letterSpacing: 0.2,
              }}
            >
              🗓️ Today's Scene — {todaySceneLabel}
            </button>
          </div>

          {/* OR divider between quick picks and manual entry */}
          <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 20 }}>
            <div style={{ flex: 1, height: 1, background: "var(--color-border-tertiary)" }} />
            <span style={{ fontSize: 11, color: "var(--color-text-tertiary)", fontWeight: 500 }}>OR DESCRIBE YOUR OWN SCENE</span>
            <div style={{ flex: 1, height: 1, background: "var(--color-border-tertiary)" }} />
          </div>

          {/* Custom scene description */}
          <div style={{ marginBottom: 24 }}>
            <label style={{ fontSize: 13, fontWeight: 600, color: "#2D6A4F", letterSpacing: 0.5 }}>SCENE DESCRIPTION</label>
            <textarea
              value={prompt}
              onChange={e => { setPrompt(e.target.value); setSelectedScene(null); }}
              placeholder="Describe your golf course scene... e.g. 'Misty dawn, links-style course near coastal cliffs, soft rain, autumn colors'"
              style={{
                width: "100%", marginTop: 8, padding: 14, fontSize: 14, borderRadius: 8,
                border: "1px solid var(--color-border-tertiary)", background: "var(--color-background-secondary)",
                color: "var(--color-text-primary)", resize: "vertical", minHeight: 80,
                fontFamily: "inherit", outline: "none", boxSizing: "border-box"
              }}
            />
          </div>

          {/* OR divider */}
          <div style={{ display: "flex", alignItems: "center", gap: 16, margin: "20px 0" }}>
            <div style={{ flex: 1, height: 1, background: "var(--color-border-tertiary)" }} />
            <span style={{ fontSize: 12, color: "var(--color-text-tertiary)", fontWeight: 500 }}>OR PICK A SCENE</span>
            <div style={{ flex: 1, height: 1, background: "var(--color-border-tertiary)" }} />
          </div>

          {/* Scene grid */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 10, marginBottom: 24 }}>
            {SCENE_LIBRARY.map(s => (
              <button key={s.id} onClick={() => { setSelectedScene(s.id); setPrompt(""); }}
                style={{
                  padding: "12px 14px", borderRadius: 8, cursor: "pointer", textAlign: "left",
                  border: selectedScene === s.id ? "2px solid #2D6A4F" : "1px solid var(--color-border-tertiary)",
                  background: selectedScene === s.id ? "#D8F3DC" : "var(--color-background-secondary)",
                  transition: "all 0.15s", fontFamily: "inherit"
                }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                  <div style={{ width: 8, height: 8, borderRadius: "50%", background: MOOD_COLORS[s.mood] || "#999", flexShrink: 0 }} />
                  <div style={{ fontSize: 13, fontWeight: 600, color: "var(--color-text-primary)" }}>{s.name}</div>
                </div>
                <div style={{ fontSize: 11, color: "var(--color-text-secondary)", lineHeight: 1.4 }}>{s.desc}</div>
              </button>
            ))}
          </div>

          {/* ── Image generation tool selector ───────────────────────── */}
          <div style={{ marginBottom: 20 }}>
            <label style={{ fontSize: 11, fontWeight: 600, color: "var(--color-text-secondary)", letterSpacing: 0.5 }}>
              IMAGE GENERATION TOOL
            </label>
            <div style={{
              display: "flex", marginTop: 6, borderRadius: 8, overflow: "hidden",
              border: "1px solid var(--color-border-tertiary)",
            }}>
              {[
                { id: "chatgpt",    label: "ChatGPT / DALL·E" },
                { id: "kling",      label: "Kling Image Gen"  },
                { id: "midjourney", label: "Midjourney"       },
              ].map((tool, idx, arr) => (
                <button key={tool.id} onClick={() => setImageGenTool(tool.id)} style={{
                  flex: 1, padding: "9px 0", fontSize: 13, fontWeight: imageGenTool === tool.id ? 600 : 400,
                  border: "none", borderRight: idx < arr.length - 1 ? "1px solid var(--color-border-tertiary)" : "none",
                  cursor: "pointer", fontFamily: "inherit", transition: "all 0.15s",
                  background: imageGenTool === tool.id ? "#2D6A4F" : "var(--color-background-secondary)",
                  color: imageGenTool === tool.id ? "#fff" : "var(--color-text-secondary)",
                }}>
                  {tool.label}
                </button>
              ))}
            </div>
          </div>

          {/* Settings row — Stylize shown only for Midjourney */}
          <div style={{
            display: "grid",
            gridTemplateColumns: imageGenTool === "midjourney" ? "1fr 1fr 1fr 1fr" : "1fr 1fr 1fr",
            gap: 16, marginBottom: 24,
          }}>
            <div>
              <label style={{ fontSize: 11, fontWeight: 600, color: "var(--color-text-secondary)" }}>CHARACTER</label>
              <select value={includeCharacter} onChange={e => setIncludeCharacter(e.target.value)}
                style={{ width: "100%", marginTop: 4, padding: "8px 10px", fontSize: 13, borderRadius: 6,
                  border: "1px solid var(--color-border-tertiary)", background: "var(--color-background-secondary)",
                  color: "var(--color-text-primary)", fontFamily: "inherit" }}>
                <option value="random">Random (40%)</option>
                <option value="always">Always</option>
                <option value="never">Never</option>
              </select>
            </div>
            <div>
              <label style={{ fontSize: 11, fontWeight: 600, color: "var(--color-text-secondary)" }}>DURATION</label>
              <select value={duration} onChange={e => setDuration(Number(e.target.value))}
                style={{ width: "100%", marginTop: 4, padding: "8px 10px", fontSize: 13, borderRadius: 6,
                  border: "1px solid var(--color-border-tertiary)", background: "var(--color-background-secondary)",
                  color: "var(--color-text-primary)", fontFamily: "inherit" }}>
                <option value={1}>1 hour</option>
                <option value={2}>2 hours</option>
                <option value={3}>3 hours</option>
                <option value={4}>4 hours</option>
              </select>
            </div>
            <div>
              <label style={{ fontSize: 11, fontWeight: 600, color: "var(--color-text-secondary)" }}>AMBIENCE</label>
              <select value={includeAmbience ? "yes" : "no"} onChange={e => setIncludeAmbience(e.target.value === "yes")}
                style={{ width: "100%", marginTop: 4, padding: "8px 10px", fontSize: 13, borderRadius: 6,
                  border: "1px solid var(--color-border-tertiary)", background: "var(--color-background-secondary)",
                  color: "var(--color-text-primary)", fontFamily: "inherit" }}>
                <option value="yes">Golf sounds</option>
                <option value="no">Music only</option>
              </select>
            </div>
            {imageGenTool === "midjourney" && (
              <div>
                <label style={{ fontSize: 11, fontWeight: 600, color: "var(--color-text-secondary)" }}>STYLIZE (--s)</label>
                <select value={stylize} onChange={e => setStylize(Number(e.target.value))}
                  style={{ width: "100%", marginTop: 4, padding: "8px 10px", fontSize: 13, borderRadius: 6,
                    border: "1px solid var(--color-border-tertiary)", background: "var(--color-background-secondary)",
                    color: "var(--color-text-primary)", fontFamily: "inherit" }}>
                  <option value={500}>--s 500 (more grounded)</option>
                  <option value={600}>--s 600</option>
                  <option value={750}>--s 750 (default)</option>
                  <option value={850}>--s 850</option>
                  <option value={900}>--s 900 (more anime)</option>
                </select>
              </div>
            )}
          </div>

          {/* Generate prompts button — calls server to get MJ + Kling prompts */}
          <button onClick={generateMJPrompt} disabled={(!prompt && !selectedScene) || promptsLoading}
            style={{
              width: "100%", padding: "14px 0", fontSize: 15, fontWeight: 600, borderRadius: 8,
              border: "none", fontFamily: "inherit", letterSpacing: 0.3, transition: "all 0.2s",
              cursor: ((!prompt && !selectedScene) || promptsLoading) ? "not-allowed" : "pointer",
              background: ((!prompt && !selectedScene) || promptsLoading)
                ? (promptsLoading ? "#B08D57" : "var(--color-border-tertiary)")
                : "#2D6A4F",
              color: (!prompt && !selectedScene) ? "var(--color-text-tertiary)" : "#fff",
            }}>
            {promptsLoading ? "Generating Prompts…" : "Generate All Prompts"}
          </button>

          {/* ── SECTION 1: Image prompt (label + instructions change per tool) ── */}
          {generatedPrompt && (
            <div style={{ marginTop: 20 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: "#B08D57", letterSpacing: 1 }}>
                  STEP 1 —{" "}
                  {imageGenTool === "chatgpt"    && "CHATGPT / DALL·E 3 IMAGE PROMPT"}
                  {imageGenTool === "kling"      && "KLING IMAGE GEN PROMPT"}
                  {imageGenTool === "midjourney" && "MIDJOURNEY PROMPT"}
                </div>
                {promptSource && (
                  <div style={{
                    fontSize: 10, fontWeight: 600, padding: "2px 8px", borderRadius: 10,
                    background: promptSource === "claude" ? "#D8F3DC" : "var(--color-accent-light)",
                    color: promptSource === "claude" ? "#1B4332" : "var(--color-text-secondary)",
                  }}>
                    {promptSource === "claude" ? "✦ Claude" : "local fallback"}
                  </div>
                )}
              </div>

              <div style={{ background: "#1B4332", borderRadius: 10, padding: 20 }}>
                <div style={{ fontSize: 11, color: "#B08D57", marginBottom: 8, letterSpacing: 0.5 }}>
                  {imageGenTool === "chatgpt"    && "Paste into ChatGPT → DALL·E image generation"}
                  {imageGenTool === "kling"      && "Paste into app.klingai.com → AI Images → Text to Image · 16:9"}
                  {imageGenTool === "midjourney" && "Copy & paste into Midjourney /imagine"}
                </div>
                <div style={{ fontSize: 13, color: "#D8F3DC", lineHeight: 1.7, fontFamily: "'DM Mono', monospace", wordBreak: "break-word" }}>
                  {generatedPrompt}
                </div>
                <button onClick={copyPrompt} style={{
                  marginTop: 14, padding: "8px 20px", fontSize: 13, fontWeight: 600, borderRadius: 6,
                  border: "1px solid #B08D57", cursor: "pointer", fontFamily: "inherit",
                  background: copied ? "#2D6A4F" : "transparent",
                  color: copied ? "#D8F3DC" : "#B08D57",
                  transition: "all 0.2s"
                }}>
                  {copied ? "✓ Copied!" : "Copy to clipboard"}
                </button>
              </div>
            </div>
          )}

          {/* ── SECTION 2: Kling animation prompts (one per clip) ── */}
          {klingPrompts.length > 0 && (
            <div style={{ marginTop: 24 }}>
              <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 12, gap: 12 }}>
                <div>
                  <div style={{ fontSize: 11, fontWeight: 700, color: "#B08D57", letterSpacing: 1 }}>
                    STEP 2 — KLING ANIMATION PROMPTS
                  </div>
                  <div style={{ fontSize: 12, color: "var(--color-text-tertiary)", marginTop: 3 }}>
                    app.klingai.com → AI Videos → Image to Video &nbsp;·&nbsp; Standard mode · 5 s · 16:9
                  </div>
                </div>
                <button onClick={copyAllKlingPrompts} style={{
                  flexShrink: 0, padding: "7px 14px", fontSize: 12, fontWeight: 600,
                  borderRadius: 6, border: "1px solid #B08D57", cursor: "pointer",
                  fontFamily: "inherit", whiteSpace: "nowrap",
                  background: copiedKling === 'all' ? "#2D6A4F" : "transparent",
                  color: copiedKling === 'all' ? "#fff" : "#B08D57",
                  transition: "all 0.2s"
                }}>
                  {copiedKling === 'all' ? "✓ Copied all!" : "Copy all 6"}
                </button>
              </div>

              {/* ── Negative prompt block (copy once, paste into every clip) ── */}
              <div style={{
                background: "#2D1B00", border: "1px solid #7A4800", borderRadius: 10,
                padding: "14px 16px", marginBottom: 12,
              }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
                  <div>
                    <span style={{ fontSize: 11, fontWeight: 700, color: "#E8A22A", letterSpacing: 1 }}>
                      ⚠ NEGATIVE PROMPT
                    </span>
                    <span style={{ fontSize: 11, color: "#9A6820", marginLeft: 8 }}>
                      paste into Kling's Negative Prompt field — same for every clip
                    </span>
                  </div>
                  <button onClick={copyNegativePrompt} style={{
                    flexShrink: 0, padding: "5px 12px", fontSize: 11, fontWeight: 600,
                    borderRadius: 5, border: "1px solid #7A4800", cursor: "pointer",
                    fontFamily: "inherit",
                    background: copiedNegative ? "#7A4800" : "transparent",
                    color: copiedNegative ? "#FFD580" : "#E8A22A",
                    transition: "all 0.2s",
                  }}>
                    {copiedNegative ? "✓ Copied!" : "Copy"}
                  </button>
                </div>
                <div style={{
                  fontSize: 12, color: "#FFD580", lineHeight: 1.6,
                  fontFamily: "'DM Mono', monospace", wordBreak: "break-word",
                }}>
                  {klingNegativePrompt || DEFAULT_NEGATIVE_PROMPT}
                </div>
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {klingPrompts.map((p, i) => (
                  <div key={i} style={{
                    background: "#1B4332", borderRadius: 8, padding: "12px 14px",
                    display: "flex", gap: 12, alignItems: "flex-start"
                  }}>
                    <div style={{
                      fontSize: 10, fontWeight: 700, color: "#B08D57", letterSpacing: 0.5,
                      whiteSpace: "nowrap", marginTop: 3, minWidth: 38
                    }}>
                      CLIP {i + 1}
                    </div>
                    <div style={{
                      flex: 1, fontSize: 12, color: "#D8F3DC", lineHeight: 1.6,
                      fontFamily: "'DM Mono', monospace", wordBreak: "break-word"
                    }}>
                      {p}
                    </div>
                    <button onClick={() => copyKlingPrompt(i)} style={{
                      flexShrink: 0, padding: "5px 12px", fontSize: 11, fontWeight: 600,
                      borderRadius: 5, border: "1px solid #B08D57", cursor: "pointer",
                      fontFamily: "inherit",
                      background: copiedKling === i ? "#2D6A4F" : "transparent",
                      color: copiedKling === i ? "#D8F3DC" : "#B08D57",
                      transition: "all 0.2s"
                    }}>
                      {copiedKling === i ? "✓" : "Copy"}
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ================================================================== */}
      {/* TAB: UPLOAD IMAGES                                                  */}
      {/* ================================================================== */}
      {tab === "upload" && (
        <div style={{ padding: "24px 0" }}>
          <div style={{ fontSize: 14, color: "var(--color-text-secondary)", marginBottom: 20, lineHeight: 1.6 }}>
            Upload your Midjourney or ChatGPT generated images here. Pick your single best image —
            this becomes the "living painting" base for the entire video. Images are saved to{" "}
            <code style={{ fontSize: 12, background: "var(--color-accent-light)", padding: "2px 6px", borderRadius: 4 }}>
              assets/midjourney_images/
            </code>
            {" "}on the server.
          </div>

          {/* Error message */}
          {uploadError && (
            <div style={{
              marginBottom: 16, padding: "12px 16px", borderRadius: 8,
              background: "#FFF5F5", border: "1px solid #FC8181", color: "#9B2C2C", fontSize: 13
            }}>
              {uploadError}
            </div>
          )}

          {/* Drop zone — click to open file picker */}
          <div
            onClick={() => fileInputRef.current?.click()}
            onDragOver={e => e.preventDefault()}
            onDrop={e => {
              e.preventDefault();
              // Simulate a change event with the dropped files
              handleImageUpload({ target: { files: e.dataTransfer.files, value: '' } });
            }}
            style={{
              border: "2px dashed var(--color-border-secondary)", borderRadius: 12, padding: "48px 24px",
              textAlign: "center", cursor: "pointer", transition: "all 0.2s",
              background: "var(--color-background-secondary)"
            }}
          >
            <div style={{ fontSize: 36, marginBottom: 8 }}>&#x1F3CC;</div>
            <div style={{ fontSize: 15, fontWeight: 600, color: "var(--color-text-primary)", marginBottom: 4 }}>
              Drop images here or click to browse
            </div>
            <div style={{ fontSize: 12, color: "var(--color-text-tertiary)" }}>
              PNG or JPG, 1920x1080 or larger recommended
            </div>
            {/* Hidden file input — triggered by clicking the drop zone above */}
            <input
              ref={fileInputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              multiple
              onChange={handleImageUpload}
              style={{ display: "none" }}
            />
          </div>

          {/* Uploaded images grid */}
          {uploadedImages.length > 0 && (
            <div style={{ marginTop: 24 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: "#2D6A4F", marginBottom: 4 }}>
                YOUR IMAGES ({uploadedImages.length}) — Click one to use it for the video
              </div>
              <div style={{ fontSize: 12, color: "var(--color-text-tertiary)", marginBottom: 12 }}>
                {selectedImage
                  ? `Selected: ${selectedImage}`
                  : "No image selected — click an image to choose which one to animate"}
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 14 }}>
                {uploadedImages.map((img, i) => {
                  const isSelected = selectedImage === img.name;
                  return (
                    <div
                      key={i}
                      onClick={() => setSelectedImage(img.name)}
                      style={{
                        borderRadius: 10, overflow: "hidden", cursor: "pointer",
                        border: isSelected ? "3px solid #2D6A4F" : "2px solid var(--color-border-tertiary)",
                        background: "var(--color-background-secondary)",
                        boxShadow: isSelected ? "0 0 0 3px #D8F3DC" : "none",
                        transition: "all 0.15s",
                      }}
                    >
                      <div style={{ position: "relative" }}>
                        <img
                          src={img.src}
                          alt={img.name}
                          style={{ width: "100%", height: 160, objectFit: "cover", display: "block" }}
                        />
                        {/* Green checkmark badge on selected image */}
                        {isSelected && (
                          <div style={{
                            position: "absolute", top: 8, left: 8,
                            background: "#2D6A4F", color: "#fff",
                            borderRadius: 20, padding: "3px 10px",
                            fontSize: 12, fontWeight: 700,
                          }}>✓ Selected</div>
                        )}
                        {/* Delete button — stopPropagation prevents also selecting the image */}
                        <button
                          onClick={e => { e.stopPropagation(); removeImage(i); }}
                          style={{
                            position: "absolute", top: 8, right: 8, width: 28, height: 28,
                            borderRadius: "50%", background: "rgba(0,0,0,0.6)", color: "#fff",
                            border: "none", cursor: "pointer", fontSize: 14,
                            display: "flex", alignItems: "center", justifyContent: "center"
                          }}>x</button>
                      </div>
                      <div style={{ padding: "10px 12px" }}>
                        <div style={{
                          fontSize: 13, fontWeight: isSelected ? 600 : 500,
                          color: isSelected ? "#2D6A4F" : "var(--color-text-primary)",
                          whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis"
                        }}>{img.name}</div>
                        <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 2 }}>
                          {img.size} · {img.date}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ================================================================== */}
      {/* TAB: RUN PIPELINE                                                   */}
      {/* ================================================================== */}
      {tab === "pipeline" && (
        <div style={{ padding: "24px 0" }}>

          {/* Status cards — 2×2 grid */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 24 }}>

            {/* BASE IMAGE card */}
            <div
              onClick={() => setTab("upload")}
              style={{ padding: "16px", borderRadius: 10, border: `1px solid ${selectedImage ? "#2D6A4F" : "var(--color-border-tertiary)"}`, background: "var(--color-background-secondary)", cursor: "pointer" }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: "var(--color-text-tertiary)", letterSpacing: 0.5 }}>BASE IMAGE</div>
              <div style={{ fontSize: 15, fontWeight: 700, marginTop: 4, color: selectedImage ? "#2D6A4F" : "#9B2C2C" }}>
                {selectedImage
                  ? selectedImage.length > 22 ? selectedImage.slice(0, 20) + "…" : selectedImage
                  : "None selected"}
              </div>
              {!selectedImage && (
                <div style={{ fontSize: 11, color: "#9B2C2C", marginTop: 2 }}>Click to pick one</div>
              )}
            </div>

            {/* KLING CLIPS card */}
            <div style={{ padding: "16px", borderRadius: 10, border: `1px solid ${klingClipSets.length > 0 ? "#2D6A4F" : "var(--color-border-tertiary)"}`, background: "var(--color-background-secondary)" }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: "var(--color-text-tertiary)", letterSpacing: 0.5, marginBottom: 6 }}>KLING CLIPS</div>
              {klingClipSets.length === 0 ? (
                <div style={{ fontSize: 13, color: "#9B2C2C", fontWeight: 600 }}>
                  No clips found
                  <div style={{ fontSize: 11, fontWeight: 400, marginTop: 2 }}>
                    Add .mp4s to assets/kling_clips/
                  </div>
                </div>
              ) : (
                <select
                  value={selectedClipSet ?? ""}
                  onChange={e => setSelectedClipSet(e.target.value)}
                  style={{
                    width: "100%", padding: "6px 8px", fontSize: 13, borderRadius: 6,
                    border: "1px solid #2D6A4F", background: "var(--color-background-secondary)",
                    color: "#2D6A4F", fontFamily: "inherit", fontWeight: 600,
                  }}
                >
                  {klingClipSets.map(s => (
                    <option key={s.name} value={s.name}>{s.label}</option>
                  ))}
                </select>
              )}
              <button
                onClick={refreshClipSets}
                style={{
                  marginTop: 8, fontSize: 11, color: "var(--color-text-tertiary)",
                  background: "none", border: "none", cursor: "pointer", padding: 0,
                  fontFamily: "inherit",
                }}
              >↻ Refresh</button>
            </div>

            {/* DURATION card */}
            <div style={{ padding: "16px", borderRadius: 10, border: "1px solid var(--color-border-tertiary)", background: "var(--color-background-secondary)" }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: "var(--color-text-tertiary)", letterSpacing: 0.5 }}>DURATION</div>
              <div style={{ fontSize: 20, fontWeight: 700, color: "var(--color-text-primary)", marginTop: 4 }}>{duration} hours</div>
            </div>

            {/* AMBIENCE card */}
            <div style={{ padding: "16px", borderRadius: 10, border: "1px solid var(--color-border-tertiary)", background: "var(--color-background-secondary)" }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: "var(--color-text-tertiary)", letterSpacing: 0.5 }}>AMBIENCE</div>
              <div style={{ fontSize: 20, fontWeight: 700, color: "var(--color-text-primary)", marginTop: 4 }}>
                {includeAmbience ? "Golf sounds" : "Music only"}
              </div>
            </div>

          </div>

          {/* Terminal command preview */}
          <div style={{ background: "#1B4332", borderRadius: 10, padding: "16px 20px", marginBottom: 20 }}>
            <div style={{ fontSize: 11, color: "#B08D57", fontWeight: 600, letterSpacing: 1, marginBottom: 8 }}>EQUIVALENT TERMINAL COMMAND</div>
            <div style={{ fontSize: 13, color: "#D8F3DC", fontFamily: "'DM Mono', monospace", wordBreak: "break-all" }}>
              {commandPreview}
            </div>
          </div>

          {/* Pipeline complete / error banner */}
          {pipelineStatus === 'complete' && !pipelineRunning && (
            <div style={{
              marginBottom: 16, padding: "12px 16px", borderRadius: 8,
              background: "#D8F3DC", border: "1px solid #2D6A4F", color: "#1B4332",
              fontSize: 14, fontWeight: 600
            }}>
              Pipeline complete! Check the <code>output/</code> folder for your video.
            </div>
          )}
          {pipelineStatus === 'error' && !pipelineRunning && (
            <div style={{
              marginBottom: 16, padding: "12px 16px", borderRadius: 8,
              background: "#FFF5F5", border: "1px solid #FC8181", color: "#9B2C2C",
              fontSize: 14, fontWeight: 600
            }}>
              Pipeline encountered an error. See log below for details.
            </div>
          )}

          {/* Run button */}
          <button
            onClick={runPipeline}
            disabled={!selectedImage || pipelineRunning}
            style={{
              width: "100%", padding: "16px 0", fontSize: 16, fontWeight: 700,
              borderRadius: 10, border: "none", fontFamily: "inherit", letterSpacing: 0.5,
              cursor: (!selectedImage || pipelineRunning) ? "not-allowed" : "pointer",
              background: !selectedImage
                ? "var(--color-border-tertiary)"
                : pipelineRunning ? "#B08D57" : "#2D6A4F",
              color: !selectedImage ? "var(--color-text-tertiary)" : "#fff",
              transition: "all 0.2s"
            }}>
            {pipelineRunning
              ? "Pipeline Running..."
              : !selectedImage
                ? "Select an image first"
                : `Run Pipeline — ${selectedImage}`}
          </button>

          {!selectedImage && (
            <div style={{ marginTop: 12, fontSize: 13, color: "var(--color-text-tertiary)", textAlign: "center" }}>
              Go to <strong>Upload Images</strong> and click the image you want to animate
            </div>
          )}

          {/* Pipeline log */}
          {pipelineLog.length > 0 && (
            <div style={{ marginTop: 20, borderRadius: 10, border: "1px solid var(--color-border-tertiary)", overflow: "hidden" }}>
              <div style={{
                padding: "12px 16px", background: "var(--color-background-secondary)",
                borderBottom: "1px solid var(--color-border-tertiary)",
                display: "flex", justifyContent: "space-between", alignItems: "center"
              }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: "var(--color-text-primary)" }}>Pipeline Log</span>
                {pipelineRunning && (
                  <span style={{ fontSize: 11, color: "#B08D57", fontWeight: 600 }}>LIVE</span>
                )}
              </div>
              <div style={{ maxHeight: 400, overflowY: "auto" }}>
                {pipelineLog.map((log, i) => (
                  <div key={i} style={{
                    padding: "9px 16px", fontSize: 13, display: "flex", gap: 12, alignItems: "flex-start",
                    borderBottom: i < pipelineLog.length - 1 ? "1px solid var(--color-border-tertiary)" : "none",
                    background: log.done ? "#D8F3DC" : log.error ? "#FFF5F5" : "transparent",
                  }}>
                    <span style={{ fontSize: 11, color: "var(--color-text-tertiary)", fontFamily: "monospace", whiteSpace: "nowrap", marginTop: 1 }}>
                      {log.time}
                    </span>
                    <span style={{ fontSize: 11, color: log.error ? "#9B2C2C" : "#2D6A4F", fontWeight: 600, whiteSpace: "nowrap", marginTop: 1 }}>
                      [{log.stage}]
                    </span>
                    <span style={{
                      color: log.done ? "#1B4332" : log.error ? "#9B2C2C" : "var(--color-text-primary)",
                      fontWeight: (log.done || log.error) ? 600 : 400,
                      wordBreak: "break-word",
                    }}>
                      {log.msg}
                    </span>
                  </div>
                ))}
                {/* Invisible anchor for auto-scroll */}
                <div ref={logEndRef} />
              </div>
            </div>
          )}
        </div>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* FOOTER                                                              */}
      {/* ------------------------------------------------------------------ */}
      <div style={{ borderTop: "1px solid var(--color-border-tertiary)", padding: "16px 0", marginTop: 24, textAlign: "center" }}>
        <div style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>
          Fairway Frequencies · Living Painting Pipeline · v3.0
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// MOUNT REACT
// =============================================================================
// WHY: In a normal React app built with Vite/webpack you'd have an index.js
// that calls ReactDOM.createRoot. Here, this JSX file IS the entry point,
// so we mount the component at the bottom of the file.
// index.html has <div id="root"></div> which is where React renders into.
// =============================================================================
ReactDOM.createRoot(document.getElementById('root')).render(
  React.createElement(FairwayControlPanel)
);
