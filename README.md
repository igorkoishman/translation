# Auto Subtitle Generator

A high-performance web application for automatic transcription and translation of large video files using OpenAI Whisper and Meta's NLLB/M2M100 models.

## 🚀 Key Features & Optimizations

### 1. GPU Acceleration (RTX 3060 Ti)
- **Engine:** Powered by `torch` 2.6.0+cu124.
- **Performance:** Transcription and alignment utilize CUDA for near real-time processing of large media.

### 2. Large File Efficiency (Staging Logic)
- **Problem:** Browser-based re-uploads of 30GB+ files are slow and redundant.
- **Solution:** Integrated "Staging" workflow.
  - Files are uploaded once during the **Analysis** phase.
  - The server retains the file in a staging area (`/tmp` or symlinked `output/`).
  - Upon clicking "Start," the server **moves** the already-staged file instead of requesting a re-upload.

### 3. Filesystem Optimization (SSD for Code/Venv)
- **Trick:** Moving the project from a slow NAS/HDD (`/mnt/d/`) to the internal WSL SSD (`/home/igorkoishman/translation/`) resulted in:
  - **Torch Import Speed:** 30s+ reduced to <2s.
  - **UI Responsiveness:** Instant startup and logging.
- **Note:** Keep the massive `model/` (~35GB) and `output/` folders on the larger D: drive via symlinks to save SSD space while maintaining speed for the code and dependencies.

### 4. Robust Translation
- **Safetensors:** Uses the latest `safetensors` format for secure and fast model loading.
- **Language Trimming:** Automatically handles leading/trailing spaces in language inputs (e.g., `" en"` -> `"en"`) to prevent library crashes.

## 📁 Project Structure

- `app/main.py`: FastAPI backend, job orchestration, and staging logic.
- `app/pipeline/`: Core AI logic (Transcriber, Translator, FFmpeg burning).
- `static/js/upload.js`: Frontend logic for file progress, staging, and status tracking.
- `logs/`: Application and server output logs with full timestamps.
- `model/`: (Symlinked to D:) Storage for ~35GB of AI model weights.
- `output/`: (Symlinked to D:) Final processed videos and SRT files.

## 🛠 Usage & Tricks

### Monitoring Progress
Always trace the logs in real-time to see detailed GPU and processing status:
```bash
tail -f logs/startup_final.log
```

### Networking in WSL2
If `localhost:9090` doesn't respond in Windows, use the WSL IP directly:
`http://<WSL_IP>:9090` (Check IP with `ip addr show eth0`).

### Running the App
Ensure `PYTHONPATH` is set to the project root:
```bash
export PYTHONPATH=.
./venv/bin/python app/main.py
```

## 📝 Current Status
- Branch: `feature/large-file-upload-logging`
- Environment: Fully migrated to SSD with D: drive symlinks for heavy assets.
- Fixes: Staging upload, Torch security vulnerability, Language input bugs, and Translation duplicate arguments are all resolved.
