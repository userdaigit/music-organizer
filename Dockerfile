FROM python:3.11-slim

LABEL maintainer="music-organizer"
LABEL description="Music library organizer with metadata scraping and fingerprinting"
LABEL version="1.2.0"

# 安装系统依赖
# chromaprint-tools: fpcalc (音频指纹识别)
# ffmpeg: 音频格式转换（可选）
# locales: 中文语言支持
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromaprint-tools \
    ffmpeg \
    locales \
    && rm -rf /var/lib/apt/lists/* \
    && echo "zh_CN.UTF-8 UTF-8" > /etc/locale.gen \
    && locale-gen

ENV LANG=zh_CN.UTF-8
ENV LC_ALL=zh_CN.UTF-8

WORKDIR /app

# 安装 Python 依赖
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# 复制脚本
COPY organize_music.py /app/organize_music.py
COPY encoding_fix.py /app/encoding_fix.py
COPY artist_normalizer.py /app/artist_normalizer.py
COPY scraper.py /app/scraper.py
COPY kugou_scraper.py /app/kugou_scraper.py
COPY netease_scraper.py /app/netease_scraper.py
COPY fingerprint.py /app/fingerprint.py
COPY shazam_fingerprint.py /app/shazam_fingerprint.py
COPY progress.py /app/progress.py
COPY version.py /app/version.py
COPY name_map.json /config/name_map.json

# 配置目录
VOLUME /config
VOLUME /music
VOLUME /music2

# 默认输出报告到 /config 目录
ENV NAME_MAP_PATH=/config/name_map.json

ENTRYPOINT ["python3", "/app/organize_music.py"]
CMD ["--source", "/music", "--output", "/music2", "--name-map", "/config/name_map.json", "--write-tags"]
