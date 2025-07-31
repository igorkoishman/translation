# app/main.py

import os
import secrets
from datetime import datetime
from fastapi import FastAPI, Request, File, UploadFile, Form
from fastapi.responses import FileResponse, HTMLResponse
import shutil
from dotenv import load_dotenv
from app.auto_subtitles import AutoSubtitlePipeline
from app.pipeline.transcriber import FasterWhisperTranscriber, OpenAIWhisperTranscriber
from app.pipeline.translator import LocalLLMTranslate
from app.pipeline.burner import FFmpegBurner
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import json

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
        align: str = Form("True"),
        original_lang: str = Form("")
):
    start_time = datetime.now()
    splitterd=file.filename.split('.')
    ext = splitterd[-1]
    job_id = f"{splitterd[0]}_{secrets.token_hex(4)}"
    input_path = os.path.join(OUTPUT_DIR, f"{job_id}_input.{ext}")
    align = align or None
    if not original_lang:
        original_lang = None
    with open(input_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    langs_list = langs.strip().split()
    model_path = os.path.join(MODEL_DIR, model)
    output_path = os.path.join(OUTPUT_DIR, f"{job_id}_output.{ext}")
    ml_device, video_device = resolve_device(user_device=processor)
    # Pipeline construction
    if model_type == "faster-whisper":
        transcriber = FasterWhisperTranscriber(MODEL_DIR, model_type, model, ml_device)
    else:
        transcriber = OpenAIWhisperTranscriber(MODEL_DIR,model_type,model, ml_device)
    burner = FFmpegBurner()

    translator = None
    if langs_list:
        translator = LocalLLMTranslate()
    pipeline = AutoSubtitlePipeline(transcriber, burner, translator)

    # Run
    pipeline.process(
        video_path=input_path,
        output_path_base=output_path,
        output_languages=langs_list,
        language=original_lang,
        device=video_device,
        align_output=align
    )

    # Save outputs
    outputs = {
        "orig": f"{job_id}_output_orig.{ext}",
        "orig_srt": f"{job_id}_output_orig.srt",
    }
    for lang in langs_list:
        outputs[lang] = f"{job_id}_output_{lang}.{ext}"
        outputs[f"{lang}_srt"] = f"{job_id}_output_{lang}.srt"
    duration = round((datetime.now() - start_time).total_seconds(), 2)
    outputs["duration_seconds"] = str(duration)
    with open(os.path.join(OUTPUT_DIR, f"{job_id}.status"), "w") as f:
        json.dump(outputs, f)
    res = {
        "job_id": job_id,
        "download_url": f"/download/{job_id}.{ext}",
        "duration_seconds": duration
    }
    return res

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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)


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