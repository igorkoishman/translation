import os
import shutil
import subprocess
import platform
import textwrap
import requests
import srt
import whisperx
import ssl
import logging
import torch
import glob
import importlib.util
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO)
print("DEBUG: Starting subtitle tool...")

def google_translate_text(text, target='he', api_key=None):
    url = "https://translation.googleapis.com/language/translate/v2"
    params = {"q": text, "target": target, "format": "text", "key": api_key}
    response = requests.post(url, data=params, verify=False)
    response.raise_for_status()
    return response.json()['data']['translations'][0]['translatedText']

def extract_audio(video_path, audio_path):
    subprocess.run([
        'ffmpeg', '-y', '-i', video_path,
        '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le',
        audio_path
    ], check=True)

def flatten_whisper_snapshot(model_base_dir: str):
    snapshot_pattern = os.path.join(model_base_dir, "models--*--faster-whisper-*", "snapshots", "*")
    snapshot_dirs = glob.glob(snapshot_pattern)
    if not snapshot_dirs:
        print("❌ No snapshot directory found.")
        return
    snapshot_dir = snapshot_dirs[0]
    print(f"📦 Flattening snapshot: {snapshot_dir}")
    for item in os.listdir(snapshot_dir):
        src = os.path.join(snapshot_dir, item)
        dst = os.path.join(model_base_dir, item)
        if os.path.exists(dst):
            continue
        if os.path.islink(src):
            shutil.copy(os.path.realpath(src), dst)
        elif os.path.isfile(src):
            shutil.copy(src, dst)
        elif os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
    for folder in glob.glob(os.path.join(model_base_dir, "models--*")):
        shutil.rmtree(folder, ignore_errors=True)
    print("✅ Flatten complete.")

def build_model_path(models_root: str, backend_name: str, model_size: str) -> str:
    """
    Compose the full model path: e.g. /models/faster-whisper-small
    """
    folder_name = f"{backend_name}-{model_size}"
    full_path = os.path.join(models_root, folder_name)
    return full_path


def get_faster_whisper_model_path(models_root: str, backend_name: str, model_size: str, device="cuda") -> str:
    model_path = build_model_path(models_root, backend_name, model_size)
    if isinstance(model_size, set):
        model_size = next(iter(model_size))  # Get the first (and only) element
    if not os.path.isdir(model_path) or not os.listdir(model_path):
        print(f"⬇️ Model directory missing or empty, downloading faster-whisper model: {model_path}")

        os.makedirs(model_path, exist_ok=True)

        # Disable SSL verification for HF hub if needed (optional)
        os.environ["HF_HUB_DISABLE_SSL_VERIFICATION"] = "1"
        ssl._create_default_https_context = ssl._create_unverified_context

        compute_type = "int8_float32" if device.startswith("cuda") else "float32"

        # Trigger download by loading model with local_files_only=False
        whisperx.load_model(
            model_size,
            device=device,
            compute_type=compute_type,
            download_root=model_path,
            local_files_only=False
        )

        # Now flatten snapshot folder so model is usable
        flatten_whisper_snapshot(model_path)
    else:
        print(f"✅ Found local faster-whisper model at: {model_path}")

    return model_path

def transcribe_audio_faster_whisper(audio_path: str, models_root: str, backend_name: str, model_size: str,
                                    device="cuda", language=None, align_output=True):
    logging.info(f"CUDA available: {torch.cuda.is_available()}")
    logging.info(f"CUDA device: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'}")
    model_path = get_faster_whisper_model_path(models_root, backend_name, model_size,device=device)
    print(f"🧠 Loading faster-whisper model from: {model_path}")

    compute_type = "int8_float32" if device.startswith("cuda") else "float32"

    model = whisperx.load_model(
        model_path,
        device=device,
        compute_type=compute_type,
        local_files_only=True
    )

    result = model.transcribe(audio_path, language=language)

    if align_output:
        print(f"Aliging Rows")
        try:
            model_a, metadata = whisperx.load_align_model(language_code=result["language"], device=device)
            result = whisperx.align(result["segments"], model_a, metadata, audio_path, device)
        except Exception as e:
            print(f"⚠️ Alignment failed: {e}")

    return result

