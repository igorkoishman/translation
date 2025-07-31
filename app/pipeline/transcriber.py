# app/pipeline/transcriber.py
import shutil

import whisperx
import importlib.util
import os
import ssl
import glob
import torch
from .base import Transcriber

class FasterWhisperTranscriber(Transcriber):
    def __init__(self, models_root, backend_name, model_size, device="cuda"):
        self.models_root = models_root
        self.backend_name = backend_name
        self.model_size = model_size
        self.device = device

    def get_model_path(self):
        folder_name = f"{self.backend_name}-{self.model_size}"
        return os.path.join(self.models_root, folder_name)

    def transcribe(self, audio_path, language=None,align_output=True):
        model_path = self.get_model_path()
        compute_type = "int8_float32" if self.device.startswith("cuda") else "float32"
        if not os.path.isdir(model_path) or not os.listdir(model_path):
            # Download model if not present
            os.makedirs(model_path, exist_ok=True)
            os.environ["HF_HUB_DISABLE_SSL_VERIFICATION"] = "1"
            ssl._create_default_https_context = ssl._create_unverified_context
            whisperx.load_model(
                self.model_size,
                device=self.device,
                compute_type=compute_type,
                download_root=model_path,
                local_files_only=False
            )
            flatten_whisper_snapshot(model_path)
        model = whisperx.load_model(
            model_path, device=self.device, compute_type=compute_type, local_files_only=True
        )
        result = model.transcribe(audio_path, language=language)
        language = result["language"]
        if align_output:
            print(f"Aliging Rows")
            try:
                model_a, metadata = whisperx.load_align_model(language_code=language, device= self.device)
                print("Starting alignment...")
                result = whisperx.align(result["segments"], model_a, metadata, audio_path,  self.device)
                print("Alignment finished.")
            except Exception as e:
                print(f"⚠️ Alignment failed: {e}")
        return result,language

# class OpenAIWhisperTranscriber(Transcriber):
#     def __init__(self, model_size, device="cpu"):
#         self.model_size = model_size
#         self.device = device
#
#     def transcribe(self, audio_path, language=None):
#         spec = importlib.util.find_spec("whisper")
#         if not spec:
#             raise ImportError("OpenAI Whisper not found.")
#         openai_whisper = importlib.util.module_from_spec(spec)
#         spec.loader.exec_module(openai_whisper)
#         model = openai_whisper.load_model(self.model_size, device=self.device)
#         transcribed = model.transcribe(audio_path, language=language)
#         model_a, metadata = whisperx.load_align_model(language_code=transcribed.get("language", language or "und"), device=self.device)
#         aligned = whisperx.align(transcribed["segments"], model_a, metadata, audio_path, self.device)
#         return {
#             aligned,
#             transcribed.get("language", language or "und")
#         }

class OpenAIWhisperTranscriber(Transcriber):
    def __init__(self, models_root,backend_name,model_size,device):
        self.models_root = models_root
        self.device = device
        self.backend_name = backend_name
        self.model_size = model_size

    def get_model_path(self):
        folder_name = f"{self.backend_name}-{self.model_size}"
        return os.path.join(self.models_root, folder_name)

    def transcribe(self, audio_path, language=None):
        model_path = self.get_model_path()
        os.makedirs(model_path, exist_ok=True)
        spec = importlib.util.find_spec("whisper")
        if not spec:
            raise ImportError("OpenAI Whisper not found.")
        openai_whisper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(openai_whisper)

        # Optionally download to model_dir; otherwise, uses default cache
        model_kwargs = {"device": self.device}
        if model_path is not None:
            model_kwargs["download_root"] = model_path

        model = openai_whisper.load_model(self.model_size, **model_kwargs)
        transcribed = model.transcribe(audio_path, language=language)
        model_a, metadata = whisperx.load_align_model(
            language_code=transcribed.get("language", language or "und"),
            device=self.device
        )
        aligned = whisperx.align(transcribed["segments"], model_a, metadata, audio_path, self.device)
        return  aligned,transcribed["language"]



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