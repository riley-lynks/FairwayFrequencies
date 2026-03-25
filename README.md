# ⛳ Fairway Frequencies
### AI-Automated LoFi Golf YouTube Channel — Living Painting Pipeline v3

**One command → upload-ready 2-hour video**

```
python fairway.py "Misty dawn, links-style course, coastal cliffs"
```

---

## What This Is

Fairway Frequencies is an automated pipeline that turns a single sentence describing a golf course scene into a complete, upload-ready YouTube video:

- **2–3 hours** of seamless animated anime/Ghibli golf course visuals
- **LoFi music** generated or selected from your library
- **Optional ambient sounds** (rain, birds, wind, golf sounds)
- **YouTube-ready** with title, description, tags, and thumbnail

**The "Living Painting" concept (v3):** Each video is ONE base image, animated with subtle continuous motion — clouds drifting, grass swaying, a flag waving — looped seamlessly for 2–3 hours. The viewer sees one beautiful scene that quietly breathes and lives. Never a cut, never a transition.

---

## Quick Start (5 Steps)

### Step 1: Install Dependencies

```bash
# Python 3.11+ required
pip install -r requirements.txt
```

### Step 2: Set Up API Keys

```bash
# Copy the template
copy .env.example .env     # Windows
cp .env.example .env       # Mac/Linux

# Open .env in any text editor and fill in your keys
# (See "Getting API Keys" section below for links)
```

### Step 3: Verify FFmpeg

FFmpeg must be installed. Check:
```bash
ffmpeg -version
```

If not installed:
- **Windows:** `winget install Gyan.FFmpeg` (then restart your terminal)
- **Mac:** `brew install ffmpeg`
- **Linux:** `sudo apt install ffmpeg`

### Step 4: Run the Smoke Test

```bash
python fairway.py --test
```

This generates a **3-minute test video** to verify everything works. It takes about 15–20 minutes (most of that is waiting for Kling to process clips).

### Step 5: Your First Full Video

**Option A — With Midjourney (recommended quality):**
```bash
# 1. Get the Midjourney prompt for a random scene
python fairway.py --prompts-only --random

# 2. Copy the prompt, generate in Midjourney, save the image to:
#    assets/midjourney_images/

# 3. Run the full pipeline
python fairway.py --random
```

**Option B — Fully automated (hands-off):**
```bash
# Set IMAGE_SOURCE = "flux" in config.py, then:
python fairway.py --random
```

---

## Getting API Keys