def create_srt(segments, srt_path, to_language=None, do_translate=False, api_key=None,
               max_chars=80, max_lines=2, max_duration=5.0):
    print(f"📄 Writing SRT: {srt_path} ({'translated' if do_translate else 'original'})")
    subs, idx = [], 1
    for seg in segments:
        start, end = seg.get('start'), seg.get('end')
        text = seg.get('text', '').strip()
        if start is None or end is None or not text:
            continue
        if do_translate and to_language:
            try:
                text = google_translate_text(text, target=to_language, api_key=api_key)
            except Exception as e:
                print(f"Translation error: {e}")
        seg_duration = end - start
        lines = textwrap.wrap(text, width=max_chars)
        n_blocks = max(1, (len(lines) + max_lines - 1) // max_lines)
        if seg_duration > max_duration and n_blocks > 1:
            for i in range(n_blocks):
                sub_lines = lines[i * max_lines: (i + 1) * max_lines]
                subs.append(srt.Subtitle(
                    index=idx,
                    start=srt.timedelta(seconds=start + (seg_duration * i / n_blocks)),
                    end=srt.timedelta(seconds=start + (seg_duration * (i + 1) / n_blocks)),
                    content='\n'.join(sub_lines)
                ))
                idx += 1
        else:
            for i in range(0, len(lines), max_lines):
                sub_lines = lines[i:i + max_lines]
                subs.append(srt.Subtitle(
                    index=idx,
                    start=srt.timedelta(seconds=start),
                    end=srt.timedelta(seconds=end),
                    content='\n'.join(sub_lines)
                ))
                idx += 1
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(srt.compose(subs))

# def burn_subtitles(video_path, srt_path, output_path,device):
#     # cmd = [
#     #     'ffmpeg', '-y', '-i', video_path,
#     #     '-vf', f"subtitles={srt_path}:force_style='FontName=Arial'",
#     #     '-c:a', 'copy', output_path
#     # ]
#
#     if device == 'cpu':
#         cmd = [
#             'ffmpeg', '-y', '-i', video_path,
#             '-vf', f"subtitles={srt_path}:force_style='FontName=Arial'",
#             '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
#             '-c:a', 'copy',
#             output_path
#         ]
#     else:
#         cmd = [
#             'ffmpeg', '-y', '-hwaccel', 'cuda', '-i', video_path,
#             '-vf', f"subtitles={srt_path}:force_style='FontName=Arial'",
#             '-c:v', 'h264_nvenc', '-preset', 'p4', '-cq', '18',
#             '-c:a', 'copy',
#             output_path
#         ]
#     subprocess.run(cmd, check=True)

def main(video_path, output_path_base, model_name_or_dir, model_name, backend,
         output_languages=None, api_key=None, device="cuda", language=None):
    import tempfile
    import shutil
    ml_device, video_device = resolve_device(device)
    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"🔧 Working in temp dir: {tmpdir}")

        # Extract audio from video
        audio_path = os.path.join(tmpdir, "audio.wav")
        extract_audio(video_path, audio_path)

        # Compose full model path
        # if model_name == "faster-whisper":
        #     model_path = build_model_path(model_name_or_dir, model_name, backend)
        # elif model_name == "openai-whisper":
        #     openai_whisper = load_openai_whisper()
        # else:
        #     raise ValueError(f"Unsupported model backend: {model_name}")

        # print(f"Loading model from {model_path}")
        # print(f"🎙️ Transcribing and aligning with model at: {model_path}")

        # Transcribe audio
        if model_name == "faster-whisper":
            model_path = build_model_path(model_name_or_dir, model_name, backend)
            print(f"Loading model from {model_path}")
            print(f"🎙️ Transcribing and aligning with model at: {model_path}")
            result = transcribe_audio_faster_whisper(
                audio_path,
                models_root=model_name_or_dir,
                backend_name=model_name,
                model_size=backend,
                device=ml_device,
                language=language,
                align_output=True
            )
        elif model_name == "openai-whisper":
             import importlib
             openai_whisper = load_openai_whisper()
             # openai_whisper = importlib.import_module("whisper")
             # model = openai_whisper.load_model(backend, device=ml_device)
             transcribed = openai_whisper.transcribe(audio_path, language=language)
             result = {
                 "segments": transcribed["segments"],
                 "language": transcribed.get("language", language or "und")
             }
             # Optional: align result using whisperx alignment tools
             if True:  # or align_output flag
                 model_a, metadata = whisperx.load_align_model(
                     language_code=result["language"], device=ml_device)
                 result = whisperx.align(result["segments"], model_a, metadata, audio_path, ml_device)

             else:
                 raise ValueError("❌ Invalid model_name. Must be 'faster-whisper' or 'openai-whisper'.")

        srt_paths = {}

        # Create original subtitles (no translation)
        srt_orig = os.path.join(tmpdir, "subtitles_orig.srt")
        create_srt(result["segments"], srt_orig)
        srt_paths["orig"] = srt_orig
        _, ext = os.path.splitext(video_path)
        # For each requested language, create translated subtitles and burn them into video
        if output_languages:
            for lang in output_languages:
                srt_lang = os.path.join(tmpdir, f"subtitles_{lang}.srt")
                create_srt(result["segments"], srt_lang,
                           to_language=lang, do_translate=True, api_key=api_key)
                srt_paths[lang] = srt_lang

                # Generate output video path with language suffix
                out_video = os.path.splitext(output_path_base)[0] + f"_{lang}{ext}"
                # out_video = os.path.splitext(output_path_base)[0] + f"_{lang}.mp4"

                # Burn translated subtitles into the video
                burn_subtitles(video_path, srt_lang, out_video,device=video_device)
                print(f"✅ Done with {lang}: {out_video}")

        # Burn original subtitles into video
        # out_video_orig = os.path.splitext(output_path_base)[0] + "_orig.mp4"
        out_video_orig = os.path.splitext(output_path_base)[0] + f"_orig{ext}"
        burn_subtitles(video_path, srt_paths["orig"], out_video_orig)
        print(f"🎬 Done with original subtitles: {out_video_orig}")

        # Move all generated SRT files from temp directory to final location
        for lang, path in srt_paths.items():
            final_srt_path = os.path.splitext(output_path_base)[0] + f"_{lang}.srt"
            shutil.move(path, final_srt_path)
            print(f"💾 Saved subtitle file: {final_srt_path}")


