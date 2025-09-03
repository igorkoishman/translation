import os
import secrets
from datetime import datetime
from fastapi import FastAPI, Request, File, UploadFile, Form
from fastapi.responses import FileResponse, HTMLResponse
import shutil
from dotenv import load_dotenv

from app.pipeline.FFmpegBurner import burn, mux_multiple_srts_into_mkv, analyze_media
from app.pipeline.transcriber import FasterWhisperTranscriber, OpenAIWhisperTranscriber
from app.pipeline.translator import LocalLLMTranslate, preload_models, NLLBTranslate, M2M100Translate
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import json
import asyncio
from concurrent.futures import ThreadPoolExecutor

load_dotenv()

app = FastAPI()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
def resolve_project_path(env_var_name: str, default_subdir: str):
    raw = os.getenv(env_var_name, default_subdir)
    rel_path = raw.lstrip(os.sep)
    return os.path.normpath(os.path.join(PROJECT_ROOT, rel_path))
MODEL_DIR = resolve_project_path("MODEL_DIR", "model")
OUTPUT_DIR = resolve_project_path("OUTPUT_DIR", "outputs")
BASE_DIR2 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR2, "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
os.makedirs(OUTPUT_DIR, exist_ok=True)
TEMPLATES_DIR = os.path.join(BASE_DIR2, "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)
translator3 = LocalLLMTranslate(MODEL_DIR)
translator2 = NLLBTranslate(MODEL_DIR)
translator = M2M100Translate(MODEL_DIR)
executor = ThreadPoolExecutor(max_workers=4)  # allow parallel jobs


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/upload")
async def upload_video(
        file: UploadFile = File(...),
        langs: str = Form(""),
        model: str = Form("large"),
        model_type: str = Form("faster-whisper"),
        processor: str = Form("cpu"),
        subtitle_burn_type: str = Form("hard"),
        align: str = Form("True"),
        original_lang: str = Form(""),
        audio_track: int = Form(None),
        subtitle_track: int = Form(None),
        use_subtitles_only: bool = Form(False)
):
    import subprocess

    splitterd = file.filename.split('.')
    ext = splitterd[-1]
    job_id = f"{splitterd[0]}_{secrets.token_hex(4)}"
    input_path = os.path.join(OUTPUT_DIR, f"{job_id}_input.{ext}")
    align = align or None
    with open(input_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    langs_list = langs.strip().split()
    output_path = os.path.join(OUTPUT_DIR, f"{job_id}_output.{ext}")
    ml_device, video_device = resolve_device(user_device=processor)
    # translator = LocalLLMTranslate(MODEL_DIR) if langs_list else None
    # --- MAIN SUBTITLE-ONLY PIPELINE ---
    if use_subtitles_only and subtitle_track is not None:
        analysis = analyze_media(input_path)
        sub_stream_index = None
        orig_lang_from_track = None
        for stream in analysis.get('streams', []):
            if stream['codec_type'] == 'subtitle' and (str(stream['index']) == str(subtitle_track)):
                sub_stream_index = stream['index']
                orig_lang_from_track = stream.get('tags', {}).get('language', None)
                break
        if sub_stream_index is None:
            return {"error": "Subtitle track not found"}

        subtitle_lang = original_lang or orig_lang_from_track or "und"
        srt_path = os.path.splitext(output_path)[0] + "_orig.srt"

        # Extract original subtitle track to SRT
        def extract_subs(infile, outfile, ffmpeg_index):
            cmd = [
                "ffmpeg", "-y", "-i", infile, "-map", f"0:{ffmpeg_index}", outfile
            ]
            subprocess.run(cmd, check=True)
        extract_subs(input_path, srt_path, sub_stream_index)

        outputs = {
            "orig_srt": os.path.basename(srt_path)
        }


        # Hard-burn original
        if subtitle_burn_type in ("hard", "both"):
            out_video_orig = os.path.splitext(output_path)[0] + f"_orig.{ext}"
            burn(input_path, srt_path, out_video_orig)
            outputs["orig"] = os.path.basename(out_video_orig)

        # Prepare for multi-soft
        srt_list = [("und", srt_path)]
        if langs_list:
            for lang in langs_list:
                translated_srt_path = os.path.splitext(output_path)[0] + f"_{lang}.srt"
                translator.translate_srt(
                    output_srt=translated_srt_path,
                    input_srt=srt_path,
                    src_lang=subtitle_lang,
                    tgt_lang=lang
                )
                outputs[f"{lang}_srt"] = os.path.basename(translated_srt_path)
                srt_list.append((lang, translated_srt_path))
                # Hard-burn
                if subtitle_burn_type in ("hard", "both"):
                    out_video = os.path.splitext(output_path)[0] + f"_{lang}.{ext}"
                    burn(input_path, translated_srt_path, out_video)
                    outputs[lang] = os.path.basename(out_video)

        # Soft-mux *all* SRTs into one MKV
        if subtitle_burn_type in ("soft", "both"):
            multi_soft_mkv = os.path.splitext(output_path)[0] + "_multi_soft.mkv"
            filtered_srt_list = [item for item in srt_list if '_orig' not in item[1]]
            mux_multiple_srts_into_mkv(input_path, filtered_srt_list, multi_soft_mkv)
            outputs["multi_soft"] = os.path.basename(multi_soft_mkv)
        with open(os.path.join(OUTPUT_DIR, f"{job_id}.status"), "w") as f:
            json.dump(outputs, f)
        return {"job_id": job_id}

    # --- AUDIO-TRACK OR FULL PIPELINE ---
    # Find actual ffmpeg stream index for audio
    analysis = analyze_media(input_path)
    audio_stream_index = None
    def extract_audio(infile, outfile, ffmpeg_index):
        cmd = [
            "ffmpeg", "-y", "-i", infile, "-map", f"0:{ffmpeg_index}", "-vn", "-acodec", "pcm_s16le", outfile
        ]
        subprocess.run(cmd, check=True)
    if audio_track is not None:
        for stream in analysis.get('streams', []):
            if stream['codec_type'] == 'audio' and (str(stream['index']) == str(audio_track)):
                audio_stream_index = stream['index']
                break

    # Only use WAV for transcription; never for burning/muxing!
    transcription_audio_path = None
    if audio_stream_index is not None:
        transcription_audio_path = os.path.splitext(output_path)[0] + "_track.wav"
        extract_audio(input_path, transcription_audio_path, audio_stream_index)
    else:
        transcription_audio_path = input_path  # fallback, will be video file

    if model_type == "faster-whisper":
        transcriber = FasterWhisperTranscriber(MODEL_DIR, model_type, model, ml_device)
    else:
        transcriber = OpenAIWhisperTranscriber(MODEL_DIR, model_type, model, ml_device)


    from app.auto_subtitles import AutoSubtitlePipeline
    pipeline = AutoSubtitlePipeline(transcriber, translator)

    def run_pipeline():
        start_time = datetime.now()
        result_files = pipeline.process(
            video_path=input_path,
            audio_path=transcription_audio_path,
            output_path_base=output_path,
            output_languages=langs_list,
            language=original_lang,
            device=video_device,
            align_output=align,
            subtitle_burn_type=subtitle_burn_type,translation_model_path=MODEL_DIR
        )
        duration = round((datetime.now() - start_time).total_seconds(), 2)
        result_files["duration_seconds"] = str(duration)
        with open(os.path.join(OUTPUT_DIR, f"{job_id}.status"), "w") as f:
            json.dump(result_files, f)
        if transcription_audio_path and os.path.exists(transcription_audio_path) and transcription_audio_path != input_path:
            os.remove(transcription_audio_path)

    asyncio.get_event_loop().run_in_executor(executor, run_pipeline)
    return {"job_id": job_id}



@app.get("/status/{job_id}")
def status(job_id: str):
    status_path = os.path.join(OUTPUT_DIR, f"{job_id}.status")
    if os.path.exists(status_path):
        with open(status_path) as f:
            outputs = json.load(f)
        duration = outputs.get("duration_seconds", None)
        files = {
            k: v
            for k, v in outputs.items()
            if k != "duration_seconds"
            and isinstance(v, str)
            and os.path.isfile(os.path.join(OUTPUT_DIR, v))
        }
        return {
            "status": "done",
            "outputs": files,
            "duration_seconds": duration
        }
    return {"status": "processing"}

@app.get("/download/{output_file}")
def download_file(output_file: str):
    path = os.path.join(OUTPUT_DIR, output_file)
    return FileResponse(path, media_type="video/mp4", filename=output_file)

@app.post("/analyze")
async def analyze_file(file: UploadFile = File(...)):
    # Save temp
    ext = file.filename.split('.')[-1]
    tmp_path = f"/tmp/{secrets.token_hex(6)}.{ext}"
    with open(tmp_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    try:
        analysis = analyze_media(tmp_path)
        tracks = []
        for stream in analysis.get('streams', []):
            track_info = {
                'index': stream['index'],
                'type': stream['codec_type'],
                'codec': stream.get('codec_name'),
                'lang': stream.get('tags', {}).get('language', 'und'),
                'default': stream.get('disposition', {}).get('default', 0),
                'forced': stream.get('disposition', {}).get('forced', 0),
                'title': stream.get('tags', {}).get('title', ''),
                'id': stream.get('id', None)
            }
            tracks.append(track_info)
        return {'tracks': tracks}
    finally:
        os.remove(tmp_path)

def resolve_device(user_device: str = None):
    import platform
    import torch

    system = platform.system()
    if system == "Darwin":
        return "cpu", "videotoolbox"
    if torch.cuda.is_available():
        return "cuda", "cuda"
    return "cpu", "cpu"

# def mux_srt_into_video(video_in, srt_path, video_out):
#     # Output container must support soft subs (MKV always, MP4 with mov_text)
#     import subprocess
#     ext = os.path.splitext(video_out)[1].lower()
#     # For .mkv you can mux srt directly. For .mp4, you need to convert to mov_text.
#     if ext == ".mkv":
#         cmd = [
#             "ffmpeg", "-y", "-i", video_in, "-i", srt_path,
#             "-c", "copy", "-c:s", "srt", "-map", "0", "-map", "1", video_out
#         ]
#     elif ext == ".mp4":
#         # Convert srt to mov_text for MP4
#         cmd = [
#             "ffmpeg", "-y", "-i", video_in, "-i", srt_path,
#             "-c:v", "copy", "-c:a", "copy", "-c:s", "mov_text", "-map", "0", "-map", "1", video_out
#         ]
#     elif ext == ".avi":
#         # AVI does not support soft subs, use MKV instead
#         video_out = os.path.splitext(video_out)[0] + ".mkv"
#         cmd = [
#             "ffmpeg", "-y", "-i", video_in, "-i", srt_path,
#             "-c", "copy", "-c:s", "srt", "-map", "0", "-map", "1", video_out
#         ]
#     else:
#         # Default to MKV muxing
#         video_out = os.path.splitext(video_out)[0] + ".mkv"
#         cmd = [
#             "ffmpeg", "-y", "-i", video_in, "-i", srt_path,
#             "-c", "copy", "-c:s", "srt", "-map", "0", "-map", "1", video_out
#         ]
#     subprocess.run(cmd, check=True)
#     return video_out
#
# def mux_multiple_srts_into_mkv(video_in, srt_paths, video_out):
#     """
#     srt_paths: list of tuples (lang_code, srt_path)
#     """
#     import subprocess
#
#     cmd = ["ffmpeg", "-y", "-i", video_in]
#     # Add all srt files as inputs
#     for _, srt_path in srt_paths:
#         cmd += ["-i", srt_path]
#     cmd += ["-c", "copy"]
#     # For each srt, add a mapping, and assign language/label
#     # First stream is video_in, srt files are inputs 1,2,3...
#     # "-map 0" maps all streams from the original video
#     cmd += ["-map", "0"]
#     for idx, (lang, _) in enumerate(srt_paths):
#         cmd += ["-map", str(idx + 1)]
#     # Subtitle codecs: srt
#     cmd += ["-c:s", "srt"]
#     # Set language for each srt stream
#     for idx, (lang, _) in enumerate(srt_paths):
#         cmd += [f"-metadata:s:s:{idx}", f"language={lang}"]
#     cmd += [video_out]
#
#     subprocess.run(cmd, check=True)
#     return video_out

if __name__ == "__main__":
    import uvicorn
    preload_models(MODEL_DIR)
    uvicorn.run("app.main:app", host="0.0.0.0", port=8080, reload=True)