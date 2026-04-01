import torch
import typing
# Patch torch.load to handle PyTorch 2.6 weights_only default change
original_load = torch.load
def patched_load(*args, **kwargs):
    # Force weights_only=False for all loads in this process
    kwargs['weights_only'] = False
    return original_load(*args, **kwargs)
torch.load = patched_load

from omegaconf.listconfig import ListConfig
from omegaconf.dictconfig import DictConfig
from omegaconf.base import ContainerMetadata, Node
torch.serialization.add_safe_globals([ListConfig, DictConfig, ContainerMetadata, Node, typing.Any])
import os
import secrets
import tempfile
from datetime import datetime
from fastapi import FastAPI, Request, File, UploadFile, Form
from fastapi.responses import FileResponse, HTMLResponse
import shutil
from dotenv import load_dotenv
import logging
from logging.handlers import RotatingFileHandler

from app.pipeline.FFmpegBurner import burn, mux_multiple_srts_into_mkv, analyze_media
from app.pipeline.transcriber import FasterWhisperTranscriber, OpenAIWhisperTranscriber
from app.pipeline.translator import LocalLLMTranslate, preload_models, NLLBTranslate, M2M100Translate
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import json
import asyncio
from concurrent.futures import ThreadPoolExecutor

load_dotenv()

# Configure logging
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

# Clear existing handlers if any
while root_logger.handlers:
    root_logger.removeHandler(root_logger.handlers[0])

file_handler = RotatingFileHandler(
    os.path.join(LOG_DIR, 'app.log'),
    maxBytes=10*1024*1024,
    backupCount=5
)
file_handler.setFormatter(log_formatter)
root_logger.addHandler(file_handler)

stream_handler = logging.StreamHandler()
stream_handler.setFormatter(log_formatter)
root_logger.addHandler(stream_handler)

logger = logging.getLogger(__name__)