def has_cuda_nvenc():
    """Check if ffmpeg supports CUDA/NVENC."""
    try:
        result = subprocess.check_output(['ffmpeg', '-encoders'], stderr=subprocess.STDOUT, text=True)
        return 'h264_nvenc' in result
    except subprocess.CalledProcessError:
        return False
# worked
# def burn_subtitles(video_path, srt_path, output_path, device=None):
#     device = resolve_device(device)
#
#     if device == 'cuda':
#         cmd = [
#             'ffmpeg', '-y', '-hwaccel', 'cuda', '-i', video_path,
#             '-vf', f"subtitles={srt_path}:force_style='FontName=Arial'",
#             '-c:v', 'h264_nvenc', '-preset', 'p4', '-cq', '18',
#             '-c:a', 'copy',
#             output_path
#         ]
#     else:
#         cmd = [
#             'ffmpeg', '-y', '-i', video_path,
#             '-vf', f"subtitles={srt_path}:force_style='FontName=Arial'",
#             '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
#             '-c:a', 'copy',
#             output_path
#         ]
#
#     subprocess.run(cmd, check=True)

def burn_subtitles(video_path, srt_path, output_path, device=None):
    device = resolve_device(device)

    if device == 'videotoolbox':
        cmd = [
            'ffmpeg', '-y', '-i', video_path,
            '-vf', f"subtitles={srt_path}:force_style='FontName=Arial'",
            '-c:v', 'h264_videotoolbox',
            '-c:a', 'copy',
            output_path
        ]
    elif device == 'cuda':
        cmd = [
            'ffmpeg', '-y', '-hwaccel', 'cuda', '-i', video_path,
            '-vf', f"subtitles={srt_path}:force_style='FontName=Arial'",
            '-c:v', 'h264_nvenc', '-preset', 'p4', '-cq', '18',
            '-c:a', 'copy',
            output_path
        ]
    else:
        cmd = [
            'ffmpeg', '-y', '-i', video_path,
            '-vf', f"subtitles={srt_path}:force_style='FontName=Arial'",
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
            '-c:a', 'copy',
            output_path
        ]

    subprocess.run(cmd, check=True)


