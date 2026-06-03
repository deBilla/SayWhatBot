FROM python:3.12-slim

WORKDIR /app

# ffmpeg is used to transcode incoming audio to 16kHz mono WAV before sending it
# to Whisper. Decoding from a seekable file (vs. the webservice's stdin pipe) is
# what makes container formats like m4a/mp4 work reliably.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# SQLite database lives here (bind-mounted in docker-compose)
RUN mkdir -p /app/data

EXPOSE 8000

CMD ["python", "-u", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