app = FastAPI()
app.state.upload_chunk_size = 1024 * 1024  # 1MB chunks
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
executor = ThreadPoolExecutor(max_workers=4)  # allow parallel jobs


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/upload")
async def upload_video(
        file: UploadFile = File(None),
        file_id: str = Form(None),
        langs: str = Form(""),
        model: str = Form("large"),
        model_type: str = Form("faster-whisper"),
        processor: str = Form("cpu"),
        subtitle_burn_type: str = Form("hard"),
        align: str = Form("True"),
        original_lang: str = Form(""),
        audio_track: int = Form(None),
        subtitle_track: int = Form(None),
        use_subtitles_only: bool = Form(False),
        translator_type: str = Form("m2m100")
):
    import subprocess
    loop = asyncio.get_running_loop()

    # --- RESOLVE TRANSLATOR ---
    if translator_type == "nllb":
        current_translator = NLLBTranslate(MODEL_DIR)
    elif translator_type == "localllm":
        current_translator = LocalLLMTranslate(MODEL_DIR)
    else:
        current_translator = M2M100Translate(MODEL_DIR)

    if file:
        filename = file.filename
        splitterd = filename.split('.')
        ext = splitterd[-1]
        job_id = f"{splitterd[0]}_{secrets.token_hex(4)}"
        input_path = os.path.join(OUTPUT_DIR, f"{job_id}_input.{ext}")

        logger.info(f"[{job_id}] Starting upload for file: {filename}")
        try:
            bytes_written = 0
            # Open file once and write chunks in a thread-safe way
            with open(input_path, "wb") as f:
                while True:
                    chunk = await file.read(app.state.upload_chunk_size)
                    if not chunk:
                        break
                    # Use run_in_executor for blocking file write
                    await loop.run_in_executor(None, f.write, chunk)
                    bytes_written += len(chunk)
            logger.info(f"[{job_id}] Upload complete - size: {bytes_written / (1024*1024):.2f}MB")
        except Exception as e:
            logger.error(f"[{job_id}] Upload failed: {str(e)}", exc_info=True)
            raise
    elif file_id:
        temp_dir = tempfile.gettempdir()
        matches = [f for f in os.listdir(temp_dir) if f.startswith(f"analyze_{file_id}")]
        if not matches:
            return {"error": "Staged file not found. Please re-analyze or upload manually."}

        staged_filename = matches[0]
        staged_path = os.path.join(temp_dir, staged_filename)
        ext = staged_filename.split('.')[-1]

        job_id = f"staged_{file_id}"
        input_path = os.path.join(OUTPUT_DIR, f"{job_id}_input.{ext}")
        # Use run_in_executor for blocking shutil.move
        await loop.run_in_executor(None, shutil.move, staged_path, input_path)
        logger.info(f"[{job_id}] Using staged file: {staged_filename}")
    else:
        return {"error": "No file or file_id provided"}

    align = align or None
    logger.info(f"[{job_id}] Parameters - langs: {langs}, model: {model}, model_type: {model_type}")

    langs_list = langs.strip().split()
    output_path = os.path.join(OUTPUT_DIR, f"{job_id}_output.{ext}")
    ml_device, video_device = resolve_device(user_device=processor)

    # --- MAIN PIPELINE SUBMIT ---
    # Create initial status file
    initial_status = {"status": "processing", "start_time": datetime.now().isoformat()}
    with open(os.path.join(OUTPUT_DIR, f"{job_id}.status"), "w") as f:
        json.dump(initial_status, f)

    async def run_pipeline_task():
        if use_subtitles_only and subtitle_track is not None:
            logger.info(f"[{job_id}] Starting subtitle-only pipeline in executor")
            # We wrap the whole subtitle-only logic in executor if it's blocking
            def process_subs_only():
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

                subtitle_lang = original_lang.strip() if original_lang and original_lang.strip() else (orig_lang_from_track or "und")
                srt_path = os.path.splitext(output_path)[0] + "_orig.srt"

                def extract_subs(infile, outfile, ffmpeg_index):
                    cmd = ["ffmpeg", "-y", "-i", infile, "-map", f"0:{ffmpeg_index}", outfile]
                    subprocess.run(cmd, check=True)
                extract_subs(input_path, srt_path, sub_stream_index)

                outputs = {"orig_srt": os.path.basename(srt_path)}
                if subtitle_burn_type in ("hard", "both"):
                    out_video_orig = os.path.splitext(output_path)[0] + f"_orig.{ext}"
                    burn(input_path, srt_path, out_video_orig)
                    outputs["orig"] = os.path.basename(out_video_orig)

                srt_list = [("und", srt_path)]
                if langs_list:
                    for lang in langs_list:
                        translated_srt_path = os.path.splitext(output_path)[0] + f"_{lang}.srt"
                        current_translator.translate_srt(translated_srt_path, srt_path, subtitle_lang, lang)
                        outputs[f"{lang}_srt"] = os.path.basename(translated_srt_path)
                        srt_list.append((lang, translated_srt_path))
                        if subtitle_burn_type in ("hard", "both"):
                            out_video = os.path.splitext(output_path)[0] + f"_{lang}.{ext}"
                            burn(input_path, translated_srt_path, out_video)
                            outputs[lang] = os.path.basename(out_video)

                if subtitle_burn_type in ("soft", "both"):
                    multi_soft_mkv = os.path.splitext(output_path)[0] + "_multi_soft.mkv"
                    filtered_srt_list = [item for item in srt_list if '_orig' not in item[1]]
                    mux_multiple_srts_into_mkv(input_path, filtered_srt_list, multi_soft_mkv)
                    outputs["multi_soft"] = os.path.basename(multi_soft_mkv)

                with open(os.path.join(OUTPUT_DIR, f"{job_id}.status"), "w") as f:
                    json.dump(outputs, f)
                return outputs

            await loop.run_in_executor(executor, process_subs_only)
        else:
            # AUDIO-TRACK OR FULL PIPELINE
            def run_full_pipeline():
                try:
                    analysis = analyze_media(input_path)
                    audio_stream_index = None
                    if audio_track is not None:
                        for stream in analysis.get('streams', []):
                            if stream['codec_type'] == 'audio' and (str(stream['index']) == str(audio_track)):
                                audio_stream_index = stream['index']
                                break

                    transcription_audio_path = None
                    if audio_stream_index is not None:
                        transcription_audio_path = os.path.splitext(output_path)[0] + "_track.wav"
                        cmd = ["ffmpeg", "-y", "-i", input_path, "-map", f"0:{audio_stream_index}", "-vn", "-acodec", "pcm_s16le", transcription_audio_path]
                        subprocess.run(cmd, check=True)
                    else:
                        transcription_audio_path = input_path

                    if model_type == "faster-whisper":
                        transcriber = FasterWhisperTranscriber(MODEL_DIR, model_type, model, ml_device)
                    else:
                        transcriber = OpenAIWhisperTranscriber(MODEL_DIR, model_type, model, ml_device)

                    from app.auto_subtitles import AutoSubtitlePipeline
                    pipeline = AutoSubtitlePipeline(transcriber, current_translator)

                    start_time = datetime.now()
                    result_files = pipeline.process(
                        video_path=input_path, audio_path=transcription_audio_path,
                        output_path_base=output_path, output_languages=langs_list,
                        language=original_lang.strip() if original_lang and original_lang.strip() else None,
                        device=video_device, align_output=align,
                        subtitle_burn_type=subtitle_burn_type, translation_model_path=MODEL_DIR
                    )
                    duration = round((datetime.now() - start_time).total_seconds(), 2)
                    result_files["duration_seconds"] = str(duration)
                    with open(os.path.join(OUTPUT_DIR, f"{job_id}.status"), "w") as f:
                        json.dump(result_files, f)

                    if transcription_audio_path and os.path.exists(transcription_audio_path) and transcription_audio_path != input_path:
                        os.remove(transcription_audio_path)
                except Exception as e:
                    logger.error(f"[{job_id}] Pipeline failed: {str(e)}", exc_info=True)
                    with open(os.path.join(OUTPUT_DIR, f"{job_id}.status"), "w") as f:
                        json.dump({"error": str(e), "status": "failed"}, f)

            await loop.run_in_executor(executor, run_full_pipeline)

    asyncio.create_task(run_pipeline_task())
    return {"job_id": job_id}