| Service | What It's For | Get Your Key |
|---------|---------------|--------------|
| **Anthropic** (required) | Prompt decomposition + metadata | [console.anthropic.com](https://console.anthropic.com/) |
| **Kling** (required) | Video animation from your image | [platform.klingai.com](https://platform.klingai.com/) |
| **BFL/Flux** (optional) | Automated image generation | [api.bfl.ml](https://api.bfl.ml/) |
| **Luma** (optional backup) | Backup video generation | [lumalabs.ai](https://lumalabs.ai/) |
| **Mubert** (optional) | LoFi music generation | [mubert.com/render/pricing](https://mubert.com/render/pricing) |
| **Freesound** (optional) | Ambient golf sounds | [freesound.org/apiv2/apply](https://freesound.org/apiv2/apply/) |

**Minimum required keys:** `ANTHROPIC_API_KEY` + `KLING_ACCESS_KEY` + `KLING_SECRET_KEY`

---

## Command Reference

```bash
# Standard run — generates a 2-hour video
python fairway.py "Misty dawn, links-style course, coastal cliffs"

# Print only the Midjourney prompt (no pipeline run)
python fairway.py --prompts-only "Cherry blossom Japanese golf course"

# Random scene from the 20-scene library
python fairway.py --random

# Show all 20 pre-built scenes
python fairway.py --list-scenes

# Custom duration
python fairway.py "scene" --duration 3.0

# Music only (no ambient golf sounds)
python fairway.py "scene" --no-ambience

# Force character figure in scene
python fairway.py "scene" --character always

# Use Flux API instead of Midjourney
python fairway.py "scene" --images flux

# Upload to YouTube after generation
python fairway.py "scene" --upload

# Resume a failed run
python fairway.py --resume runs/20260318_143201

# Smoke test (3-minute video)
python fairway.py --test
```

---

## Midjourney Workflow

The best quality comes from using Midjourney for the base image. Here's the workflow:

1. **Get the prompt:**
   ```bash
   python fairway.py --prompts-only "your scene description"
   ```

2. **Generate in Midjourney:**
   - Copy the printed prompt
   - Go to midjourney.com or Discord
   - Type `/imagine` and paste the prompt
   - Add: `--ar 16:9 --v 7 --s 750`

3. **Select and save:**
   - Wait for 4 images to generate
   - Pick your favorite (upscale with U1-U4)
   - Right-click the image → Save as
   - Save to: `assets/midjourney_images/`

4. **Run the pipeline:**
   ```bash
   python fairway.py "your scene description"
   ```

**Midjourney Tips:**
- `--s 750` gives high stylization (painterly/anime feel). Try `--s 850` for more anime, `--s 600` for more grounded
- Make sure the image has lots of sky (30%+ of frame) for the cloud animation to work well
- Images with a flag pin look best — the flag waving is very satisfying

---

## Adding Your Own Music

The pipeline checks `assets/music/` for pre-made tracks before using Mubert.

**Recommended: Generate tracks at [suno.com](https://suno.com)**
- Use prompts like: "lofi hip hop, gentle piano, 80 BPM, chill, no lyrics, ambient"
- Download as MP3
- Save to `assets/music/`

The pipeline will randomly select from your library and loop it to fill the video duration. Having 5–10 tracks gives good variety.

---

## The 20-Scene Library

See all scenes:
```bash
python fairway.py --list-scenes
```

| Scene | Description | Mood |
|-------|-------------|------|
| misty_dawn_links | Scottish links, coastal fog, dawn | calm |
| golden_hour_masters | Augusta-style, pink azaleas, golden light | warm |
| rainy_afternoon_parkland | Light rain, lush greens, warm clubhouse | cozy |
| desert_sunrise | Cacti silhouettes, pink sky, sandy bunkers | dramatic |
| autumn_new_england | Peak fall foliage, stone bridge, stream | nostalgic |
| tropical_paradise | Palm trees, turquoise ocean, bright flowers | bright |
| moonlit_fairway | Stars, full moon, silver mist, fireflies | dreamy |
| winter_frost | Frost-covered course, frozen pond, bare trees | serene |
| cherry_blossom_japan | Cherry blossoms, koi pond, pagoda | peaceful |
| coastal_cliffs_sunset | Pacific cliffs, dramatic clouds, sunset | epic |
| english_countryside | Stone walls, sheep, wildflowers, overcast | charming |
| mountain_alpine | Snow peaks, wildflower meadows, mountain stream | majestic |
| foggy_practice_range | Dawn fog, flag markers in mist, dew | meditative |
| storm_approaching | Dark clouds building, golden pre-storm light | moody |
| lakeside_reflection | Mirror lake, perfect reflections, sunrise | tranquil |
| vintage_clubhouse_veranda | Veranda view, roses, afternoon light | nostalgic |
| snowy_holiday | Soft snow falling, warm clubhouse lights | festive |
| summer_afternoon_sprinklers | Sprinkler rainbows, puffy clouds, butterflies | cheerful |
| hawaiian_volcanic | Lava rock, tropical flowers, Pacific ocean | exotic |
| morning_dew_closeup | Dew drops, spider web, misty distance | intimate |

---

## Configuration Reference

Edit `config.py` to customize the pipeline:

| Setting | Default | Description |
|---------|---------|-------------|
| `IMAGE_SOURCE` | `"midjourney"` | `"midjourney"` or `"flux"` |
| `INCLUDE_CHARACTER` | `"random"` | `"always"`, `"never"`, or `"random"` (40% chance) |
| `TARGET_DURATION_HOURS` | `2.0` | Final video length in hours |
| `NUM_ANIMATION_CLIPS` | `10` | Animation variations per video (min: 6) |
| `LOOP_BLEND_SECONDS` | `2` | Crossfade duration between clips |
| `MUSIC_VOLUME` | `0.85` | Music loudness (0.0–1.0) |
| `AMBIENCE_VOLUME` | `0.20` | Ambient sound loudness (0.0–1.0) |
| `INCLUDE_AMBIENCE` | `True` | Whether to add golf ambient sounds |
| `VIDEO_MODEL` | `"kling"` | `"kling"` or `"luma"` |
| `STYLE_SUFFIX` | (anime/Ghibli text) | Appended to every image prompt |

---

## Pipeline Overview

```
Your scene description
        │
        ▼
┌─────────────────┐
│ Stage 1         │  Claude decomposes your prompt into detailed
│ ORCHESTRATOR    │  sub-prompts for every downstream stage
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Stage 2         │  ONE perfect base image (Midjourney or Flux)
│ IMAGE GEN       │  This is what the viewer looks at for 2-3 hours
└────────┬────────┘
         │
    ┌────┴────┐
    ▼         ▼
┌────────┐ ┌────────┐
│ Video  │ │ Audio  │  ← Run in parallel to save time
│ Pipeline│ │ Pipeline│
└────┬───┘ └────┬───┘
     │          │
     ▼          ▼
┌─────────────────┐
│ Stage 3         │  10 animation clips from that ONE image
│ VIDEO GEN       │  (Kling API — ~2-4 min per clip)
└────────┬────────┘    ┌─────────────────┐
         │             │ Stage 5         │  LoFi music track
         │             │ MUSIC GEN       │  (local library or Mubert)
         ▼             └────────┬────────┘
┌─────────────────┐             │
│ Stage 4         │             ▼
│ VIDEO ASSEMBLY  │    ┌─────────────────┐
│ Living Painting │    │ Stage 6         │  Ambient golf sounds
└────────┬────────┘    │ AMBIENT SOUNDS  │  (Freesound API)
         │             └────────┬────────┘
         └──────────┬───────────┘
                    ▼
         ┌─────────────────┐
         │ Stage 7         │  Mix music + ambience
         │ AUDIO ASSEMBLY  │
         └────────┬────────┘
                  ▼
         ┌─────────────────┐
         │ Stage 8         │  Merge video + audio → final MP4
         │ FINAL RENDER    │
         └────────┬────────┘
                  │
         ┌────────┴────────┐
         ▼                 ▼
┌─────────────────┐ ┌─────────────────┐
│ Stage 9         │ │ Stage 10        │
│ METADATA GEN    │ │ THUMBNAIL GEN   │
└─────────────────┘ └─────────────────┘
                  │
                  ▼ (optional)
         ┌─────────────────┐
         │ Stage 11        │  --upload flag
         │ YOUTUBE UPLOAD  │
         └─────────────────┘
```

---

## YouTube Upload Setup

YouTube upload requires Google OAuth. It's a bit involved to set up once, then automatic.

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or use existing)
3. Enable "YouTube Data API v3"
4. Create OAuth 2.0 credentials (Desktop app)
5. Download the client ID and secret
6. Add to `.env`:
   ```
   YOUTUBE_CLIENT_ID=your_client_id
   YOUTUBE_CLIENT_SECRET=your_client_secret
   ```

First time you use `--upload`, a browser window will open asking you to log in to your YouTube account. After that, it's automatic.

**Note:** Videos upload as **unlisted** by default. Change to Public in YouTube Studio after reviewing.

---

## Troubleshooting

**"FFmpeg not found"**
```bash
# Windows — install and restart terminal:
winget install Gyan.FFmpeg
```

**"No images found in assets/midjourney_images/"**
```bash
# Get the Midjourney prompt for your scene:
python fairway.py --prompts-only "your scene"
# Generate in Midjourney, save .png to assets/midjourney_images/
# Or switch to automated: set IMAGE_SOURCE = "flux" in config.py
```

**"Kling clip generation failed"**
- Check your KLING_ACCESS_KEY and KLING_SECRET_KEY in .env
- Kling may be rate limiting — wait a few minutes
- Resume the run: `python fairway.py --resume runs/[your-run-id]`

**"Not enough clips to proceed (need 6 minimum)"**
- Check Kling API logs for specific error
- Your image may have been flagged — try a different image
- Fall back to Luma: set VIDEO_MODEL = "luma" in config.py

**"Music generation failed"**
- Add MP3 tracks to `assets/music/` (download from suno.com)
- Or set your Mubert API key in .env

**Pipeline interrupted mid-run**
```bash
# Resume from where it stopped:
python fairway.py --resume runs/20260318_143201
# (use the run ID from when it started — shown in the progress output)
```

---

## Cost Estimates

For a typical 2-hour video:

| Service | Usage | Approximate Cost |
|---------|-------|-----------------|
| Anthropic (Claude) | 2 API calls | ~$0.01 |
| Black Forest Labs (Flux) | 3 images | ~$0.15 (if using Flux) |
| Kling | 10 clips × 10 sec | ~$0.50–$1.50 |
| Mubert | 1 track | ~$0.10 (if using Mubert) |
| Freesound | Download previews | Free |
| **Total** | | **~$0.60–$1.70/video** |

Using Midjourney images saves the Flux cost but adds Midjourney subscription cost.

---

## Project Structure

```
fairway/
├── fairway.py                    ← START HERE — main entry point
├── config.py                     ← All settings and API keys
├── .env                          ← Your API keys (never share this!)
├── .env.example                  ← Template for .env
├── requirements.txt              ← Python packages to install
├── setup.sh                      ← One-command setup script
├── README.md                     ← This file
│
├── pipeline/                     ← All the production stage modules
│   ├── orchestrator.py           ← Stage 1: Claude prompt decomposition
│   ├── image_gen.py              ← Stage 2a: Flux API image generation
│   ├── image_import.py           ← Stage 2b: Midjourney image import
│   ├── video_gen.py              ← Stage 3: Kling animation clips
│   ├── video_gen_luma.py         ← Stage 3 backup: Luma Ray 3
│   ├── video_assembly.py         ← Stage 4: Living painting assembly
│   ├── music_gen.py              ← Stage 5: LoFi music
│   ├── ambient_sounds.py         ← Stage 6: Golf ambient sounds
│   ├── audio_assembly.py         ← Stage 7: Mix music + ambience
│   ├── final_render.py           ← Stage 8: Merge video + audio
│   ├── metadata_gen.py           ← Stage 9: YouTube title/desc/tags
│   ├── thumbnail_gen.py          ← Stage 10: Thumbnail image
│   └── youtube_upload.py         ← Stage 11: Optional upload
│
├── prompts/
│   ├── orchestrator_system.txt   ← Claude's art direction instructions
│   ├── metadata_system.txt       ← Claude's YouTube SEO instructions
│   └── scene_library.json        ← 20 pre-built scene prompts
│
├── assets/
│   ├── midjourney_images/        ← Drop your Midjourney images here
│   ├── music/                    ← Drop your Suno LoFi tracks here
│   └── sounds/                   ← Auto-filled by Freesound downloader
│
├── output/                       ← Finished videos, thumbnails, metadata
├── runs/                         ← Per-run working directories (auto-created)
└── logs/                         ← Generation logs
```

---

*Fairway Frequencies — Where Golf Meets LoFi* ⛳
