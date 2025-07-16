FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y git ffmpeg

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Find the hash dir (snapshot)
RUN python3 -c "from faster_whisper import WhisperModel; WhisperModel('small', download_root='/models/faster-whisper-small')"
RUN SNAP_DIR=$(find /models/faster-whisper-small/models--*--faster-whisper-small/snapshots -mindepth 1 -maxdepth 1 -type d | head -n1) && \
    cp -rL $SNAP_DIR/. /models/faster-whisper-small/ && \
    rm -rf /models/faster-whisper-small/models--*

COPY . /app

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]