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

// Monthly art style rotation — mirrors ART_STYLES in pipeline/orchestrator.py
// (month - 1) % 4 → 0=Ghibli, 1=Cinematic, 2=Watercolour, 3=Oil Painting
const ART_STYLES = [
  { name: "Studio Ghibli Anime",      short: "Ghibli",      description: "Hand-painted anime aesthetic. Rich saturated colors, soft natural light, dreamlike atmosphere.", accent: "#2D6A4F" },
  { name: "Cinematic Photorealistic", short: "Cinematic",   description: "Film-quality photography look. Dramatic golden-hour lighting, shallow depth of field.",          accent: "#744210" },
  { name: "Soft Watercolour",         short: "Watercolour", description: "Delicate watercolour illustration. Soft washes, paper texture, impressionistic.",                accent: "#2C5282" },
  { name: "Rich Oil Painting",        short: "Oil Painting",description: "Classical oil painting. Impasto texture, Old Masters drama, rich deep colors.",                  accent: "#702459" },
];

function getCurrentArtStyle() {
  const month = new Date().getMonth() + 1; // 1-12
  return ART_STYLES[(month - 1) % 4];
}

// Short style suffix appended to Gemini prompts — matches STYLE_SUFFIX in config.py
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
  const [sceneGenerating, setSceneGenerating] = useState(false);
  const [includeCharacter, setIncludeCharacter] = useState("random");
  const [includeAmbience, setIncludeAmbience] = useState(true);
  const [duration, setDuration] = useState(2);
  const [uploadToYoutube, setUploadToYoutube] = useState(false);
  const [abTest, setAbTest] = useState(true);
  const [stylize, setStylize] = useState(750);
  const [generatedPrompt, setGeneratedPrompt] = useState("");
  const [pipelineLog, setPipelineLog] = useState([]);
  const [pipelineRunning, setPipelineRunning] = useState(false);
  const [pipelineStatus, setPipelineStatus] = useState(null); // "running" | "complete" | "error"
  const [pipelineStartTime, setPipelineStartTime] = useState(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [logExpanded, setLogExpanded] = useState(false);
  const [copied, setCopied] = useState(false);
  const [klingPrompts, setKlingPrompts] = useState([]);   // 3 Kling animation prompts
  const [promptsLoading, setPromptsLoading] = useState(false); // waiting for server
  const [copiedKling, setCopiedKling] = useState(null);        // index | "all" | null
  const [klingNegativePrompt, setKlingNegativePrompt] = useState(""); // negative prompt (same for all clips)
  const [copiedNegative, setCopiedNegative] = useState(false);        // for the negative prompt copy btn
  const [promptSource, setPromptSource] = useState(null);             // "claude" | "local"
  const [klingClipSets, setKlingClipSets] = useState([]);       // available clip sets
  const [selectedClipSet, setSelectedClipSet] = useState(null); // chosen folder name ("" = root)
  const [imageGenTool] = useState("gemini");

  // Analytics state
  const [analyticsData, setAnalyticsData] = useState(null);
  const [analyticsLoading, setAnalyticsLoading] = useState(false);
  const [analyticsError, setAnalyticsError] = useState(null);

  // Scene history — { scene_id: days_ago }
  const [usedSceneIds, setUsedSceneIds] = useState({});

  // ---------------------------------------------------------------------------
  // getRecommendations — analyze analytics data and return actionable cards
  // ---------------------------------------------------------------------------
  // Each card: { icon, title, body, action, accent }
  // accent: "green" | "yellow" | "red" | "blue"
  function getRecommendations(data, sceneHistory = {}) {
    const recs = [];
    const videos = data.videos || [];
    const channel = data.channel || {};

    // ── 1. Top performer by avg view % ─────────────────────────────────────
    if (videos.length > 0) {
      const best = videos.reduce((a, b) => a.avg_view_pct >= b.avg_view_pct ? a : b);
      const shortTitle = best.title.length > 40 ? best.title.slice(0, 38) + "…" : best.title;
      if (best.avg_view_pct >= 30) {
        recs.push({
          icon: "★",
          title: "Top Performer — Make More Like This",
          body: `"${shortTitle}" has ${best.avg_view_pct}% avg view retention — your strongest video. Viewers are staying engaged. Replicate the scene mood, thumbnail style, and music energy for your next upload.`,
          action: `Suggested next scene: same vibe as ${shortTitle.split("—")[1]?.trim() || "this one"}`,
          accent: "green",
        });
      } else if (best.avg_view_pct > 0) {
        recs.push({
          icon: "↑",
          title: "Best Retention So Far",
          body: `"${shortTitle}" leads with ${best.avg_view_pct}% avg view — but there's room to grow. LoFi channels typically hit 30–50% once the algorithm finds the right audience.`,
          action: "Focus on consistency — more uploads help the algorithm learn your audience",
          accent: "yellow",
        });
      }
    }

    // ── 2. Retention health check ───────────────────────────────────────────
    if (videos.length > 1) {
      const avgRetention = videos.reduce((sum, v) => sum + v.avg_view_pct, 0) / videos.length;
      if (avgRetention < 20) {
        recs.push({
          icon: "⚠",
          title: "Low Retention — Thumbnail/Title Mismatch Likely",
          body: `Average retention across your videos is ${avgRetention.toFixed(1)}%. When viewers click but leave quickly it usually means the thumbnail or title promises something different from what they get. Consider more literal thumbnail text (e.g. "2 HOUR LOFI" instead of a mood phrase).`,
          action: "Try A/B testing: one keyword thumbnail vs one mood thumbnail on the next upload",
          accent: "red",
        });
      } else if (avgRetention >= 40) {
        recs.push({
          icon: "✓",
          title: "Strong Retention — Push for Volume",
          body: `${avgRetention.toFixed(1)}% avg retention is excellent for long-form LoFi. YouTube's algorithm will reward consistency now. The main lever is publishing frequency.`,
          action: "Aim for 1 upload per week to accelerate algorithm indexing",
          accent: "green",
        });
      }
    }

    // ── 3. Watch hours milestone ─────────────────────────────────────────────
    if (channel.watch_hours !== undefined) {
      const hrs = channel.watch_hours;
      // YouTube monetization requires 4,000 watch hours in 12 months
      if (hrs < 100) {
        recs.push({
          icon: "⏱",
          title: "Building Watch Hours",
          body: `You have ${hrs} watch hours this month. Long-form LoFi (2–3 hrs) is one of the best formats for accumulating watch hours quickly — each video that gets traction multiplies your totals. YouTube monetization unlocks at 4,000 hours/year.`,
          action: "Prioritize 2–3 hour videos over 1 hour while building up",
          accent: "blue",
        });
      } else if (hrs >= 100 && hrs < 500) {
        recs.push({
          icon: "⏱",
          title: "Watch Hours Growing",
          body: `${hrs} watch hours this month — solid progress. At this pace, consistent uploads will get you to the 4,000-hour/year monetization threshold within a few months.`,
          action: "Keep the 2–3 hour format. Each viral video compounds your total fast.",
          accent: "blue",
        });
      }
    }

    // ── 4. Subscriber momentum ───────────────────────────────────────────────
    if (channel.subscribers_gained > 0) {
      const ratio = channel.views > 0
        ? ((channel.subscribers_gained / channel.views) * 100).toFixed(2)
        : "0";
      recs.push({
        icon: "↗",
        title: "Subscriber Conversion",
        body: `You gained ${channel.subscribers_gained} subscribers from ${channel.views.toLocaleString()} views — a ${ratio}% conversion rate. LoFi channels typically convert at 0.5–2%. A channel branding card in the first 30 seconds of each video can lift this.`,
        action: "Add an end screen with Subscribe prompt via YouTube Studio",
        accent: channel.subscribers_gained >= 5 ? "green" : "yellow",
      });
    }

    // ── 5. Next video prompt ─────────────────────────────────────────────────
    const artStyle = getCurrentArtStyle();
    const season = getCurrentSeasonScene().label;
    recs.push({
      icon: "▶",
      title: `Next Video: ${artStyle.name} + ${season}`,
      body: `This month's art style is ${artStyle.name}. Click "✦ Generate Scene" on the Create tab — Claude will write a fresh golf scene that matches the ${artStyle.short} aesthetic and the current ${season} season.`,
      action: `Go to Create & Prompt → click ✦ Generate Scene → run the pipeline`,
      accent: "blue",
    });

    return recs;
  }

  // Refs
  const pollingRef = useRef(null);   // stores the setInterval ID for pipeline polling
  const logEndRef = useRef(null);    // for auto-scrolling the log to the bottom


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

  // ---------------------------------------------------------------------------
  // fetchAnalytics — call /api/analytics and populate the analytics tab
  // ---------------------------------------------------------------------------
  const fetchAnalytics = useCallback(() => {
    setAnalyticsLoading(true);
    setAnalyticsError(null);

    // Fetch analytics + scene history in parallel
    Promise.all([
      fetch('/api/analytics').then(r => r.json()),
      fetch('/api/scene-history').then(r => r.json()).catch(() => ({ used_ids: {} })),
    ]).then(([analyticsJson, historyJson]) => {
      if (analyticsJson.error) {
        setAnalyticsError(analyticsJson.error);
      } else {
        setAnalyticsData(analyticsJson);
      }
      setUsedSceneIds(historyJson.used_ids || {});
      setAnalyticsLoading(false);
    }).catch(err => {
      setAnalyticsError(`Could not reach server: ${err.message}`);
      setAnalyticsLoading(false);
    });
  }, []);

  // Load scene history on mount (so scene badges show immediately on Create tab)
  useEffect(() => {
    fetch('/api/scene-history')
      .then(r => r.json())
      .then(data => setUsedSceneIds(data.used_ids || {}))
      .catch(() => {});
  }, []);

  // Load full analytics when the tab is opened
  useEffect(() => { if (tab === "analytics" && !analyticsData) fetchAnalytics(); }, [tab]);

  // Auto-scroll the pipeline log to the latest entry whenever a new line arrives
  useEffect(() => {
    if (logEndRef.current) {
      logEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [pipelineLog]);

  // Tick elapsed time every second while pipeline is running
  useEffect(() => {
    if (!pipelineRunning || !pipelineStartTime) return;
    const timer = setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - pipelineStartTime) / 1000));
    }, 1000);
    return () => clearInterval(timer);
  }, [pipelineRunning, pipelineStartTime]);

  // Clean up the polling interval if the component unmounts mid-run
  useEffect(() => {
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, []);

  // ---------------------------------------------------------------------------
  // GENERATE ALL PROMPTS — Gemini (image) + Kling (3 animation clips)
  // ---------------------------------------------------------------------------
  // HOW IT WORKS:
  //   1. POST /api/generate-prompt → server uses Claude (if key set) or local
  //      fallback to build a full orchestration object
  //   2. Response gives us: image_prompt (Gemini) + base_video_prompt +
  //      animation_variations (3 Kling clip prompts)
  //   3. If the server is unreachable, fall back entirely to local generation
  // ---------------------------------------------------------------------------
  // formatImagePrompt — wraps a raw scene prompt for Google Gemini
  const formatImagePrompt = useCallback((raw) => {
    return (
      `Create a 16:9 widescreen digital illustration: ${raw}. ` +
      `Art style: detailed anime background painting, Studio Ghibli inspired, ` +
      `vibrant saturated colors, clean linework, lush detailed landscape, ` +
      `warm natural lighting, soft puffy clouds, visible brushstroke texture, ` +
      `concept art quality. No text, no logos, no UI elements, no watermarks.`
    );
  }, []);

  const generateMJPrompt = useCallback(async (overrideDesc = null) => {
    const sceneDesc = overrideDesc || prompt;
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
      imagePrompt = formatImagePrompt(rawPrompt);

      // Animation variations are now objects { prompt, negative_prompt }.
      // Extract the positive prompts for display; the negative prompt is shared.
      const variations = orch.animation_variations || ANIMATION_VARIATIONS;
      klingPromptsArr = variations.slice(0, 3).map(v =>
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
      imagePrompt = formatImagePrompt(rawLocal);
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
  }, [prompt, includeCharacter, stylize, formatImagePrompt]);

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
  // GENERATE SCENE — call /api/generate-scene (Claude picks a fresh scene
  // based on the current month's art style + season)
  // ---------------------------------------------------------------------------
  const handleGenerateScene = useCallback(async () => {
    setSceneGenerating(true);
    try {
      const res = await fetch('/api/generate-scene', { method: 'POST' });
      const data = await res.json();
      if (data.scene) {
        setPrompt(data.scene);
        await generateMJPrompt(data.scene);
      }
    } catch (err) {
      console.error('Scene generation failed:', err);
    }
    setSceneGenerating(false);
  }, [generateMJPrompt]);


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
    if (pipelineRunning) return;

    setPipelineRunning(true);
    setPipelineStatus("running");
    setPipelineLog([]);
    setPipelineStartTime(Date.now());
    setElapsedSeconds(0);
    setLogExpanded(false);

    // Build the arguments to pass to fairway.py.
    const args = {
      duration: duration,
      no_ambience: !includeAmbience,
      character: includeCharacter,
      scene: prompt,
      clips_folder: selectedClipSet,     // which video_clips subfolder to use
      upload: uploadToYoutube,
      ab_test: abTest,
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

  }, [pipelineRunning, prompt, duration, includeAmbience, includeCharacter, selectedClipSet, uploadToYoutube, abTest]);

  // ---------------------------------------------------------------------------
  // BUILD COMMAND PREVIEW (shown in the dark box on the Run tab)
  // ---------------------------------------------------------------------------
  const commandPreview = (() => {
    const parts = ['python -X utf8 fairway.py'];
    if (prompt) parts.push(`"${prompt}"`);
    parts.push(`--duration ${duration}`);
    if (selectedClipSet != null) parts.push(`--clips-folder "${selectedClipSet || '(root)'}"`);
    if (!includeAmbience) parts.push('--no-ambience');
    if (includeCharacter !== 'random') parts.push(`--character ${includeCharacter}`);
    if (!uploadToYoutube) parts.push('--no-upload');
    if (abTest) parts.push('--ab-test');
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
          { id: "create",    label: "Create & Prompt" },
          { id: "pipeline",  label: "Run Pipeline" },
          { id: "analytics", label: "Analytics" },
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

          {/* ── Art Style Banner ─────────────────────────────────────────── */}
          {(() => {
            const style = getCurrentArtStyle();
            return (
              <div style={{
                borderRadius: 10, padding: "16px 20px", marginBottom: 20,
                border: `1px solid ${style.accent}40`,
                background: `${style.accent}12`,
              }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
                  <div>
                    <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: 1.5, color: style.accent, marginBottom: 4 }}>
                      THIS MONTH'S ART STYLE
                    </div>
                    <div style={{ fontSize: 16, fontWeight: 700, color: "var(--color-text-primary)" }}>{style.name}</div>
                    <div style={{ fontSize: 12, color: "var(--color-text-secondary)", marginTop: 2 }}>{style.description}</div>
                  </div>
                  <div style={{
                    fontSize: 11, fontWeight: 600, padding: "4px 10px", borderRadius: 20,
                    background: style.accent, color: "#fff", letterSpacing: 0.3,
                  }}>
                    {style.short}
                  </div>
                </div>
              </div>
            );
          })()}

          {/* ── Generate Scene + manual textarea ──────────────────────── */}
          <div style={{ marginBottom: 24 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
              <label style={{ fontSize: 13, fontWeight: 600, color: "#2D6A4F", letterSpacing: 0.5 }}>SCENE DESCRIPTION</label>
              <button
                onClick={handleGenerateScene}
                disabled={sceneGenerating || promptsLoading}
                style={{
                  padding: "7px 16px", fontSize: 13, fontWeight: 600, borderRadius: 8,
                  border: "1px solid #2D6A4F", cursor: (sceneGenerating || promptsLoading) ? "not-allowed" : "pointer",
                  background: sceneGenerating ? "var(--color-background-secondary)" : "#2D6A4F",
                  color: sceneGenerating ? "#2D6A4F" : "#fff",
                  fontFamily: "inherit", transition: "all 0.2s", letterSpacing: 0.2,
                  opacity: (sceneGenerating || promptsLoading) ? 0.7 : 1,
                }}
              >
                {sceneGenerating ? "✦ Generating…" : "✦ Generate Scene"}
              </button>
            </div>
            <textarea
              value={prompt}
              onChange={e => setPrompt(e.target.value)}
              placeholder="Click ✦ Generate Scene to have Claude write a fresh scene for this month's art style, or type your own description…"
              style={{
                width: "100%", padding: 14, fontSize: 14, borderRadius: 8,
                border: "1px solid var(--color-border-tertiary)", background: "var(--color-background-secondary)",
                color: "var(--color-text-primary)", resize: "vertical", minHeight: 90,
                fontFamily: "inherit", outline: "none", boxSizing: "border-box"
              }}
            />
          </div>

          {/* ── Image generation tool ────────────────────────────────── */}
          <div style={{ marginBottom: 20 }}>
            <label style={{ fontSize: 11, fontWeight: 600, color: "var(--color-text-secondary)", letterSpacing: 0.5 }}>
              IMAGE GENERATION TOOL
            </label>
            <div style={{
              marginTop: 6, padding: "9px 14px", borderRadius: 8, fontSize: 13, fontWeight: 600,
              border: "1px solid var(--color-border-tertiary)", background: "#2D6A4F", color: "#fff",
            }}>
              Google Gemini
            </div>
          </div>

          {/* Settings row */}
          <div style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr 1fr 1fr",
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
            <div>
              <label style={{ fontSize: 11, fontWeight: 600, color: "var(--color-text-secondary)" }}>YOUTUBE UPLOAD</label>
              <div style={{
                marginTop: 4, padding: "8px 10px", fontSize: 13, borderRadius: 6,
                border: "1px solid var(--color-border-tertiary)", background: "var(--color-background-secondary)",
                display: "flex", alignItems: "center", gap: 8, cursor: "pointer", height: 37,
              }} onClick={() => setUploadToYoutube(v => !v)}>
                <input type="checkbox" checked={uploadToYoutube} onChange={e => setUploadToYoutube(e.target.checked)}
                  style={{ cursor: "pointer", width: 14, height: 14, accentColor: "#2D6A4F" }} />
                <span style={{ color: uploadToYoutube ? "var(--color-text-primary)" : "var(--color-text-tertiary)" }}>
                  {uploadToYoutube ? "Upload & schedule" : "Skip upload"}
                </span>
              </div>
            </div>
            <div>
              <label style={{ fontSize: 11, fontWeight: 600, color: "var(--color-text-secondary)" }}>A/B MUSIC TEST</label>
              <div style={{
                marginTop: 4, padding: "8px 10px", fontSize: 13, borderRadius: 6,
                border: abTest ? "1px solid #B08D57" : "1px solid var(--color-border-tertiary)",
                background: abTest ? "rgba(176,141,87,0.08)" : "var(--color-background-secondary)",
                display: "flex", alignItems: "center", gap: 8, cursor: "pointer", height: 37,
              }} onClick={() => setAbTest(v => !v)}>
                <input type="checkbox" checked={abTest} onChange={e => setAbTest(e.target.checked)}
                  style={{ cursor: "pointer", width: 14, height: 14, accentColor: "#B08D57" }} />
                <span style={{ color: abTest ? "#B08D57" : "var(--color-text-tertiary)" }}>
                  {abTest ? "Jazz + Hip-Hop variants" : "Single video"}
                </span>
              </div>
            </div>
          </div>

          {/* Generate prompts button — calls server to get MJ + Kling prompts */}
          <button onClick={generateMJPrompt} disabled={!prompt || promptsLoading}
            style={{
              width: "100%", padding: "14px 0", fontSize: 15, fontWeight: 600, borderRadius: 8,
              border: "none", fontFamily: "inherit", letterSpacing: 0.3, transition: "all 0.2s",
              cursor: (!prompt || promptsLoading) ? "not-allowed" : "pointer",
              background: (!prompt || promptsLoading)
                ? (promptsLoading ? "#B08D57" : "var(--color-border-tertiary)")
                : "#2D6A4F",
              color: !prompt ? "var(--color-text-tertiary)" : "#fff",
            }}>
            {promptsLoading ? "Generating Prompts…" : "Generate All Prompts"}
          </button>

          {/* ── SECTION 1: Image prompt (label + instructions change per tool) ── */}
          {generatedPrompt && (
            <div style={{ marginTop: 20 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: "#B08D57", letterSpacing: 1 }}>
                  STEP 1 — GOOGLE GEMINI IMAGE PROMPT
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
                  Paste into Gemini → Generate image · 16:9
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
                  {copiedKling === 'all' ? "✓ Copied all!" : "Copy all 3"}
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
      {/* TAB: RUN PIPELINE                                                   */}
      {/* ================================================================== */}
      {tab === "pipeline" && (
        <div style={{ padding: "24px 0" }}>

          {/* Status cards */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 24 }}>

            {/* VIDEO CLIPS card */}
            <div style={{ padding: "16px", borderRadius: 10, border: `1px solid ${klingClipSets.length > 0 ? "#2D6A4F" : "var(--color-border-tertiary)"}`, background: "var(--color-background-secondary)" }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: "var(--color-text-tertiary)", letterSpacing: 0.5, marginBottom: 6 }}>VIDEO CLIPS</div>
              {klingClipSets.length === 0 ? (
                <div style={{ fontSize: 13, color: "#9B2C2C", fontWeight: 600 }}>
                  No clips found
                  <div style={{ fontSize: 11, fontWeight: 400, marginTop: 2 }}>
                    Add .mp4s to assets/video_clips/
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
            disabled={pipelineRunning}
            style={{
              width: "100%", padding: "16px 0", fontSize: 16, fontWeight: 700,
              borderRadius: 10, border: "none", fontFamily: "inherit", letterSpacing: 0.5,
              cursor: pipelineRunning ? "not-allowed" : "pointer",
              background: pipelineRunning ? "#B08D57" : "#2D6A4F",
              color: "#fff",
              transition: "all 0.2s"
            }}>
            {pipelineRunning ? "Pipeline Running..." : "Run Pipeline"}
          </button>

          {/* ── PIPELINE STATUS CARD (shown while running or after finish) ── */}
          {pipelineLog.length > 0 && (() => {
            // Derive current stage and progress from log entries
            const stageNames = {
              "1": "Orchestration", "2": "Video Clips", "3": "Video Assembly",
              "4": "Music Track",   "5": "Ambient Sounds", "6": "Mix Audio",
              "7": "Final Video",   "8": "Metadata", "9": "Thumbnail", "10": "YouTube Upload"
            };
            const completedNums = new Set(
              pipelineLog.filter(l => l.done).map(l => l.stage.replace("Stage ", "").split("/")[0])
            );
            const lastActive = [...pipelineLog].reverse().find(l => !l.done && !l.error && l.stage !== "—");
            const currentStageNum = lastActive ? lastActive.stage.replace("Stage ", "").split("/")[0] : null;
            const currentStageName = stageNames[currentStageNum] || "Processing...";
            const lastLog = pipelineLog[pipelineLog.length - 1];
            const mins = Math.floor(elapsedSeconds / 60);
            const secs = elapsedSeconds % 60;
            const elapsedStr = `${mins}m ${String(secs).padStart(2, "0")}s`;

            return (
              <div style={{ marginTop: 20 }}>
                {/* Status card */}
                {pipelineRunning && (
                  <div style={{
                    borderRadius: 10, border: "1px solid #2D6A4F",
                    background: "#0f1f17", padding: "18px 20px", marginBottom: 12,
                  }}>
                    {/* Top row: indicator + elapsed */}
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        {/* Pulsing dot */}
                        <span style={{
                          display: "inline-block", width: 10, height: 10, borderRadius: "50%",
                          background: "#48BB78",
                          boxShadow: "0 0 0 0 rgba(72,187,120,0.6)",
                          animation: "pulse-ring 1.4s ease-out infinite",
                        }} />
                        <span style={{ fontSize: 12, fontWeight: 700, color: "#48BB78", letterSpacing: 1 }}>RUNNING</span>
                      </div>
                      <span style={{ fontSize: 13, color: "#B08D57", fontFamily: "monospace" }}>
                        ⏱ {elapsedStr}
                      </span>
                    </div>

                    {/* Current stage */}
                    <div style={{ marginBottom: 14 }}>
                      <div style={{ fontSize: 11, color: "#6B9E7A", fontWeight: 600, letterSpacing: 0.5, marginBottom: 4 }}>CURRENT STAGE</div>
                      <div style={{ fontSize: 18, fontWeight: 700, color: "#D8F3DC" }}>
                        {currentStageNum && `${currentStageNum}/10 — `}{currentStageName}
                      </div>
                    </div>

                    {/* Stage progress dots */}
                    <div style={{ display: "flex", gap: 6, marginBottom: 14 }}>
                      {[1,2,3,4,5,6,7,8,9,10].map(n => {
                        const s = String(n);
                        const done = completedNums.has(s);
                        const active = s === currentStageNum;
                        return (
                          <div key={n} title={`${n}/10 — ${stageNames[s]}`} style={{
                            flex: 1, height: 6, borderRadius: 3,
                            background: done ? "#2D6A4F" : active ? "#48BB78" : "#1a3a2a",
                            transition: "background 0.4s",
                            boxShadow: active ? "0 0 6px rgba(72,187,120,0.7)" : "none",
                          }} />
                        );
                      })}
                    </div>

                    {/* Last activity */}
                    <div style={{ fontSize: 12, color: "#4a7a5a", borderTop: "1px solid #1a3a2a", paddingTop: 10 }}>
                      <span style={{ color: "#6B9E7A", fontWeight: 600 }}>Last activity </span>
                      <span style={{ fontFamily: "monospace" }}>{lastLog?.time}</span>
                      <span style={{ color: "#D8F3DC", marginLeft: 8 }}>{lastLog?.msg}</span>
                    </div>
                  </div>
                )}

                {/* Pulse animation keyframes injected inline */}
                <style>{`
                  @keyframes pulse-ring {
                    0%   { box-shadow: 0 0 0 0 rgba(72,187,120,0.6); }
                    70%  { box-shadow: 0 0 0 8px rgba(72,187,120,0); }
                    100% { box-shadow: 0 0 0 0 rgba(72,187,120,0); }
                  }
                `}</style>

                {/* Full log — collapsed to last 5 lines by default */}
                <div style={{ borderRadius: 10, border: "1px solid var(--color-border-tertiary)", overflow: "hidden" }}>
                  <div style={{
                    padding: "10px 16px", background: "var(--color-background-secondary)",
                    borderBottom: "1px solid var(--color-border-tertiary)",
                    display: "flex", justifyContent: "space-between", alignItems: "center"
                  }}>
                    <span style={{ fontSize: 12, fontWeight: 600, color: "var(--color-text-secondary)" }}>
                      Pipeline Log {pipelineRunning && <span style={{ color: "#B08D57", marginLeft: 6 }}>● LIVE</span>}
                    </span>
                    <button onClick={() => setLogExpanded(v => !v)} style={{
                      fontSize: 11, color: "var(--color-text-tertiary)", background: "none",
                      border: "none", cursor: "pointer", fontFamily: "inherit", padding: "2px 6px",
                    }}>
                      {logExpanded ? "▲ Collapse" : `▼ Show all (${pipelineLog.length})`}
                    </button>
                  </div>
                  <div style={{ maxHeight: logExpanded ? 500 : 220, overflowY: "auto" }}>
                    {(logExpanded ? pipelineLog : pipelineLog.slice(-5)).map((log, i, arr) => (
                      <div key={i} style={{
                        padding: "8px 16px", fontSize: 12, display: "flex", gap: 10, alignItems: "flex-start",
                        borderBottom: i < arr.length - 1 ? "1px solid var(--color-border-tertiary)" : "none",
                        background: log.done ? "rgba(216,243,220,0.4)" : log.error ? "rgba(255,245,245,0.6)" : "transparent",
                      }}>
                        <span style={{ color: "var(--color-text-tertiary)", fontFamily: "monospace", whiteSpace: "nowrap", marginTop: 1, minWidth: 60 }}>
                          {log.time}
                        </span>
                        <span style={{ color: log.error ? "#9B2C2C" : "#2D6A4F", fontWeight: 600, whiteSpace: "nowrap", marginTop: 1, minWidth: 72 }}>
                          [{log.stage}]
                        </span>
                        <span style={{
                          color: log.done ? "#1B4332" : log.error ? "#9B2C2C" : "var(--color-text-primary)",
                          fontWeight: (log.done || log.error) ? 600 : 400,
                          wordBreak: "break-word",
                        }}>
                          {log.done ? "✓ " : log.error ? "✗ " : ""}{log.msg}
                        </span>
                      </div>
                    ))}
                    <div ref={logEndRef} />
                  </div>
                </div>
              </div>
            );
          })()}
        </div>
      )}

      {/* ================================================================== */}
      {/* TAB: ANALYTICS                                                      */}
      {/* ================================================================== */}
      {tab === "analytics" && (
        <div style={{ padding: "24px 0" }}>

          {/* Header + refresh button */}
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
            <div>
              <div style={{ fontSize: 18, fontWeight: 700, color: "var(--color-text-primary)" }}>Channel Analytics</div>
              <div style={{ fontSize: 12, color: "var(--color-text-tertiary)", marginTop: 2 }}>
                {analyticsData ? `Last 28 days · Fetched ${new Date(analyticsData.fetched_at).toLocaleTimeString()}` : "Last 28 days"}
              </div>
            </div>
            <button
              onClick={fetchAnalytics}
              disabled={analyticsLoading}
              style={{
                padding: "9px 18px", fontSize: 13, fontWeight: 600, borderRadius: 8,
                border: "1px solid #2D6A4F", background: analyticsLoading ? "var(--color-background-secondary)" : "#2D6A4F",
                color: analyticsLoading ? "var(--color-text-secondary)" : "#fff",
                cursor: analyticsLoading ? "default" : "pointer", fontFamily: "inherit",
              }}>
              {analyticsLoading ? "Fetching…" : "Refresh"}
            </button>
          </div>

          {/* Error state */}
          {analyticsError && (
            <div style={{
              padding: "16px", borderRadius: 10, background: "#FFF5F5",
              border: "1px solid #FC8181", color: "#9B2C2C", fontSize: 13, marginBottom: 20,
            }}>
              <strong>Error:</strong> {analyticsError}
              {analyticsError.includes("not installed") && (
                <div style={{ marginTop: 8, fontFamily: "monospace", fontSize: 12, background: "#FED7D7", padding: "6px 10px", borderRadius: 6 }}>
                  pip install google-api-python-client google-auth-oauthlib
                </div>
              )}
            </div>
          )}

          {/* Loading skeleton */}
          {analyticsLoading && !analyticsData && (
            <div style={{ textAlign: "center", padding: 40, color: "var(--color-text-tertiary)", fontSize: 14 }}>
              Connecting to YouTube Analytics…
              <div style={{ fontSize: 12, marginTop: 8 }}>
                If this is your first time, a browser window will open for authentication.
              </div>
            </div>
          )}

          {/* Analytics data */}
          {analyticsData && (
            <>
              {/* Channel summary cards */}
              <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 28 }}>
                {[
                  { label: "VIEWS",          value: analyticsData.channel.views.toLocaleString(),           color: "#2D6A4F" },
                  { label: "WATCH HOURS",    value: analyticsData.channel.watch_hours.toLocaleString(),      color: "#2D6A4F" },
                  { label: "SUBS GAINED",    value: `+${analyticsData.channel.subscribers_gained}`,          color: "#276749" },
                  { label: "NET SUBSCRIBERS",value: (analyticsData.channel.net_subscribers >= 0 ? "+" : "") + analyticsData.channel.net_subscribers,
                    color: analyticsData.channel.net_subscribers >= 0 ? "#276749" : "#9B2C2C" },
                ].map(card => (
                  <div key={card.label} style={{
                    padding: "16px", borderRadius: 10,
                    border: "1px solid var(--color-border-tertiary)",
                    background: "var(--color-background-secondary)",
                  }}>
                    <div style={{ fontSize: 10, fontWeight: 700, color: "var(--color-text-tertiary)", letterSpacing: 0.8, marginBottom: 6 }}>
                      {card.label}
                    </div>
                    <div style={{ fontSize: 22, fontWeight: 700, color: card.color }}>
                      {card.value}
                    </div>
                  </div>
                ))}
              </div>

              {/* Recommendations */}
              {(() => {
                const recs = getRecommendations(analyticsData, usedSceneIds);
                if (recs.length === 0) return null;
                const accentStyles = {
                  green:  { bg: "#D8F3DC", border: "#2D6A4F", iconColor: "#1B4332", titleColor: "#1B4332" },
                  yellow: { bg: "#FEFCBF", border: "#B7791F", iconColor: "#744210", titleColor: "#744210" },
                  red:    { bg: "#FFF5F5", border: "#FC8181", iconColor: "#9B2C2C", titleColor: "#9B2C2C" },
                  blue:   { bg: "#EBF8FF", border: "#63B3ED", iconColor: "#2C5282", titleColor: "#2C5282" },
                };
                return (
                  <div style={{ marginBottom: 28 }}>
                    <div style={{ fontSize: 12, fontWeight: 700, color: "var(--color-text-secondary)", letterSpacing: 0.8, marginBottom: 10 }}>
                      RECOMMENDATIONS
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                      {recs.map((rec, i) => {
                        const s = accentStyles[rec.accent] || accentStyles.blue;
                        return (
                          <div key={i} style={{
                            padding: "14px 16px", borderRadius: 10,
                            background: s.bg, border: `1px solid ${s.border}`,
                          }}>
                            <div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
                              <div style={{ fontSize: 16, color: s.iconColor, lineHeight: 1.3, flexShrink: 0 }}>
                                {rec.icon}
                              </div>
                              <div style={{ flex: 1 }}>
                                <div style={{ fontSize: 13, fontWeight: 700, color: s.titleColor, marginBottom: 4 }}>
                                  {rec.title}
                                </div>
                                <div style={{ fontSize: 13, color: "var(--color-text-primary)", lineHeight: 1.55, marginBottom: 8 }}>
                                  {rec.body}
                                </div>
                                <div style={{
                                  fontSize: 12, fontWeight: 600, color: s.iconColor,
                                  display: "flex", alignItems: "center", gap: 6,
                                }}>
                                  <span>→</span>
                                  {rec.sceneId ? (
                                    <button onClick={() => { setSelectedScene(rec.sceneId); setTab("create"); }}
                                      style={{
                                        background: "none", border: "none", padding: 0, cursor: "pointer",
                                        fontSize: 12, fontWeight: 600, color: s.iconColor,
                                        textDecoration: "underline", fontFamily: "inherit",
                                      }}>
                                      {rec.action}
                                    </button>
                                  ) : (
                                    <span>{rec.action}</span>
                                  )}
                                </div>
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })()}

              {/* Per-video table */}
              {analyticsData.videos.length > 0 ? (
                <div>
                  <div style={{ fontSize: 12, fontWeight: 700, color: "var(--color-text-secondary)", letterSpacing: 0.8, marginBottom: 10 }}>
                    YOUR VIDEOS
                  </div>
                  <div style={{ borderRadius: 10, border: "1px solid var(--color-border-tertiary)", overflow: "hidden" }}>
                    {/* Table header */}
                    <div style={{
                      display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1fr 1fr",
                      padding: "10px 16px", background: "var(--color-background-secondary)",
                      borderBottom: "1px solid var(--color-border-tertiary)",
                      fontSize: 10, fontWeight: 700, color: "var(--color-text-tertiary)", letterSpacing: 0.8,
                    }}>
                      <div>TITLE</div>
                      <div style={{ textAlign: "right" }}>VIEWS</div>
                      <div style={{ textAlign: "right" }}>WATCH HRS</div>
                      <div style={{ textAlign: "right" }}>AVG VIEW %</div>
                      <div style={{ textAlign: "right" }}>LIKES</div>
                    </div>
                    {/* Table rows */}
                    {analyticsData.videos.map((v, i) => (
                      <div key={v.video_id} style={{
                        display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1fr 1fr",
                        padding: "12px 16px", fontSize: 13, alignItems: "center",
                        borderBottom: i < analyticsData.videos.length - 1 ? "1px solid var(--color-border-tertiary)" : "none",
                        background: i % 2 === 0 ? "transparent" : "var(--color-background-secondary)",
                      }}>
                        <div>
                          <a href={v.url} target="_blank" rel="noopener noreferrer"
                            style={{ color: "#2D6A4F", fontWeight: 600, textDecoration: "none", fontSize: 13 }}>
                            {v.title.length > 45 ? v.title.slice(0, 43) + "…" : v.title}
                          </a>
                          {v.published && (
                            <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 2 }}>
                              Published {v.published}
                            </div>
                          )}
                        </div>
                        <div style={{ textAlign: "right", fontWeight: 600 }}>{v.views.toLocaleString()}</div>
                        <div style={{ textAlign: "right" }}>{v.watch_hours.toLocaleString()}</div>
                        <div style={{ textAlign: "right" }}>
                          <span style={{
                            padding: "2px 8px", borderRadius: 12, fontSize: 12, fontWeight: 600,
                            background: v.avg_view_pct >= 40 ? "#D8F3DC" : v.avg_view_pct >= 20 ? "#FEFCBF" : "#FFF5F5",
                            color: v.avg_view_pct >= 40 ? "#1B4332" : v.avg_view_pct >= 20 ? "#744210" : "#9B2C2C",
                          }}>
                            {v.avg_view_pct}%
                          </span>
                        </div>
                        <div style={{ textAlign: "right" }}>{v.likes.toLocaleString()}</div>
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <div style={{
                  padding: "24px", borderRadius: 10, border: "1px solid var(--color-border-tertiary)",
                  textAlign: "center", color: "var(--color-text-tertiary)", fontSize: 13,
                }}>
                  No tracked videos yet. After uploading a video with --upload, it will appear here.
                </div>
              )}
            </>
          )}

          {/* Empty state — no data, not loading, no error */}
          {!analyticsData && !analyticsLoading && !analyticsError && (
            <div style={{
              padding: "40px", textAlign: "center", borderRadius: 10,
              border: "1px solid var(--color-border-tertiary)", color: "var(--color-text-tertiary)",
            }}>
              <div style={{ fontSize: 14, marginBottom: 8 }}>Click Refresh to load your YouTube Analytics.</div>
              <div style={{ fontSize: 12 }}>Requires YouTube OAuth credentials in .env</div>
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
