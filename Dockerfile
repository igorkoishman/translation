FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y git ffmpeg

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Download the model to a persistent directory
RUN python3 -c "from faster_whisper import WhisperModel; WhisperModel('small', download_root='/models/faster-whisper-small')"

# (NO NEED TO COPY/FLATTEN SNAPSHOT DIR!)
# The model loader will find the snapshot in /models/faster-whisper-small as needed.

COPY . /app

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]