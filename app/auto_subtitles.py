import os
import shutil
import subprocess
import tempfile
import textwrap
import requests
import srt
import whisperx
import ssl
import logging
import torch
import glob

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


def transcribe_audio_whisperx(audio_path, model_name_or_dir, device="cuda", language=None, align_output=True):
    print(f"🧠 Loading model from: {model_name_or_dir}")
    if os.path.exists(model_name_or_dir) and os.listdir(model_name_or_dir):
        model = whisperx.load_model(
            model_name_or_dir, device=device,
            compute_type="float16" if device.startswith("cuda") else "float32",
            local_files_only=True
        )
    else:
        os.environ["HF_HUB_DISABLE_SSL_VERIFICATION"] = "1"
        ssl._create_default_https_context = ssl._create_unverified_context
        model = whisperx.load_model(
            "large", device=device,
            compute_type="float16" if device.startswith("cuda") else "float32",
            download_root=model_name_or_dir,
            local_files_only=False
        )
        flatten_whisper_snapshot(model_name_or_dir)

    result = model.transcribe(audio_path, language=language)

    # Perform alignment for word-level timestamps
    if align_output:
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


def burn_subtitles(video_path, srt_path, output_path):
    cmd = [
        'ffmpeg', '-y', '-i', video_path,
        '-vf', f"subtitles={srt_path}:force_style='FontName=Arial'",
        '-c:a', 'copy', output_path
    ]
    subprocess.run(cmd, check=True)


def main(video_path, output_path_base, model_name_or_dir="./models/whisper-large",
         output_languages=None, api_key=None, device="cuda", language=None):
    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"🔧 Working in temp dir: {tmpdir}")
        audio_path = os.path.join(tmpdir, "audio.wav")
        extract_audio(video_path, audio_path)

        print("🎙️ Transcribing and aligning...")
        result = transcribe_audio_whisperx(audio_path, model_name_or_dir=model_name_or_dir,
                                           device=device, language=language)

        srt_paths = {}

        srt_orig = os.path.join(tmpdir, "subtitles_orig.srt")
        create_srt(result["segments"], srt_orig)
        srt_paths["orig"] = srt_orig

        if output_languages:
            for lang in output_languages:
                srt_lang = os.path.join(tmpdir, f"subtitles_{lang}.srt")
                create_srt(result["segments"], srt_lang, to_language=lang, do_translate=True, api_key=api_key)
                srt_paths[lang] = srt_lang
                out_video = os.path.splitext(output_path_base)[0] + f"_{lang}.mp4"
                burn_subtitles(video_path, srt_paths[lang], out_video)
                print(f"✅ Done with {lang}: {out_video}")

        out_video_orig = os.path.splitext(output_path_base)[0] + "_orig.mp4"
        burn_subtitles(video_path, srt_paths["orig"], out_video_orig)
        print(f"🎬 Done with original subtitles: {out_video_orig}")

        for lang, path in srt_paths.items():
            final_srt_path = os.path.splitext(output_path_base)[0] + f"_{lang}.srt"
            shutil.move(path, final_srt_path)
            print(f"💾 Saved: {final_srt_path}")
