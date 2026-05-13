FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /models /work

WORKDIR /app

COPY pyproject.toml .
COPY docker-constraints.txt .
COPY ydbi_speaker ./ydbi_speaker

RUN python -m venv /venv
RUN /venv/bin/pip install --no-cache-dir -U pip
RUN /venv/bin/pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.11.0 torchaudio==2.11.0
RUN /venv/bin/pip install --no-cache-dir -c docker-constraints.txt .

ENV PATH=/venv/bin:$PATH

CMD ["ydbi-speaker"]
