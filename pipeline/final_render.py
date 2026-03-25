# =============================================================================
# pipeline/final_render.py — Final Video + Audio Merge
# =============================================================================
# PURPOSE:
#   Merge the assembled video (from video_assembly.py) and the mixed audio
#   (from audio_assembly.py) into the final upload-ready MP4 file.
#
# WHY a separate module for this? The video and audio pipelines run in parallel
# (see fairway.py). They must both finish before we can merge them. Having
# this as a separate stage makes the dependency clear and keeps the code clean.
#
# THE TRICK: -c:v copy
#   When merging video + audio, we use "-c:v copy" which tells FFmpeg to
#   NOT re-encode the video. The video was already encoded at high quality
#   in video_assembly.py. Re-encoding it would:
#   - Take 10-30 minutes (slow!)
#   - Reduce quality (every encode degrades the video slightly)
#   - Serve no purpose (we're just adding audio)
#   With "-c:v copy", the video stream is passed through unchanged.
# =============================================================================

import os
import subprocess
import logging

logger = logging.getLogger("fairway.final_render")


def render_final_video(
    video_path: str,
    audio_path: str,
    output_path: str,
    logger: logging.Logger = None,
) -> str:
    """
    Merge the assembled video and mixed audio into the final MP4.

    This is Stage 8 of the pipeline — the last FFmpeg operation.
    It takes the muted video (all our animation work) and the mixed
    audio (LoFi music + optional ambience) and combines them.

    Args:
        video_path:  Path to the assembled video (no audio track).
        audio_path:  Path to the mixed audio file.
        output_path: Where to save the final video.
        logger:      Logger for progress messages.

    Returns:
        Path to the final video file (same as output_path).

    Raises:
        RuntimeError: If FFmpeg fails or input files don't exist.
    """
    local_logger = logger or logging.getLogger("fairway.final_render")

    # Verify inputs exist before calling FFmpeg
    if not os.path.exists(video_path):
        raise RuntimeError(f"Video file not found: {video_path}")
    if not os.path.exists(audio_path):
        raise RuntimeError(f"Audio file not found: {audio_path}")

    # Ensure the output directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    local_logger.info(f"  Merging video + audio...")
    local_logger.debug(f"  Video: {video_path}")
    local_logger.debug(f"  Audio: {audio_path}")
    local_logger.debug(f"  Output: {output_path}")

    # FFmpeg command explanation:
    # -i video_path     : input 1 — the video (no audio)
    # -i audio_path     : input 2 — the audio
    # -c:v copy         : DON'T re-encode video — copy it straight through
    # -c:a aac          : Encode audio as AAC (YouTube's preferred audio codec)
    # -b:a 192k         : Audio bitrate (192kbps = high quality, small size)
    # -shortest         : Stop when the shorter stream ends
    #                     (protects against audio/video length mismatch)
    # -movflags +faststart : Move MP4 metadata to the start of the file
    #                        WHY: This lets YouTube start processing before the
    #                        upload is complete, and lets viewers start watching
    #                        before the video fully downloads (streaming)
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", audio_path,
        "-c:v", "copy",          # Video pass-through (no quality loss)
        "-c:a", "aac",           # Encode audio as AAC
        "-b:a", "192k",          # 192kbps audio bitrate
        "-shortest",             # End at the shorter of the two streams
        "-movflags", "+faststart",  # Optimize for streaming
        output_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        file_size_gb = os.path.getsize(output_path) / (1024**3)
        local_logger.info(f"  ✓ Final render complete: {file_size_gb:.2f}GB")
        return output_path

    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"Final render (FFmpeg merge) failed:\n"
            f"Error: {e.stderr[-500:]}\n"
            "Check that both the video and audio files are valid."
        )
