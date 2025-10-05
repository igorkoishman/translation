# app/auto_subtitles.py

import os
import tempfile
import shutil
import textwrap
import srt
import cv2
import pytesseract
from PIL import Image

from app.pipeline.FFmpegBurner import mux_multiple_srts_into_mkv, burn


class AutoSubtitlePipeline:
    def __init__(self, transcriber, translator=None):
        self.transcriber = transcriber
        self.translator = translator

    @staticmethod
    def extract_audio(video_path, audio_path):
        import subprocess
        subprocess.run([
            "ffmpeg", "-y", "-i", video_path,
            "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
            audio_path
        ], check=True)

    def create_srt(self, segments, src_lang, srt_path, to_language=None, do_translate=False,
                   max_chars=80, max_lines=2, max_duration=5.0):
        subs, idx = [], 1
        for seg in segments:
            start, end = seg.get('start'), seg.get('end')
            text = seg.get('text', '').strip()
            if start is None or end is None or not text:
                continue
            if do_translate and self.translator and to_language:
                try:
                    text = self.translator.translate(text, src_lang, to_language)
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

    def detect_burned_in_subs(self, video_path, frames_to_check=10, min_line_length=5, min_frames_with_text=6):
        import re
        cap = cv2.VideoCapture(video_path)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if frame_count == 0:
            cap.release()
            return False
        check_idxs = [int(frame_count * i / frames_to_check) for i in range(frames_to_check)]
        found_text = 0

        for idx in check_idxs:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if not ret:
                continue
            h, w, _ = frame.shape
            bottom = frame[int(h * 0.8):, :]
            img = Image.fromarray(bottom)
            text = pytesseract.image_to_string(img).strip()

            # Filter out very short, single words/numbers, or non-subtitle noise
            if (
                text
                and len(text) >= min_line_length
                and re.search(r'\s', text)  # must contain a space (likely a sentence)
                and len(text.split()) > 1  # more than one word
                and len(text) < 100  # ignore unlikely long texts
            ):
                found_text += 1

        cap.release()
        print(f"Detected subtitle-like text in {found_text} of {frames_to_check} frames.")
        return found_text >= min_frames_with_text

    # def mask_subtitle_area(self, input_video, output_video, percent=0.15, color="black"):
    #     import subprocess
    #     filter_str = f"drawbox=y=ih*(1-{percent}):w=iw:h=ih*{percent}:color={color}@1.0:t=fill"
    #     subprocess.run([
    #         "ffmpeg", "-y", "-i", input_video,
    #         "-vf", filter_str,
    #         "-c:a", "copy", output_video
    #     ], check=True)

    # def process(
    #         self, video_path, audio_path, output_path_base,
    #         output_languages=None, language=None, device=None,
    #         align_output=True, subtitle_burn_type="hard"
    # ):
    #     """
    #     Processes subtitles for a video file:
    #     - hard: burn subs into video
    #     - soft: mux .srt as soft subs (in .mkv)
    #     - both: do both
    #     """
    #     from app.main import mux_srt_into_video  # Ensure this is imported
    #
    #     with tempfile.TemporaryDirectory() as tmpdir:
    #         masked = self.detect_burned_in_subs(video_path)
    #         if masked:
    #             print("Burned-in subtitles detected. Masking area before burning new subtitles.")
    #             masked_path = os.path.join(tmpdir, "masked.mp4")
    #             self.mask_subtitle_area(video_path, masked_path, percent=0.25)
    #             video_for_burn = masked_path
    #         else:
    #             video_for_burn = video_path
    #
    #         audio_for_transcription = audio_path or video_for_burn
    #         if not (audio_for_transcription.endswith('.wav') and os.path.exists(audio_for_transcription)):
    #             audio_temp_path = os.path.join(tmpdir, "audio.wav")
    #             self.extract_audio(video_for_burn, audio_temp_path)
    #             audio_for_transcription = audio_temp_path
    #
    #         result, src_lang = self.transcriber.transcribe(
    #             audio_for_transcription, language=language, align_output=align_output
    #         )
    #         srt_paths = {}
    #         # Original SRT
    #         srt_orig = os.path.join(tmpdir, "subtitles_orig.srt")
    #         self.create_srt(result['segments'], src_lang=src_lang, srt_path=srt_orig)
    #         srt_paths["orig"] = srt_orig
    #         _, ext = os.path.splitext(video_for_burn)
    #
    #         # --- Handle original subtitles (non-translated) ---
    #         base_out = os.path.splitext(output_path_base)[0]
    #         if subtitle_burn_type in ("hard", "both"):
    #             out_video_orig = f"{base_out}_orig{ext}"
    #             self.burner.burn(video_for_burn, srt_orig, out_video_orig, device=device, masked=masked)
    #         if subtitle_burn_type in ("soft", "both"):
    #             out_video_orig_soft = f"{base_out}_orig_soft.mkv"
    #             mux_srt_into_video(video_for_burn, srt_orig, out_video_orig_soft)
    #
    #
    #         # --- Handle translations ---
    #         if output_languages:
    #             for lang in output_languages:
    #                 srt_path = os.path.join(tmpdir, f"subtitles_{lang}.srt")
    #                 self.create_srt(
    #                     result['segments'], src_lang=src_lang,
    #                     srt_path=srt_path, to_language=lang, do_translate=True
    #                 )
    #                 srt_paths[lang] = srt_path
    #
    #                 if subtitle_burn_type in ("hard", "both"):
    #                     out_video = f"{base_out}_{lang}{ext}"
    #                     self.burner.burn(video_for_burn, srt_path, out_video, device=device, masked=masked)
    #                 if subtitle_burn_type in ("soft", "both"):
    #                     out_video_soft = f"{base_out}_{lang}_soft.mkv"
    #                     mux_srt_into_video(video_for_burn, srt_path, out_video_soft)
    #
    #         # Move SRTs to output location
    #         for lang, path in srt_paths.items():
    #             final_srt_path = f"{base_out}_{lang}.srt"
    #             shutil.move(path, final_srt_path)
    #
    #         return True
    def process(
            self, video_path, audio_path, output_path_base,
            output_languages=None, language=None, device=None,
            align_output=True, subtitle_burn_type="hard",translation_model_path=None
    ):

        output_files = {}

        with tempfile.TemporaryDirectory() as tmpdir:
            masked = self.detect_burned_in_subs(video_path)
            if masked:
                print("Burned-in subtitles detected. Masking area before burning new subtitles.")
                masked_path = os.path.join(tmpdir, "masked.mp4")
                self.mask_subtitle_area(video_path, masked_path, percent=0.25)
                video_for_burn = masked_path
            else:
                video_for_burn = video_path

            audio_for_transcription = audio_path or video_for_burn
            if not (audio_for_transcription.endswith('.wav') and os.path.exists(audio_for_transcription)):
                audio_temp_path = os.path.join(tmpdir, "audio.wav")
                self.extract_audio(video_for_burn, audio_temp_path)
                audio_for_transcription = audio_temp_path

            result, src_lang = self.transcriber.transcribe(
                audio_for_transcription, language=language, align_output=align_output
            )
            srt_paths = {}

            # --- Create all SRTs first ---
            srt_orig = os.path.join(tmpdir, "subtitles_orig.srt")
            self.create_srt(result['segments'], src_lang=src_lang, srt_path=srt_orig)
            srt_paths["orig"] = srt_orig
            _, ext = os.path.splitext(video_for_burn)
            base_out = os.path.splitext(output_path_base)[0]

            # --- Handle translations ---
            if output_languages:
                for lang in output_languages:
                    srt_path = os.path.join(tmpdir, f"subtitles_{lang}.srt")
                    self.create_srt(
                        result['segments'], src_lang=src_lang,
                        srt_path=srt_path, to_language=lang, do_translate=True
                    )
                    srt_paths[lang] = srt_path

            # --- Hard-burn (still per-language and original) ---
            if subtitle_burn_type in ("hard", "both"):
                # Hard-burn original
                out_video_orig = f"{base_out}_orig{ext}"
                burn(video_for_burn, srt_orig, out_video_orig, device=device, masked=masked)
                output_files["orig"] = os.path.basename(out_video_orig)
                # Hard-burn translations
                if output_languages:
                    for lang in output_languages:
                        srt_path = srt_paths[lang]
                        out_video = f"{base_out}_{lang}{ext}"
                        burn(video_for_burn, srt_path, out_video, device=device, masked=masked)
                        output_files[lang] = os.path.basename(out_video)

            # --- Soft-mux: make one MKV with ALL SRTs ---
            if subtitle_burn_type in ("soft", "both"):
                # Collect all SRTs and languages (original + translations)
                multi_soft_mkv = f"{base_out}_multi_soft.mkv"
                srt_list = [("und", srt_paths["orig"])]  # orig is typically "und" unless you have lang code
                if output_languages:
                    for lang in output_languages:
                        srt_list.append((lang, srt_paths[lang]))
                mux_multiple_srts_into_mkv(video_for_burn, srt_list, multi_soft_mkv)
                output_files["multi_soft"] = os.path.basename(multi_soft_mkv)

            # Move SRTs to output location and add to output_files
            for lang, path in srt_paths.items():
                final_srt_path = f"{base_out}_{lang}.srt"
                shutil.move(path, final_srt_path)
                output_files[f"{lang}_srt"] = os.path.basename(final_srt_path)

            # Also move and track the original SRT file
            # final_srt_orig_path = f"{base_out}_orig.srt"
            # shutil.move(srt_orig, final_srt_orig_path)
            # output_files["orig_srt"] = os.path.basename(final_srt_orig_path)

            return output_files


