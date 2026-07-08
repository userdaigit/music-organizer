#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Shazam 音频指纹识别模块
=============================================
使用 shazamio 库通过 Shazam API 识别歌曲。
完全免费，无需 API Key，全球最大曲库。

依赖:
  - shazamio (pip install shazamio)
  - Python >= 3.10

ShazamIO 项目: https://github.com/dotX12/ShazamIO
"""

import json
import time
import os


def check_shazamio():
    """检查 shazamio 是否可用"""
    try:
        import shazamio
        return True
    except ImportError:
        return False


class ShazamIdentifier:
    """Shazam 音频指纹识别器，带缓存"""

    def __init__(self, cache_file=None):
        self.cache_file = cache_file
        self.cache = {}
        self.available = check_shazamio()
        if cache_file:
            self._load_cache()
        self.last_request_time = 0

    def _load_cache(self):
        if not self.cache_file:
            return
        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                self.cache = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, IOError):
            pass

    def _save_cache(self):
        if not self.cache_file:
            return
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
        except (IOError, TypeError):
            pass

    def is_available(self):
        return self.available

    def identify(self, filepath):
        """
        识别音频文件，返回歌曲信息。
        返回: {title, artist, album} 或 None
        """
        path_str = str(filepath)
        if path_str in self.cache:
            return self.cache[path_str]

        if not self.available:
            return None

        # 限流：1次/秒（Shazam 对逆向 API 比较敏感）
        elapsed = time.time() - self.last_request_time
        if elapsed < 1.2:
            time.sleep(1.2 - elapsed)

        try:
            result = _shazam_recognize(filepath)
            # 修复(Bug L)：无论成功或失败都缓存，避免对同一文件重复慢速重试。
            # 失败结果缓存为 None，下次直接跳过（用户可用 --clear-cache 清除重试）。
            self.cache[path_str] = result
            self._save_cache()
            self.last_request_time = time.time()
            return result
        except Exception:
            self.cache[path_str] = None
            self._save_cache()
            self.last_request_time = time.time()
            return None


def _shazam_recognize(filepath):
    """
    调用 ShazamIO 识别音频文件。
    因为 shazamio 是异步的，需要用 asyncio 包装。
    """
    import asyncio
    from shazamio import Shazam

    async def _recognize():
        shazam = Shazam()
        try:
            # 使用 recognize() (Rust 版本，更快)
            out = await shazam.recognize(str(filepath))
            return out
        except Exception:
            # 回退到旧版 recognize_song()
            try:
                out = await shazam.recognize_song(str(filepath))
                return out
            except Exception:
                return None

    # Python 3.10+: asyncio.get_event_loop() 在无运行循环时已弃用
    # 统一使用 asyncio.run()，它自动创建和关闭事件循环
    try:
        loop = asyncio.get_running_loop()
        # 如果有运行中的事件循环，在新线程中运行避免嵌套
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, _recognize())
            result = future.result(timeout=30)
            return _parse_shazam_result(result)
    except RuntimeError:
        # 没有运行中的事件循环，直接 asyncio.run
        result = asyncio.run(_recognize())
        return _parse_shazam_result(result)


def _parse_shazam_result(result):
    """解析 Shazam 识别结果"""
    if not result:
        return None

    # ShazamIO 返回格式: {'track': {'title': '...', 'subtitle': 'Artist', ...}}
    track = result.get('track', {})
    if not track:
        return None

    title = track.get('title', '')
    subtitle = track.get('subtitle', '')  # 通常是歌手名

    # 尝试从 sections 获取更详细的信息
    sections = track.get('sections', [])
    album = ''
    artist = subtitle
    for section in sections:
        if section.get('type') == 'SONG':
            metadata = section.get('metadata', [])
            for m in metadata:
                if m.get('title') == 'Album':
                    album = m.get('text', '')
                elif m.get('title') == 'Artist':
                    artist = m.get('text', artist)

    if not title:
        return None

    parsed = {
        'title': title,
        'artist': artist or subtitle or '',
        'album': album,
    }
    return parsed if parsed['title'] else None