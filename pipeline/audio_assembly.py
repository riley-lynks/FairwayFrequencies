# =============================================================================
# pipeline/audio_assembly.py — Audio Mix and Assembly
# =============================================================================
# PURPOSE:
#   Combine the LoFi music track and optional ambient sounds into a single
#   mixed audio file, then normalize the result for YouTube.
#
# MIX STRATEGY:
#   - Music:   MUSIC_VOLUME = 0.85 (dominant — this is a LoFi music channel)
#   - Ambience: AMBIENCE_VOLUME = 0.20 (subtle — felt, not heard prominently)
#   - Final normalization to -14 LUFS (YouTube's standard)
#
# WHY separate this from music_gen.py? Single Responsibility Principle.
# music_gen.py gets the music. ambient_sounds.py gets the ambience.
# audio_assembly.py MIXES them. Each module does one thing — easier to
# debug and test independently.
# =============================================================================

import os
import subprocess
import logging
import json

import config

logger = logging.getLogger("fairway.audio_assembly")

TARGET_LUFS = -14.0  # YouTube's target loudness level


def assemble_audio(
    music_path: str,
    ambient_path: str,
    target_duration_hours: float,
    music_volume: float,
    ambience_volume: float,
    audio_dir: str,
    logger: logging.Logger = None,
) -> str:
    """
    Mix music and ambient sounds into the final audio track.

    Uses FFmpeg's amix filter to blend the two audio streams at the
    specified volume levels, then normalizes the result.

    Args:
        music_path:           Path to the LoFi music file.
        ambient_path:         Path to the ambient sounds file (or None if disabled).
        target_duration_hours: How long the audio should be.
        music_volume:         Music volume (0.0-1.0). Default: 0.85
        ambience_volume:      Ambient volume (0.0-1.0). Default: 0.20
        audio_dir:            Directory to save the mixed audio.
        logger:               Logger for progress messages.

    Returns:
        Path to the final mixed audio file.
    """
    local_logger = logger or logging.getLogger("fairway.audio_assembly")
    target_seconds = target_duration_hours * 3600

    output_path = os.path.join(audio_dir, "final_audio.wav")

    if ambient_path and os.path.exists(ambient_path):
        local_logger.info(
            f"  Mixing music ({music_volume*100:.0f}%) + "
            f"ambience ({ambience_volume*100:.0f}%)..."
        )
        _mix_music_and_ambience(
            music_path=music_path,
            ambient_path=ambient_path,
            music_volume=music_volume,
            ambience_volume=ambience_volume,
            target_seconds=target_seconds,
            output_path=output_path,
        )
    else:
        local_logger.info("  No ambient sounds — using music track only...")
        _trim_music_only(
            music_path=music_path,
            target_seconds=target_seconds,
            output_path=output_path,
        )

    local_logger.info(f"  ✓ Mixed audio ready: {output_path}")
    return output_path


def _mix_music_and_ambience(
    music_path: str,
    ambient_path: str,
    music_volume: float,
    ambience_volume: float,
    target_seconds: float,
    output_path: str,
):
    """
    Mix music and ambient sounds using FFmpeg's amix filter.

    The amix filter takes multiple audio inputs and blends them.
    We also apply volume adjustments to each stream independently.

    Args:
        music_path:      Music audio file.
        ambient_path:    Ambient audio file.
        music_volume:    Music loudness multiplier (0.85 = 85% volume).
        ambience_volume: Ambient loudness multiplier (0.20 = 20% volume).
        target_seconds:  Output duration.
        output_path:     Where to save the mix.
    """
    # FFmpeg filter explanation:
    # [0:a]volume={music_volume}[music]   — adjust music volume
    # [1:a]volume={ambience_volume}[amb]  — adjust ambient volume
    # [music][amb]amix=inputs=2:duration=first  — mix both streams
    # duration=first = use the first input's duration (music)
    # loudnorm = normalize to YouTube target

    filter_complex = (
        f"[0:a]volume={music_volume}[music];"
        f"[1:a]volume={ambience_volume}[amb];"
        f"[music][amb]amix=inputs=2:duration=first,"
        f"afade=t=in:st=0:d=10,"
        f"loudnorm=I={TARGET_LUFS}:LRA=11:TP=-1.5[out]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", music_path,
        "-i", ambient_path,
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-t", str(target_seconds),
        "-ar", "44100",
        "-ac", "2",
        "-c:a", "pcm_s16le",
        output_path,
    ]

    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Audio mixing failed: {e.stderr[-400:]}")


def _trim_music_only(music_path: str, target_seconds: float, output_path: str):
    """
    When no ambient sounds are available, just trim the music to duration.

    Args:
        music_path:     Music audio file.
        target_seconds: Output duration.
        output_path:    Where to save it.
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", music_path,
        "-t", str(target_seconds),
        "-af", f"afade=t=in:st=0:d=10,loudnorm=I={TARGET_LUFS}:LRA=11:TP=-1.5",
        "-ar", "44100",
        "-ac", "2",
        "-c:a", "pcm_s16le",
        output_path,
    ]

    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Audio trim failed: {e.stderr[-400:]}")
