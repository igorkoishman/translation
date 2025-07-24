import json
import os
import uuid
from fastapi import FastAPI, File, UploadFile, Form, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse
import shutil
from dotenv import load_dotenv
# from auto_subtitles import main as subtitle_main  # Import your main()
# from .auto_subtitles import main as subtitle_main
from app.auto_subtitles import main as subtitle_main

app = FastAPI()




load_dotenv()
OUTPUT_DIR = os.getenv("OUTPUT_DIR")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")

# BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
# MODEL_PATH = os.environ.get("MODEL_PATH", os.path.join(BASE_DIR, "models", "faster-whisper-small"))
# BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# default_model_path = os.path.join(BASE_DIR, "models", "faster-whisper-small")
# MODEL_PATH = os.getenv("MODEL_PATH", default_model_path)
# MODEL_PATH = os.getenv("MODEL_PATH", "/models/faster-whisper-small")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # Adjust if main.py is inside 'app/'
MODEL_PATH = os.getenv("MODEL_PATH", os.path.join(BASE_DIR, "models/faster-whisper-small"))
print(f"MODEL_PATH resolved to 2: {MODEL_PATH}")
if not os.path.isabs(MODEL_PATH):
    print("absulute method")
    # If running from inside 'app/', go up one level
    BASE_DIR = os.path.dirname(BASE_DIR)
    MODEL_PATH = os.path.abspath(os.path.join(BASE_DIR, MODEL_PATH))
    OUTPUT_DIR = os.path.abspath(os.path.join(BASE_DIR, "outputs"))
# OUTPUT_DIR = os.getenv("OUTPUT_DIR", os.path.join(BASE_DIR, "outputs"))
os.makedirs(OUTPUT_DIR, exist_ok=True)
print(f"BASE_DIR resolved to 2: {BASE_DIR}")
print(f"MODEL_PATH resolved to 2: {MODEL_PATH}")
print(f"OUTPUT_DIR resolved to 2: {OUTPUT_DIR}")
print(f"Exists? {os.path.isdir(MODEL_PATH)}")

@app.get("/", response_class=HTMLResponse)
async def home():
    return """
    <h1>Auto Subtitle Generator</h1>
    <form id="upload-form" enctype="multipart/form-data">
        <input type="file" id="file-input" name="file" accept="video/*" />
        <input type="text" id="langs" name="langs" placeholder="Languages (e.g. he ru)" />
        <button type="submit">Upload & Process</button>
    </form>
    <div id="progress"></div>
    <div id="result"></div>
    <script>
    const form = document.getElementById('upload-form');
    form.onsubmit = async (e) => {
        e.preventDefault();
        const fileInput = document.getElementById('file-input');
        const langs = document.getElementById('langs').value;
        const formData = new FormData();
        formData.append('file', fileInput.files[0]);
        formData.append('langs', langs);
        document.getElementById('progress').innerText = 'Uploading...';
        const res = await fetch('/upload', { method: 'POST', body: formData });
        const data = await res.json();
        document.getElementById('progress').innerText = 'Processing...';
        checkStatus(data.job_id);
    };
    async function checkStatus(job_id) {
        const res = await fetch('/status/' + job_id);
        const data = await res.json();
        if (data.status === 'done') {
    let links = '';
    for (const [label, file] of Object.entries(data.outputs)) {
        links += `<div><a href="/download/${file}">${label}</a></div>`;
    }
    document.getElementById('result').innerHTML = links;
    document.getElementById('progress').innerText = 'Done!';
} else {
            setTimeout(() => checkStatus(job_id), 2000);
        }
    }
    </script>
    """


@app.post("/upload")
async def upload_video(file: UploadFile = File(...), langs: str = Form("")):
    job_id = str(uuid.uuid4())
    ext = file.filename.split('.')[-1]
    input_path = os.path.join(OUTPUT_DIR, f"{job_id}_input.{ext}")
    with open(input_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    output_path = os.path.join(OUTPUT_DIR, f"{job_id}_output.mp4")
    langs_list = langs.strip().split()
    # Call your main pipeline
    subtitle_main(input_path, output_path, MODEL_PATH,api_key=GOOGLE_API_KEY, output_languages=langs_list)

    # --- Build outputs dict for all generated files ---
    outputs = {
        "orig": f"{job_id}_output_orig.mp4",
        "orig_srt": f"{job_id}_output_orig.srt",
    }
    for lang in langs_list:
        outputs[lang] = f"{job_id}_output_{lang}.mp4"
        outputs[f"{lang}_srt"] = f"{job_id}_output_{lang}.srt"

    # Save status as JSON
    with open(os.path.join(OUTPUT_DIR, f"{job_id}.status"), "w") as f:
        json.dump(outputs, f)

    return {"job_id": job_id}


# @app.post("/upload")
# async def upload_video(file: UploadFile = File(...), langs: str = Form("")):
#     job_id = str(uuid.uuid4())
#     ext = file.filename.split('.')[-1]
#     input_path = os.path.join(OUTPUT_DIR, f"{job_id}_input.{ext}")
#     with open(input_path, "wb") as f:
#         shutil.copyfileobj(file.file, f)
#     # Queue processing
#     output_path = os.path.join(OUTPUT_DIR, f"{job_id}_output.mp4")
#     langs_list = langs.strip().split()
#     # You could use BackgroundTasks for async jobs, or Celery for real jobs
#     subtitle_main(input_path, output_path, MODEL_PATH, output_languages=langs_list)
#     # Save job status (very simple version, production would use a database)
#     with open(os.path.join(OUTPUT_DIR, f"{job_id}.status"), "w") as f:
#         f.write(output_path)
#     return {"job_id": job_id}

# @app.get("/status/{job_id}")
# def status(job_id: str):
#     status_path = os.path.join(OUTPUT_DIR, f"{job_id}.status")
#     if os.path.exists(status_path):
#         with open(status_path) as f:
#             output_file = os.path.basename(f.read().strip())
#         return {"status": "done", "output_file": output_file}
#     else:
#         return {"status": "processing"}

# @app.get("/status/{job_id}")
# def status(job_id: str):
#     status_path = os.path.join(OUTPUT_DIR, f"{job_id}.status")
#     if os.path.exists(status_path):
#         with open(status_path) as f:
#             outputs = json.load(f)
#         # Only show links to files that actually exist
#         files = {k: v for k, v in outputs.items() if os.path.isfile(os.path.join(OUTPUT_DIR, v))}
#         return {"status": "done", "outputs": files}
#     else:
#         return {"status": "processing"}

@app.get("/status/{job_id}")
def status(job_id: str):
    status_path = os.path.join(OUTPUT_DIR, f"{job_id}.status")
    if os.path.exists(status_path):
        with open(status_path) as f:
            outputs = json.load(f)
        # Only show links to files that actually exist
        files = {k: v for k, v in outputs.items() if os.path.isfile(os.path.join(OUTPUT_DIR, v))}
        return {"status": "done", "outputs": files}
    else:
        return {"status": "processing"}

@app.get("/download/{output_file}")
def download_file(output_file: str):
    path = os.path.join(OUTPUT_DIR, output_file)
    return FileResponse(path, media_type="video/mp4", filename=output_file)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8181, reload=True)