# app/pipeline/burner.py

import subprocess
import platform
from .base import SubtitleBurner

# class FFmpegBurner(SubtitleBurner):
#     def burn(self, video_path, srt_path, output_path, device=None):
#         if not device:
#             system = platform.system()
#             if system == "Darwin":
#                 device = "videotoolbox"
#             else:
#                 device = "cuda"  # fallback to CPU if cuda not available
#
#         if device == "videotoolbox":
#             cmd = [
#                 "ffmpeg", "-y", "-i", video_path,
#                 "-vf", f"subtitles={srt_path}:force_style='FontName=Arial'",
#                 "-c:v", "h264_videotoolbox", "-c:a", "copy", output_path
#             ]
#         elif device == "cuda":
#             cmd = [
#                 "ffmpeg", "-y", "-hwaccel", "cuda", "-i", video_path,
#                 "-vf", f"subtitles={srt_path}:force_style='FontName=Arial'",
#                 "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "18",
#                 "-c:a", "copy", output_path
#             ]
#         else:
#             cmd = [
#                 "ffmpeg", "-y", "-i", video_path,
#                 "-vf", f"subtitles={srt_path}:force_style='FontName=Arial'",
#                 "-c:v", "libx264", "-preset", "fast", "-crf", "18",
#                 "-c:a", "copy", output_path
#             ]
#         subprocess.run(cmd, check=True)

def get_video_height(video_path):
    import cv2
    cap = cv2.VideoCapture(video_path)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    return height

class FFmpegBurner(SubtitleBurner):
    def burn(self, video_path, srt_path, output_path, device=None, mask_percent=0.25,masked=False):
        import platform
        import subprocess

        # Font settings
        font_name = "Arial"
        alignment = 2  # bottom-center
        # Calculate vertical margin to center subs in the masked area
        # Approximate: MarginV = half of the masked area height in pixels
        # (Will work for 720p/1080p and up; you can auto-calculate if you want)
        # margin_v = 80  # Default for 1080p and mask_percent=0.25. Adjust for your videos!
        video_height = get_video_height(video_path)
        if masked:
            margin_v = int(video_height * mask_percent / 2)
            force_style = f"FontName={font_name},Alignment={alignment},MarginV={margin_v}"
        else:
            margin_v = 40
            force_style = f"FontName={font_name}"

        # force_style = f"FontName={font_name},Alignment={alignment},MarginV={margin_v}"

        if not device:
            system = platform.system()
            if system == "Darwin":
                device = "videotoolbox"
            else:
                device = "cuda"  # fallback to CPU if cuda not available

        vf_arg = f"subtitles='{srt_path}':force_style='{force_style}'"

        if device == "videotoolbox":
            cmd = [
                "ffmpeg", "-y", "-i", video_path,
                "-vf", vf_arg,
                "-c:v", "h264_videotoolbox", "-c:a", "copy", output_path
            ]
        elif device == "cuda":
            cmd = [
                "ffmpeg", "-y", "-hwaccel", "cuda", "-i", video_path,
                "-vf", vf_arg,
                "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "18",
                "-c:a", "copy", output_path
            ]
        else:
            cmd = [
                "ffmpeg", "-y", "-i", video_path,
                "-vf", vf_arg,
                "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                "-c:a", "copy", output_path
            ]
        subprocess.run(cmd, check=True)
