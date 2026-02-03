FROM python:3.11-slim

# ── Install FFmpeg + Opus support + Node.js for build tools ──
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ffmpeg \
      libopus0 \
      opus-tools \
      git \
      nodejs \
      npm \
      bc \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Create sounds directory ──
RUN mkdir -p /app/sounds \
    && chmod 777 /app/sounds

# ── Create non-root user with configurable UID/GID ──
ARG UID=1000
ARG GID=1000
RUN groupadd -g $GID app && useradd -u $UID -g app -m app

# ── Install Node.js build tools ──
RUN npm install -g terser

# ── Copy build scripts first ──
COPY scripts/build.sh scripts/

# ── Copy app source ──
COPY . .

# ── Add entrypoint ──
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-u", "-m", "memer.bot"]
