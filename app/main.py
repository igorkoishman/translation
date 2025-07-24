import json
import os
import uuid
from datetime import datetime

from fastapi import FastAPI, Request, File, UploadFile, Form, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse
import shutil
from dotenv import load_dotenv
from app.auto_subtitles_combined_models import main
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import sys
load_dotenv()
print("Python version:", sys.version)
print("Python executable:", sys.executable)
app = FastAPI()
print("CWD:", os.getcwd())
print("Static exists?", os.path.exists("static"))
print("Static abs path:", os.path.abspath("static"))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)  # /translation


def resolve_project_path(env_var_name: str, default_subdir: str):
    raw = os.getenv(env_var_name, default_subdir)

    # Strip leading '/' to prevent incorrect root-relative resolution
    rel_path = raw.lstrip(os.sep)

    return os.path.normpath(os.path.join(PROJECT_ROOT, rel_path))


# Usage
MODEL_DIR = resolve_project_path("MODEL_DIR", "model")
OUTPUT_DIR = resolve_project_path("OUTPUT_DIR", "outputs")
print("CWD:", os.getcwd())
print("Static exists?", os.path.exists("static"))
print("Static abs path:", os.path.abspath("static"))


BASE_DIR2 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # one level up from app/
STATIC_DIR = os.path.join(BASE_DIR2, "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
print("CWD:", os.getcwd())
print("Static exists?", os.path.exists("static"))
print("Static abs path:", os.path.abspath("static"))


# BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# PARENT_DIR = os.path.dirname(BASE_DIR)
# OUTPUT_DIR = os.getenv("OUTPUT_DIR", os.path.join(BASE_DIR, "outputs"))
# DEFAULT_MODEL_DIR = os.getenv("MODEL_DIR", os.path.join(BASE_DIR, "models"))
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
        processor: str = Form("cpu")
):
    start_time = datetime.now()
    job_id = str(uuid.uuid4())
    ext = file.filename.split('.')[-1]
    input_path = os.path.join(OUTPUT_DIR, f"{job_id}_input.{ext}")
    with open(input_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    langs_list = langs.strip().split()

    model_path = os.path.join(MODEL_DIR, model)
    print(f"🎯 Selected model: {model} (type: {model_type})")
    print(f"📁 Model path: {model_path}")

    output_path = os.path.join(OUTPUT_DIR, f"{job_id}_output.mp4")

    # Call your processing pipeline
    main(
        video_path=input_path,
        output_path_base=output_path,
        model_name_or_dir=MODEL_DIR,
        model_name=model_type,
        backend=model,
        api_key=GOOGLE_API_KEY,
        device=processor,
        output_languages=langs_list
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
    outputs["duration_seconds"] = str(duration)  # Add this line!
    # Save status
    with open(os.path.join(OUTPUT_DIR, f"{job_id}.status"), "w") as f:
        json.dump(outputs, f)

    res = {
        "job_id": job_id,
        "download_url": f"/download/{job_id}.mp4",
        "duration_seconds": duration
    }
    print("---------------------",res,"---------------------")
    return res
@app.get("/status/{job_id}")
def status(job_id: str):
    status_path = os.path.join(OUTPUT_DIR, f"{job_id}.status")
    if os.path.exists(status_path):
        with open(status_path) as f:
            outputs = json.load(f)

        # Extract duration_seconds (if exists)
        duration = outputs.get("duration_seconds", None)

        # Filter only string values that exist as files
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
    uvicorn.run("main:app", host="0.0.0.0", port=8181, reload=True)
