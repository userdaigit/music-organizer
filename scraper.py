#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
网络刮削模块
=============================================
通过 MusicBrainz API 查询和补全音乐元数据。
支持：歌手信息查询、专辑查询、录音（歌曲）查询。

参考:
  - MusicBrainz API: https://musicbrainz.org/doc/MusicBrainz_API
  - 限流: 每秒最多1次请求
  - 需要设置 User-Agent
"""

import re
import json
import time
import datetime
import urllib.request
import urllib.parse
from version import MB_USER_AGENT

MB_API_BASE = "https://musicbrainz.org/ws/2"
# User-Agent 从 version.py 统一管理，必须包含联系方式，否则会被 MusicBrainz 限流
# 参考: https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting


def _mb_request(path, params, timeout=10):
    """发送 MusicBrainz API 请求"""
    params['fmt'] = 'json'
    query = urllib.parse.urlencode(params)
    url = f"{MB_API_BASE}/{path}?{query}"

    req = urllib.request.Request(url)
    req.add_header('User-Agent', MB_USER_AGENT)
    req.add_header('Accept', 'application/json')

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception:
        return None


class MusicBrainzScraper:
    """MusicBrainz 网络刮削器"""

    def __init__(self, cache_file=None):
        self.cache_file = cache_file
        self.cache = {}
        self.last_request_time = 0
        self._load_cache()

    def _load_cache(self):
        if not self.cache_file:
            return
        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                self.cache = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.cache = {}

    def _save_cache(self):
        if not self.cache_file:
            return
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _rate_limit(self):
        """MusicBrainz 限流：每秒最多1次请求"""
        elapsed = time.time() - self.last_request_time
        if elapsed < 1.1:
            time.sleep(1.1 - elapsed)
        self.last_request_time = time.time()

    def search_recording(self, title, artist='', timeout=10):
        """
        搜索录音（歌曲）信息。
        返回: dict 或 None
        {
            'title': 歌曲名,
            'artist': 歌手名,
            'album': 专辑名,
            'year': 年份,
            'mbid': Recording ID,
        }
        """
        cache_key = f"rec:{artist}:{title}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        query_parts = []
        if title:
            query_parts.append(f'recording:"{title}"')
        if artist:
            query_parts.append(f'artist:"{artist}"')
        query = ' AND '.join(query_parts) if query_parts else title

        self._rate_limit()
        data = _mb_request('recording', {
            'query': query,
            'limit': 3,
        }, timeout)

        if not data or not data.get('recordings'):
            self.cache[cache_key] = None
            self._save_cache()
            return None

        rec = data['recordings'][0]

        result = {
            'title': rec.get('title', ''),
            'artist': '',
            'album': '',
            'year': '',
            'mbid': rec.get('id', ''),
        }

        # 提取歌手
        if 'artist-credit' in rec and rec['artist-credit']:
            credit = rec['artist-credit'][0]
            result['artist'] = credit.get('name', '') if isinstance(credit, dict) else str(credit)

        # 提取专辑和年份
        if 'release-groups' in rec and rec['release-groups']:
            rg = rec['release-groups'][0]
            result['album'] = rg.get('title', '')
            if 'first-release-date' in rg:
                date = rg['first-release-date']
                year_match = re.search(r'(\d{4})', date)
                if year_match:
                    result['year'] = year_match.group(1)

        self.cache[cache_key] = result
        self._save_cache()
        return result

    def search_release(self, album, artist='', timeout=10):
        """
        搜索专辑（Release）信息。
        返回: dict 或 None
        {
            'album': 专辑名,
            'artist': 歌手名,
            'year': 年份,
            'track_count': 曲目数,
            'mbid': Release ID,
        }
        """
        cache_key = f"rel:{artist}:{album}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        query_parts = []
        if album:
            query_parts.append(f'release:"{album}"')
        if artist:
            query_parts.append(f'artist:"{artist}"')
        query = ' AND '.join(query_parts) if query_parts else album

        self._rate_limit()
        data = _mb_request('release', {
            'query': query,
            'limit': 3,
        }, timeout)

        if not data or not data.get('releases'):
            self.cache[cache_key] = None
            self._save_cache()
            return None

        rel = data['releases'][0]

        result = {
            'album': rel.get('title', ''),
            'artist': '',
            'year': '',
            'track_count': 0,
            'mbid': rel.get('id', ''),
        }

        if 'artist-credit' in rel and rel['artist-credit']:
            credit = rel['artist-credit'][0]
            result['artist'] = credit.get('name', '') if isinstance(credit, dict) else str(credit)

        if 'date' in rel:
            year_match = re.search(r'(\d{4})', rel['date'])
            if year_match:
                result['year'] = year_match.group(1)

        if 'mediums' in rel and rel['mediums']:
            for medium in rel['mediums']:
                if 'track-count' in medium:
                    result['track_count'] += medium['track-count']

        self.cache[cache_key] = result
        self._save_cache()
        return result

    @staticmethod
    def _validate_year(year):
        """校验年份：拒绝当前年份（可能是错误返回）"""
        if not year:
            return False
        current_year = datetime.datetime.now().year
        try:
            y = int(year)
            # 修复(Bug G)：原 `>=` 拒绝当前年份，导致今年发行歌曲年份被丢弃。改为仅拒绝未来年份。
            if y > current_year:
                return False
            # 拒绝不合理的年份（早于1900）
            if y < 1900:
                return False
            return True
        except (ValueError, TypeError):
            return False

    def enrich_metadata(self, meta, use_fingerprint=None):
        """
        补全元数据。
        当标签和文件名都无法提供完整信息时，尝试网络查询补全。

        Args:
            meta: 现有元数据字典
            use_fingerprint: 可选的指纹识别回调函数

        Returns:
            补全后的元数据字典，以及是否有修改的标志
        """
        result = dict(meta)
        changed = False

        # 策略1：如果歌手和歌名都有，直接查录音
        if result.get('artist') and result.get('title') and result['artist'] != '未知歌手':
            mb_rec = self.search_recording(result['title'], result['artist'])
            if mb_rec:
                if not result.get('album') and mb_rec.get('album'):
                    result['album'] = mb_rec['album']
                    changed = True
                if not result.get('year') and self._validate_year(mb_rec.get('year')):
                    result['year'] = mb_rec['year']
                    changed = True
                # 修正标题
                if mb_rec.get('title') and mb_rec.get('title') != result['title']:
                    pass  # 不覆盖用户已有的标题

        # 策略2：如果只有文件名，尝试用文件名查询
        elif result.get('title') and not result.get('artist'):
            mb_rec = self.search_recording(result['title'])
            if mb_rec:
                if mb_rec.get('artist'):
                    result['artist'] = mb_rec['artist']
                    changed = True
                if not result.get('album') and mb_rec.get('album'):
                    result['album'] = mb_rec['album']
                    changed = True
                if not result.get('year') and self._validate_year(mb_rec.get('year')):
                    result['year'] = mb_rec['year']
                    changed = True

        # 策略3：如果专辑有但年份没有，查专辑
        if result.get('album') and not result.get('year') and result.get('artist'):
            mb_rel = self.search_release(result['album'], result['artist'])
            if mb_rel and self._validate_year(mb_rel.get('year')):
                result['year'] = mb_rel['year']
                changed = True

        # 策略4：所有信息都不全时，用音频指纹
        if use_fingerprint and not changed:
            if (not result.get('artist') or result['artist'] == '未知歌手') and \
               not result.get('album'):
                fp_result = use_fingerprint(result.get('source_path', ''))
                if fp_result:
                    if fp_result.get('title'):
                        result['title'] = fp_result['title']
                    if fp_result.get('artist'):
                        result['artist'] = fp_result['artist']
                    changed = True

        return result, changed