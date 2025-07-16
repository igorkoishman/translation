import os
import shutil
import subprocess
import tempfile
import textwrap

import requests
import srt
import whisperx


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

# def transcribe_audio_whisperx(audio_path, model_name_or_dir="faster-whisper-small", device="cpu", language=None):
#     import whisperx
#     model = whisperx.load_model(
#         model_name_or_dir,
#         device=device,
#         compute_type="float16" if device.startswith("cuda") else "float32",local_files_only=True
#     )
#     result = model.transcribe(audio_path, language=language)
#     # result['segments'] is a list of dicts: {'start', 'end', 'text'}
#     return result

# def transcribe_audio_whisperx(audio_path, model_name_or_dir="faster-whisper-small", device="cpu", language=None):
#     import whisperx
#     try:
#         model = whisperx.load_model(
#             model_name_or_dir,
#             device=device,
#             compute_type="float16" if device.startswith("cuda") else "float32",
#             local_files_only=True
#         )
#     except Exception:
#         # If local not found, allow download
#         model = whisperx.load_model(
#             "guillaumekln/faster-whisper-small",
#             device=device,
#             compute_type="float16" if device.startswith("cuda") else "float32"
#             # local_files_only not set
#         )
#     result = model.transcribe(audio_path, language=language)
#     return result


# def transcribe_audio_whisperx(audio_path, model_name_or_dir="faster-whisper-small", device="cpu", language=None):
#     import whisperx
#     try:
#         model = whisperx.load_model(
#             model_name_or_dir,
#             device=device,
#             compute_type="float16" if device.startswith("cuda") else "float32",
#             local_files_only=True,
#             download_root="/models/faster-whisper-small"
#         )
#     except Exception:
#         model = whisperx.load_model(
#             model_name_or_dir,
#             device=device,
#             compute_type="float16" if device.startswith("cuda") else "float32",
#             local_files_only=False,
#             download_root="/models/faster-whisper-small"
#         )
#     result = model.transcribe(audio_path, language=language)
#     return result

def transcribe_audio_whisperx(audio_path,model_name_or_dir, device="cpu", language=None):
    local_model_path = "/Users/ikoishman/PycharmProjects/translation/models/faster-whisper-small"
    try:
        # Try local directory first
        model = whisperx.load_model(
            model_name_or_dir,
            device=device,
            compute_type="float16" if device.startswith("cuda") else "float32",
            local_files_only=True
        )
    except Exception:
        # If not found, download by model name
        model = whisperx.load_model(
            "small",
            device=device,
            compute_type="float16" if device.startswith("cuda") else "float32",
             download_root=model_name_or_dir,
            local_files_only=False
        )
    return model.transcribe(audio_path, language=language)

# def create_srt(segments, srt_path, to_language=None, do_translate=False, api_key=None):
#     print(f"Creating SRT: {srt_path} ({'translating' if do_translate else 'original'})")
#     subs = []
#     for i, seg in enumerate(segments):
#         start = seg.get('start')
#         end = seg.get('end')
#         text = seg.get('text', '').strip()
#         if start is None or end is None or not text:
#             continue
#         if do_translate and text and to_language:
#             try:
#                 translated = google_translate_text(text, target=to_language, api_key=api_key)
#                 print(f"ORIG: {text}\n{to_language.upper()}: {translated}\n---")
#             except Exception as e:
#                 print(f"Translation error: {e}")
#                 translated = text
#         else:
#             translated = text
#         subs.append(srt.Subtitle(
#             index=len(subs) + 1,
#             start=srt.timedelta(seconds=start),
#             end=srt.timedelta(seconds=end),
#             content=translated
#         ))
#     with open(srt_path, "w", encoding="utf-8") as f:
#         f.write(srt.compose(subs))

# def create_srt(segments, srt_path, to_language=None, do_translate=False, api_key=None, max_chars=80, max_lines=2, max_duration=5.0):
#     print(f"Creating SRT: {srt_path} ({'translating' if do_translate else 'original'})")
#     subs = []
#     idx = 1
#     for seg in segments:
#         start = seg.get('start')
#         end = seg.get('end')
#         text = seg.get('text', '').strip()
#         if start is None or end is None or not text:
#             continue
#         Optionally translate
        # if do_translate and text and to_language:
        #     try:
        #         translated = google_translate_text(text, target=to_language, api_key=api_key)
        #         text = translated
        #     except Exception as e:
        #         print(f"Translation error: {e}")
        #         fallback to original text
        #
        # Split the text into chunks no longer than (max_chars * max_lines)
        # and with no more than max_lines per sub
        # lines = textwrap.wrap(text, width=max_chars)
        # for i in range(0, len(lines), max_lines):
        #     sub_lines = lines[i:i+max_lines]
        #     sub_text = '\n'.join(sub_lines)
        #
            # Proportional timing: divide the segment's time by number of sub-blocks
            # seg_duration = end - start
            # num_blocks = (len(lines) + max_lines - 1) // max_lines
            # this_block = i // max_lines
            # Compute times for this block, clamp to max_duration
            # block_start = start + (seg_duration * this_block / num_blocks)
            # block_end = start + (seg_duration * (this_block+1) / num_blocks)
            # if block_end - block_start > max_duration:
            #     block_end = block_start + max_duration
            #
            # subs.append(srt.Subtitle(
            #     index=idx,
            #     start=srt.timedelta(seconds=block_start),
            #     end=srt.timedelta(seconds=block_end),
            #     content=sub_text
            # ))
            # idx += 1
    #
    # with open(srt_path, "w", encoding="utf-8") as f:
    #     f.write(srt.compose(subs))

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

def main(video_path, output_path_base, model_name_or_dir="faster-whisper-small", output_languages=None, api_key=None, device="cpu", language=None):
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

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 4:
        print("Usage: python auto_subtitle.py input_video output_video model_dir_or_name [lang1 lang2 ...]")
        print("Example: python auto_subtitle.py input.mp4 output.mp4 faster-whisper-small he en ru")
        print("For CUDA/GPU: edit the script to set device='cuda'")
        sys.exit(1)
    video_path = sys.argv[1]
    output_path_base = sys.argv[2]
    model_name_or_dir = sys.argv[3]  # e.g. "faster-whisper-small" or a folder
    output_languages = sys.argv[4:] if len(sys.argv) > 4 else []
    GOOGLE_API_KEY = "AIzaSyDaMcdpM5lBHuUATrZAD3gX0GAUmi5hfXs"  # replace with your key or use os.getenv
    # Set device to "cuda" if you have a GPU and PyTorch CUDA installed
    main(
        video_path,
        output_path_base,
        model_name_or_dir,
        output_languages=output_languages,
        api_key=GOOGLE_API_KEY,
        device="cpu",  # or "cuda"
        language=None  # Set to "en", "he", etc., to force language, else None for auto
    )


# auto_subtitles.py english.mp4 output_large.mp4 /Users/ikoishman/faster-whisper-small