import os


import subprocess
import json






def burn(video_path, srt_path, output_path, device=None, mask_percent=0.25,masked=False):
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


def mux_srt_into_video(video_in, srt_path, video_out):
    # Output container must support soft subs (MKV always, MP4 with mov_text)
    import subprocess
    ext = os.path.splitext(video_out)[1].lower()
    # For .mkv you can mux srt directly. For .mp4, you need to convert to mov_text.
    if ext == ".mkv":
        cmd = [
            "ffmpeg", "-y", "-i", video_in, "-i", srt_path,
            "-c", "copy", "-c:s", "srt", "-map", "0", "-map", "1", video_out
        ]
    elif ext == ".mp4":
        # Convert srt to mov_text for MP4
        cmd = [
            "ffmpeg", "-y", "-i", video_in, "-i", srt_path,
            "-c:v", "copy", "-c:a", "copy", "-c:s", "mov_text", "-map", "0", "-map", "1", video_out
        ]
    elif ext == ".avi":
        # AVI does not support soft subs, use MKV instead
        video_out = os.path.splitext(video_out)[0] + ".mkv"
        cmd = [
            "ffmpeg", "-y", "-i", video_in, "-i", srt_path,
            "-c", "copy", "-c:s", "srt", "-map", "0", "-map", "1", video_out
        ]
    else:
        # Default to MKV muxing
        video_out = os.path.splitext(video_out)[0] + ".mkv"
        cmd = [
            "ffmpeg", "-y", "-i", video_in, "-i", srt_path,
            "-c", "copy", "-c:s", "srt", "-map", "0", "-map", "1", video_out
        ]
    subprocess.run(cmd, check=True)
    return video_out


def mux_multiple_srts_into_mkv(video_in, srt_paths, video_out):
    """
    srt_paths: list of tuples (lang_code, srt_path)
    """
    import subprocess

    cmd = ["ffmpeg", "-y", "-i", video_in]
    # Add all srt files as inputs
    for _, srt_path in srt_paths:
        cmd += ["-i", srt_path]
    cmd += ["-c", "copy"]
    # For each srt, add a mapping, and assign language/label
    # First stream is video_in, srt files are inputs 1,2,3...
    # "-map 0" maps all streams from the original video
    cmd += ["-map", "0"]
    for idx, (lang, _) in enumerate(srt_paths):
        cmd += ["-map", str(idx + 1)]
    # Subtitle codecs: srt
    cmd += ["-c:s", "srt"]
    # Set language for each srt stream
    for idx, (lang, _) in enumerate(srt_paths):
        cmd += [f"-metadata:s:s:{idx}", f"language={lang}"]
    cmd += [video_out]

    subprocess.run(cmd, check=True)
    return video_out


def analyze_media(file_path):
    cmd = [
        'ffprobe', '-v', 'quiet', '-print_format', 'json',
        '-show_format', '-show_streams', '-show_chapters', file_path
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("ffprobe failed")
    return json.loads(proc.stdout)


def get_video_height(video_path):
    import cv2
    cap = cv2.VideoCapture(video_path)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    return height

def mask_subtitle_area(self, input_video, output_video, percent=0.15, color="black"):
    import subprocess
    filter_str = f"drawbox=y=ih*(1-{percent}):w=iw:h=ih*{percent}:color={color}@1.0:t=fill"
    subprocess.run([
        "ffmpeg", "-y", "-i", input_video,
        "-vf", filter_str,
        "-c:a", "copy", output_video
    ], check=True)



