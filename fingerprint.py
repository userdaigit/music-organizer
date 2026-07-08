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
    (Docker 中可安装: apt-get install -y libchromaprint-tools)

参考:
  - pyacoustid: https://github.com/beetbox/pyacoustid
  - AcoustID API: https://acoustid.org/webservice
  - AcoustID API 限流: 3次/秒
"""

import os
import time
import json
import urllib.request
import urllib.parse

# AcoustID API Key
# ==========================================
# 配置说明（二选一）:
#
# 方式1（推荐）: 设置环境变量 ACOUSTID_API_KEY
#   Linux/macOS: export ACOUSTID_API_KEY="你的KEY"
#   Windows:     set ACOUSTID_API_KEY=你的KEY
#   Docker:      在 docker-compose.yml 的 environment 中设置
#
# 方式2: 修改下方第 42 行的占位符
#   在 https://acoustid.org/api-key 申请免费 API Key
#   将 YOUR_ACOUSTID_API_KEY_HERE 替换为你的 KEY
#
# ==========================================

# >>> 第 42 行: 将 YOUR_ACOUSTID_API_KEY_HERE 替换为你的 AcoustID API Key <<<
DEFAULT_API_KEY = 'YOUR_ACOUSTID_API_KEY_HERE'
ACOUSTID_API_KEY = os.environ.get('ACOUSTID_API_KEY', DEFAULT_API_KEY)

# 已知的占位符和公开测试KEY，用于检测用户是否未配置
_PLACEHOLDER_KEY = 'YOUR_ACOUSTID_API_KEY_HERE'
_KNOWN_TEST_KEYS = {'lmv7m8k7Fe'}

# AcoustID API 基础 URL
ACOUSTID_BASE_URL = "https://api.acoustid.org/v2"


def is_default_key(api_key=None):
    """检查是否为未配置的占位符 KEY 或已知的公开测试 KEY"""
    key = api_key or ACOUSTID_API_KEY
    return key == _PLACEHOLDER_KEY or key in _KNOWN_TEST_KEYS


def validate_api_key(api_key=None, timeout=5):
    """
    向 AcoustID 发送测试请求验证 KEY 有效性。

    返回:
        True  - KEY 有效
        False - KEY 无效（被拒绝）
        None  - 网络错误，无法判断
    """
    key = api_key or ACOUSTID_API_KEY
    try:
        # 发送一个最简单的 lookup 请求（不带 fingerprint）
        # 有效 KEY: 返回 {"status": "ok", "results": []}
        # 无效 KEY: 返回 {"status": "error", "error": {"message": "invalid API key", "code": 6}}
        params = urllib.parse.urlencode({
            'format': 'json',
            'client': key,
            'duration': 0,
            'fingerprint': '',
        })
        url = f"{ACOUSTID_BASE_URL}/lookup?{params}"
        req = urllib.request.Request(url, headers={'User-Agent': 'MusicOrganizer/1.2.0'})
        resp = urllib.request.urlopen(req, timeout=timeout)
        data = json.loads(resp.read().decode('utf-8'))

        if data.get('status') == 'ok':
            return True
        elif data.get('status') == 'error':
            error_msg = data.get('error', {}).get('message', '')
            if 'invalid' in error_msg.lower() and 'key' in error_msg.lower():
                return False
            return False
        return None
    except Exception:
        return None


def check_fpcalc():
    """
    检查音频指纹后端是否可用。

    依次检测:
      1. pyacoustid Python 包（提供 acoustid.match / fingerprint_file）
      2. chromaprint 命令行工具 (fpcalc)
    只要任一可用即返回 True。
    """
    try:
        import acoustid  # noqa: F401
        return True
    except ImportError:
        pass
    # 回退: 检测 fpcalc 命令行工具
    import shutil
    return shutil.which('fpcalc') is not None


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

        # 取最佳匹配
        # 注意: acoustid.match() 返回生成器，网络请求在迭代时才实际发生，
        # 所以 for 循环必须在 try/except 内部
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
    except acoustid.NoBackendError:
        return None
    except acoustid.WebServiceError:
        return None
    except Exception:
        return None

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

    def __init__(self, api_key=None, cache=None, cache_file=None):
        """
        初始化指纹识别器。

        Args:
            api_key:    AcoustID API Key
            cache:      缓存字典（内存缓存）
            cache_file: 缓存文件路径（JSON格式，持久化到磁盘）
        """
        self.api_key = api_key or ACOUSTID_API_KEY
        self.cache_file = cache_file
        self.cache = cache or {}
        # 如果指定了缓存文件，加载已有缓存
        if cache_file:
            self._load_cache()
        self.available = check_fpcalc()
        self.last_request_time = 0
        # KEY 有效性状态：None=未检查, True=有效, False=无效, "default"=默认KEY
        self._key_status = None
        self._check_key_status()

    def _load_cache(self):
        """从磁盘加载缓存"""
        if not self.cache_file:
            return
        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                self.cache.update(data)
        except (FileNotFoundError, json.JSONDecodeError, IOError):
            pass

    def _save_cache(self):
        """保存缓存到磁盘"""
        if not self.cache_file:
            return
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
        except (IOError, TypeError):
            pass

    def _check_key_status(self):
        """检查 API KEY 状态"""
        if is_default_key(self.api_key):
            self._key_status = "default"
        else:
            # 非默认 KEY，假设有效（实际验证在首次识别时发生）
            # AcoustID API 没有专门的 KEY 验证端点，/lookup 需要有效指纹
            # 发送空指纹会返回 400 Bad Request，不是有效的验证方式
            self._key_status = True

    def identify(self, filepath):
        """识别文件，带缓存"""
        path_str = str(filepath)
        if path_str in self.cache:
            return self.cache[path_str]

        if not self.available:
            return None

        # 检查 KEY 状态
        if self._key_status in ("default", False):
            return None

        # AcoustID 限流: 3次/秒
        elapsed = time.time() - self.last_request_time
        if elapsed < 0.4:
            time.sleep(0.4 - elapsed)

        # pyacoustid 已安装 -> 直接使用
        result = identify_file(filepath, self.api_key)
        if result is not None:
            self.last_request_time = time.time()
            self.cache[path_str] = result
            self._save_cache()
            return result

        # pyacoustid 失败但 chromaprint 命令行可用 -> 尝试 fpcalc
        # (此场景需额外实现, 当前先返回 None)
        return None

    def is_available(self):
        """
        检查指纹识别功能是否可用（整体可用性）。
        需要 后端(pyacoustid/fpcalc) + 有效（非默认）API KEY 同时满足。
        """
        if not self.available:
            return False
        if self._key_status in ("default", False):
            return False
        return True

    def is_backend_available(self):
        """
        检查后端是否可用（pyacoustid 或 fpcalc 命令行工具）。
        不检查 API KEY 状态。
        """
        return self.available

    def get_key_status(self):
        """
        返回 KEY 状态描述。
        - "default": 使用默认测试 KEY，未配置
        - True: KEY 有效
        - False: KEY 无效
        """
        return self._key_status