# def burn_subtitles(video_path, srt_path, output_path, device=None):
#     # Auto-determine device if not specified
#     if device is None:
#         if platform.system() == 'Darwin':
#             # macOS: CUDA not supported
#             device = 'cpu'
#         elif has_cuda_nvenc():
#             device = 'cuda'
#         else:
#             device = 'cpu'
#
#     if device == 'cuda':
#         cmd = [
#             'ffmpeg', '-y', '-hwaccel', 'cuda', '-i', video_path,
#             '-vf', f"subtitles={srt_path}:force_style='FontName=Arial'",
#             '-c:v', 'h264_nvenc', '-preset', 'p4', '-cq', '18',
#             '-c:a', 'copy',
#             output_path
#         ]
#     else:
#         cmd = [
#             'ffmpeg', '-y', '-i', video_path,
#             '-vf', f"subtitles={srt_path}:force_style='FontName=Arial'",
#             '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
#             '-c:a', 'copy',
#             output_path
#         ]
#
#     subprocess.run(cmd, check=True)

# worked
# def resolve_device(device: str = None) -> str:
#     """Normalize device selection across OSes and environments."""
#     if platform.system() == 'Darwin':
#         # macOS never supports CUDA
#         return 'cpu'
#     if device == 'cuda':
#         if has_cuda_nvenc() and torch.cuda.is_available():
#             return 'cuda'
#         else:
#             print("⚠️ CUDA requested but not available. Falling back to CPU.")
#             return 'cpu'
#     return device or 'cpu'

# def resolve_device(device: str = None) -> str:
#     import platform
#     import torch
#
#     if device:  # Explicit user preference
#         if device == "cuda" and torch.cuda.is_available():
#             return "cuda"
#         return "cpu"
#
#     if platform.system() == 'Darwin':
#         return 'cpu'
#
#     if torch.cuda.is_available():
#         return 'cuda'
#
#     return 'cpu'

# def resolve_device(device: str = None) -> str:
#     import platform
#     import torch
#
#     system = platform.system()
#
#     # if device:  # User-specified
#     #     if device == "cuda" and torch.cuda.is_available():
#     #         return "cuda"
#     #     elif device == "videotoolbox":
#     #         return "videotoolbox"
#     #     else:
#     #         return "cpu"
#
#     if system == 'Darwin':
#         return "videotoolbox"
#
#     if torch.cuda.is_available():
#         return "cuda"
#
#     return "cpu"


def resolve_device(user_device: str = None):
    import platform
    import torch

    system = platform.system()

    # if user_device == "cuda" and torch.cuda.is_available():
    #     return "cuda", "cuda"
    # if user_device == "videotoolbox":
    #     return "cpu", "videotoolbox"
    # if user_device == "cpu":
    #     return "cpu", "cpu"

    # Auto-select
    if system == "Darwin":
        return "cpu", "videotoolbox"
    if torch.cuda.is_available():
        return "cuda", "cuda"
    return "cpu", "cpu"

def load_openai_whisper():
    """
    Load OpenAI Whisper dynamically to avoid conflicts with faster-whisper.
    """
    try:
        spec = importlib.util.find_spec("whisper")
        if spec is None:
            raise ImportError("OpenAI Whisper not found.")

        openai_whisper = importlib.util.module_from_spec(spec)
        sys.modules["openai_whisper"] = openai_whisper
        spec.loader.exec_module(openai_whisper)
        return openai_whisper
    except Exception as e:
        print(f"❌ Failed to load OpenAI Whisper: {e}")
        raise