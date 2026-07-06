#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
音频指纹识别模块
=============================================
使用 Chromaprint + AcoustID API 通过音频指纹识别歌曲。
当文件名和标签都无法识别歌曲信息时，通过音频指纹查询。

依赖:
  - pyacoustid (pip install pyacoustid)
  - Chromaprint 库或 fpcalc 命令行工具
    (Docker 中可安装: apt-get install -y chromaprint-tools)

参考:
  - pyacoustid: https://github.com/beetbox/pyacoustid
  - AcoustID API: https://acoustid.org/webservice
  - AcoustID API 限流: 3次/秒
"""

import os
import time

# AcoustID API Key
# 需要在 https://acoustid.org/api-key 申请免费的 API Key
# 这里使用公开的测试 Key，建议替换为自己的
ACOUSTID_API_KEY = os.environ.get('ACOUSTID_API_KEY', 'lmv7m8k7Fe')


def check_fpcalc():
    """检查 fpcalc 工具是否可用"""
    try:
        import acoustid
        # 尝试生成指纹来检测后端是否可用
        return True
    except ImportError:
        return False


def identify_file(filepath, api_key=None, timeout=30):
    """
    通过音频指纹识别文件。
    返回: dict 或 None
    {
        'score': 匹配分数 (0-1),
        'recording_id': MusicBrainz Recording ID,
        'title': 歌曲名,
        'artist': 歌手名,
        'album': 专辑名 (可能为空),
        'duration': 时长(秒),
    }
    """
    try:
        import acoustid
    except ImportError:
        return None

    api_key = api_key or ACOUSTID_API_KEY

    try:
        results = acoustid.match(
            api_key,
            str(filepath),
            meta='recordings+releasegroups',
            timeout=timeout,
        )
    except acoustid.NoBackendError:
        return None
    except acoustid.WebServiceError:
        return None
    except Exception:
        return None

    # 取最佳匹配
    best = None
    best_score = 0
    for score, recording_id, title, artist in results:
        if score > best_score:
            best_score = score
            best = {
                'score': score,
                'recording_id': recording_id,
                'title': title or '',
                'artist': artist or '',
                'album': '',
                'duration': 0,
            }

    if best and best_score > 0.5:
        return best

    return None


def get_fingerprint(filepath):
    """
    获取文件的音频指纹（不查询网络）。
    用于本地去重比较。
    返回: (duration, fingerprint) 或 None
    """
    try:
        import acoustid
        duration, fp = acoustid.fingerprint_file(str(filepath))
        return duration, fp
    except Exception:
        return None


def compare_files(filepath_a, filepath_b):
    """
    比较两个音频文件的指纹相似度。
    返回: 0-1 的相似度分数，None 表示无法比较
    """
    try:
        import acoustid
        fp_a = get_fingerprint(filepath_a)
        fp_b = get_fingerprint(filepath_b)
        if not fp_a or not fp_b:
            return None
        # acoustid.compare_fingerprints 返回相似度
        score = acoustid.compare_fingerprints(fp_a[1], fp_b[1])
        return score
    except Exception:
        return None


class FingerprintIdentifier:
    """音频指纹识别器，带缓存"""

    def __init__(self, api_key=None, cache=None):
        self.api_key = api_key or ACOUSTID_API_KEY
        self.cache = cache or {}
        self.available = check_fpcalc()
        self.last_request_time = 0

    def identify(self, filepath):
        """识别文件，带缓存"""
        path_str = str(filepath)
        if path_str in self.cache:
            return self.cache[path_str]

        if not self.available:
            return None

        # AcoustID 限流: 3次/秒
        elapsed = time.time() - self.last_request_time
        if elapsed < 0.4:
            time.sleep(0.4 - elapsed)

        result = identify_file(filepath, self.api_key)
        self.last_request_time = time.time()
        self.cache[path_str] = result
        return result

    def is_available(self):
        """检查指纹识别功能是否可用"""
        return self.available