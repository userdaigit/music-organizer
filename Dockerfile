FROM python:3.12-slim

LABEL description="飞牛NAS 音乐库一键整理工具 v1.0"

# 安装 chromaprint（音频指纹识别依赖）和 ffmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromaprint-tools \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# 复制脚本
COPY organize_music.py /app/organize_music.py
COPY encoding_fix.py /app/encoding_fix.py
COPY artist_normalizer.py /app/artist_normalizer.py
COPY scraper.py /app/scraper.py
COPY fingerprint.py /app/fingerprint.py
COPY name_map.json /config/name_map.json

WORKDIR /app

ENTRYPOINT ["python3", "/app/organize_music.py"]