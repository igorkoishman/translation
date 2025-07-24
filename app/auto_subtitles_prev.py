import os
import shutil
import subprocess
import tempfile
import textwrap

import requests
import srt
import whisperx
import ssl
import huggingface_hub
import logging
import torch
import glob
print("DEBUG: Starting subtitle main() function")
logging.basicConfig(level=logging.INFO)

def google_translate_text(text, target='he', api_key=None):
    url = "https://translation.googleapis.com/language/translate/v2"
    params = {
        "q": text,
        "target": target,
        "format": "text",
        "key": api_key
    }
    response = requests.post(url, data=params, verify=False)
    response.raise_for_status()
    return response.json()['data']['translations'][0]['translatedText']

def extract_audio(video_path, audio_path):
    cmd = [
        'ffmpeg', '-y', '-i', video_path,
        '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le',
        audio_path
    ]
    subprocess.run(cmd, check=True)


def flatten_whisper_snapshot(model_base_dir: str):
    """
    Finds the snapshot folder inside HuggingFace's nested model structure
    and moves all its contents to the model_base_dir.
    """
    snapshot_pattern = os.path.join(
        model_base_dir, "models--*--faster-whisper-*", "snapshots", "*"
    )
    snapshot_dirs = glob.glob(snapshot_pattern)

    if not snapshot_dirs:
        print("❌ No snapshot directory found.")
        return

    snapshot_dir = snapshot_dirs[0]
    print(f"📦 Found snapshot: {snapshot_dir}")

    for item in os.listdir(snapshot_dir):
        src = os.path.join(snapshot_dir, item)
        dst = os.path.join(model_base_dir, item)

        if os.path.exists(dst):
            print(f"⚠️ Skipping existing file: {dst}")
            continue

        if os.path.islink(src):
            shutil.copy(os.path.realpath(src), dst)
        elif os.path.isfile(src):
            shutil.copy(src, dst)
        elif os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)

    # Optional cleanup
    nested_model_dir = os.path.join(model_base_dir, "models--")
    for folder in glob.glob(os.path.join(model_base_dir, "models--*")):
        print(f"🧹 Removing nested HuggingFace folder: {folder}")
        shutil.rmtree(folder, ignore_errors=True)

    print("✅ Flatten complete.")

def transcribe_audio_whisperx(audio_path, model_name_or_dir, device="cuda", language=None):
    print("Trying model path:", model_name_or_dir)
    logging.info(f"CUDA available: {torch.cuda.is_available()}")
    logging.info(f"CUDA device: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'}")
    if os.path.exists(model_name_or_dir) and os.listdir(model_name_or_dir):
        print("Found local model directory.")
        model = whisperx.load_model(
            model_name_or_dir,
            device=device,
            compute_type="float16" if device.startswith("cuda") else "float32",
            local_files_only=True
        )
    else:
        os.environ["HF_HUB_DISABLE_SSL_VERIFICATION"] = "1"
        ssl._create_default_https_context = ssl._create_unverified_context
        print("Downloading model to:", model_name_or_dir)
        model = whisperx.load_model(
            "large",  # or full HF model name if needed
            device=device,
            compute_type="float16" if device.startswith("cuda") else "float32",
            download_root=model_name_or_dir,
            local_files_only=False
        )
        flatten_whisper_snapshot(model_name_or_dir)
    return model.transcribe(audio_path, language=language)

def create_srt(
    segments, srt_path, to_language=None, do_translate=False, api_key=None,
    max_chars=80, max_lines=2, max_duration=5.0
):
    print(f"Creating SRT: {srt_path} ({'translating' if do_translate else 'original'})")
    subs = []
    idx = 1
    for seg in segments:
        start = seg.get('start')
        end = seg.get('end')
        text = seg.get('text', '').strip()
        if start is None or end is None or not text:
            continue
        if do_translate and text and to_language:
            try:
                translated = google_translate_text(text, target=to_language, api_key=api_key)
                text = translated
            except Exception as e:
                print(f"Translation error: {e}")

        seg_duration = end - start
        # Split only if segment is longer than max_duration or too many lines
        lines = textwrap.wrap(text, width=max_chars)
        n_blocks = max(1, (len(lines) + max_lines - 1) // max_lines)
        # If segment is much longer than max_duration, split by duration, else split only by lines
        if seg_duration > max_duration and n_blocks > 1:
            # Split by both lines and time
            for i in range(n_blocks):
                sub_lines = lines[i*max_lines : (i+1)*max_lines]
                sub_text = '\n'.join(sub_lines)
                block_start = start + (seg_duration * i / n_blocks)
                block_end = start + (seg_duration * (i+1) / n_blocks)
                subs.append(srt.Subtitle(
                    index=idx,
                    start=srt.timedelta(seconds=block_start),
                    end=srt.timedelta(seconds=block_end),
                    content=sub_text
                ))
                idx += 1
        else:
            # Keep original timing for all blocks, just split text
            for i in range(0, len(lines), max_lines):
                sub_lines = lines[i:i+max_lines]
                sub_text = '\n'.join(sub_lines)
                subs.append(srt.Subtitle(
                    index=idx,
                    start=srt.timedelta(seconds=start),
                    end=srt.timedelta(seconds=end),
                    content=sub_text
                ))
                idx += 1

    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(srt.compose(subs))

def burn_subtitles(video_path, srt_path, output_path):
    cmd = [
        'ffmpeg', '-y',
        '-i', video_path,
        '-vf', f"subtitles={srt_path}:force_style='FontName=Arial'",
        '-c:a', 'copy',
        output_path
    ]
    subprocess.run(cmd, check=True)

def main(video_path, output_path_base, model_name_or_dir, output_languages=None, api_key=None, device="cuda", language=None):
    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"Temporary directory: {tmpdir}")
        audio_path = os.path.join(tmpdir, "audio.wav")
        print("Extracting audio...")
        extract_audio(video_path, audio_path)
        print("Transcribing with WhisperX...")
        result = transcribe_audio_whisperx(audio_path, model_name_or_dir=model_name_or_dir, device=device, language=language)


        srt_paths = {}
        # Save original language SRT (always!)
        srt_orig = os.path.join(tmpdir, "subtitles_orig.srt")
        create_srt(result['segments'], srt_orig, to_language=None, do_translate=False)
        srt_paths['orig'] = srt_orig

        # Translate and save SRT for each requested language
        if output_languages:
            for lang in output_languages:
                srt_lang = os.path.join(tmpdir, f"subtitles_{lang}.srt")
                print(f"Creating SRT subtitles in {lang}...")
                create_srt(result['segments'], srt_lang, to_language=lang, do_translate=True, api_key=api_key)
                srt_paths[lang] = srt_lang

            # Burn each language SRT into a separate video
            for lang in output_languages:
                out_video = os.path.splitext(output_path_base)[0] + f"_{lang}.mp4"
                print(f"Burning subtitles ({lang}) into video: {out_video}")
                burn_subtitles(video_path, srt_paths[lang], out_video)
                print(f"Done! Output video with {lang} subtitles: {out_video}")

        out_video_orig = os.path.splitext(output_path_base)[0] + "_orig.mp4"
        burn_subtitles(video_path, srt_paths['orig'], out_video_orig)
        print(f"Done! Output video with original language subtitles: {out_video_orig}")

        # Save all SRTs
        for lang, path in srt_paths.items():
            out_srt = os.path.splitext(output_path_base)[0] + f"_{lang}.srt"
            # os.rename(path, out_srt)
            shutil.move(path, out_srt)
            print(f"SRT file saved: {out_srt}")
