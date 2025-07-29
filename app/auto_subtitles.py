# app/auto_subtitles.py

import os
import tempfile
import shutil
import textwrap
import srt

from app.pipeline.transcriber import FasterWhisperTranscriber, OpenAIWhisperTranscriber
# from app.pipeline.translator import GoogleTranslate
from app.pipeline.burner import FFmpegBurner

class AutoSubtitlePipeline:
    def __init__(self, transcriber, burner, translator=None):
        self.transcriber = transcriber
        self.translator = translator
        self.burner = burner

    @staticmethod
    def extract_audio(video_path, audio_path):
        import subprocess
        subprocess.run([
            "ffmpeg", "-y", "-i", video_path,
            "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
            audio_path
        ], check=True)

    def create_srt(self, segments,src_lang, srt_path, to_language=None, do_translate=False, max_chars=80, max_lines=2,
                   max_duration=5.0):

        subs, idx = [], 1
        for seg in segments:
            start, end = seg.get('start'), seg.get('end')
            text = seg.get('text', '').strip()
            if start is None or end is None or not text:
                continue
            if do_translate and self.translator and to_language:
                try:
                    text = self.translator.translate(text, src_lang,to_language)
                    # text = self.translator.translate(text, to_language,)
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

    def process(self, video_path, output_path_base, output_languages=None, language=None, device=None):
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = os.path.join(tmpdir, "audio.wav")
            self.extract_audio(video_path, audio_path)
            result,src_lang = self.transcriber.transcribe(audio_path, language=language)
            print("DEBUG: type of result['segments'] = ", type(result))
            # print("DEBUG: value of result['segments'] = ", result)
            # segments = result["segments"]
            # if isinstance(segments, dict) and "segments" in segments:
            #     flatten accidental wrapping
                # segments = segments["segments"]
            srt_paths = {}

            # Original SRT
            srt_orig = os.path.join(tmpdir, "subtitles_orig.srt")
            self.create_srt(result['segments'],src_lang=src_lang, srt_path=srt_orig)
            srt_paths["orig"] = srt_orig
            _, ext = os.path.splitext(video_path)

            # Translate + burn
            if output_languages:
                for lang in output_languages:
                    srt_path = os.path.join(tmpdir, f"subtitles_{lang}.srt")
                    self.create_srt(result['segments'],src_lang=src_lang, srt_path=srt_path, to_language=lang, do_translate=True)
                    srt_paths[lang] = srt_path
                    out_video = os.path.splitext(output_path_base)[0] + f"_{lang}{ext}"
                    self.burner.burn(video_path, srt_path, out_video, device=device)
            # Burn original
            out_video_orig = os.path.splitext(output_path_base)[0] + f"_orig{ext}"
            self.burner.burn(video_path, srt_paths["orig"], out_video_orig, device=device)
            # Move SRTs to output location
            for lang, path in srt_paths.items():
                final_srt_path = os.path.splitext(output_path_base)[0] + f"_{lang}.srt"
                shutil.move(path, final_srt_path)
            return True