@app.post("/analyze")
async def analyze_file(file: UploadFile = File(...)):
    ext = file.filename.split('.')[-1]
    analyze_id = secrets.token_hex(6)
    tmp_path = os.path.join(tempfile.gettempdir(), f"analyze_{analyze_id}.{ext}")
    loop = asyncio.get_running_loop()

    logger.info(f"[analyze-{analyze_id}] Starting analysis for: {file.filename}")
    try:
        with open(tmp_path, "wb") as f:
            while True:
                chunk = await file.read(app.state.upload_chunk_size)
                if not chunk:
                    break
                await loop.run_in_executor(None, f.write, chunk)

        analysis = await loop.run_in_executor(None, analyze_media, tmp_path)
        tracks = []
        for stream in analysis.get('streams', []):
            tracks.append({
                'index': stream['index'],
                'type': stream['codec_type'],
                'codec': stream.get('codec_name'),
                'lang': stream.get('tags', {}).get('language', 'und'),
                'default': stream.get('disposition', {}).get('default', 0),
                'forced': stream.get('disposition', {}).get('forced', 0),
                'title': stream.get('tags', {}).get('title', ''),
                'id': stream.get('id', None)
            })
        return {'tracks': tracks, 'file_id': analyze_id}
    except Exception as e:
        logger.error(f"[analyze-{analyze_id}] Analysis failed: {str(e)}", exc_info=True)
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise

@app.on_event("startup")
async def startup_event():
    # Optional: cleanup old staged files on startup
    import time
    temp_dir = tempfile.gettempdir()
    now = time.time()
    for f in os.listdir(temp_dir):
        if f.startswith("analyze_"):
            path = os.path.join(temp_dir, f)
            if os.stat(path).st_mtime < now - 24 * 3600:
                os.remove(path)
                logger.info(f"Cleaned up old staged file: {f}")

def resolve_device(user_device: str = None):
    import platform
    import torch

    system = platform.system()
    if system == "Darwin":
        return "cpu", "videotoolbox"

    # If user explicitly requested cpu, honor it
    if user_device == "cpu":
        return "cpu", "cpu"

    # Otherwise try cuda if available
    if torch.cuda.is_available():
        return "cuda", "cuda"

    return "cpu", "cpu"

@app.get("/status/{job_id}")
async def get_status(job_id: str):
    status_path = os.path.join(OUTPUT_DIR, f"{job_id}.status")
    if not os.path.exists(status_path):
        return {"status": "not_found"}

    try:
        with open(status_path, "r") as f:
            data = json.load(f)

        if "status" in data and data["status"] == "failed":
            return {"status": "failed", "error": data.get("error")}

        # If it's the initial processing status
        if "status" in data and data["status"] == "processing":
            return {"status": "processing"}

        # If it's finished (contains output files)
        # We wrap the results in 'outputs' and set status to 'done' for the frontend
        outputs = {k: v for k, v in data.items() if k not in ["duration_seconds", "status"]}
        return {
            "status": "done",
            "outputs": outputs,
            "duration_seconds": data.get("duration_seconds")
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}

@app.get("/download/{filename}")
async def download_file(filename: str):
    file_path = os.path.join(OUTPUT_DIR, filename)
    if os.path.exists(file_path):
        return FileResponse(file_path, filename=filename)
    return {"error": "File not found"}

if __name__ == "__main__":
    import uvicorn
    # Start server first so logs are active
    uvicorn.run("app.main:app", host="0.0.0.0", port=9090, reload=True)