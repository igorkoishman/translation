# app/pipeline/burner.py

import subprocess
import platform
from .base import SubtitleBurner

class FFmpegBurner(SubtitleBurner):
    def burn(self, video_path, srt_path, output_path, device=None):
        if not device:
            system = platform.system()
            if system == "Darwin":
                device = "videotoolbox"
            else:
                device = "cuda"  # fallback to CPU if cuda not available

        if device == "videotoolbox":
            cmd = [
                "ffmpeg", "-y", "-i", video_path,
                "-vf", f"subtitles={srt_path}:force_style='FontName=Arial'",
                "-c:v", "h264_videotoolbox", "-c:a", "copy", output_path
            ]
        elif device == "cuda":
            cmd = [
                "ffmpeg", "-y", "-hwaccel", "cuda", "-i", video_path,
                "-vf", f"subtitles={srt_path}:force_style='FontName=Arial'",
                "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "18",
                "-c:a", "copy", output_path
            ]
        else:
            cmd = [
                "ffmpeg", "-y", "-i", video_path,
                "-vf", f"subtitles={srt_path}:force_style='FontName=Arial'",
                "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                "-c:a", "copy", output_path
            ]
        subprocess.run(cmd, check=True)
