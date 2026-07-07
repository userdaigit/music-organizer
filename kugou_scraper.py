# -*- coding: utf-8 -*-
"""
酷狗音乐刮削模块
=============================================
通过酷狗音乐移动端搜索接口补全华语歌曲元数据。

接口: http://mobilecdn.kugou.com/api/v3/search/song
无需认证，直接 HTTP GET。

注意:
  - 此接口为非官方接口，可能随时失效或变更。
  - 仅获取元数据（歌手、专辑、年份），不下载音乐文件。
  - 对华语音乐覆盖较好，弥补 MusicBrainz 的不足。

参考:
  - 酷狗音乐移动端 API（公开可访问）
"""

import time
import json
import urllib.request
import urllib.parse
from version import MB_USER_AGENT


class KugouScraper:
    """酷狗音乐搜索刮削器"""

    SEARCH_URL = "http://mobilecdn.kugou.com/api/v3/search/song"

    def __init__(self, cache=None):
        """
        初始化酷狗刮削器。

        Args:
            cache: 可选的缓存字典，避免重复搜索
        """
        self.cache = cache or {}
        self.last_request_time = 0
        self._available = None  # None=未检查, True=可用, False=不可用

    def search(self, keyword, timeout=5):
        """
        搜索歌曲，返回结果列表。

        Args:
            keyword: 搜索关键词（歌曲名 或 "歌曲名 歌手"）
            timeout: 请求超时秒数

        Returns:
            结果列表，每项为 dict:
            {
                'title': 歌曲名,
                'artist': 歌手名,
                'album': 专辑名,
                'duration': 时长(秒),
                'release_date': 发行日期 (YYYY-MM-DD 或空),
            }
            搜索失败返回空列表。
        """
        # 检查缓存
        cache_key = keyword.strip().lower()
        if cache_key in self.cache:
            return self.cache[cache_key]

        # 速率限制: 最多 2 次/秒（0.5 秒间隔）
        elapsed = time.time() - self.last_request_time
        if elapsed < 0.5:
            time.sleep(0.5 - elapsed)

        try:
            params = urllib.parse.urlencode({
                'format': 'json',
                'keyword': keyword,
                'page': 1,
                'pagesize': 5,  # 取前 5 条结果
            })
            url = f"{self.SEARCH_URL}?{params}"
            req = urllib.request.Request(url, headers={
                'User-Agent': MB_USER_AGENT,
            })

            self.last_request_time = time.time()
            resp = urllib.request.urlopen(req, timeout=timeout)
            data = json.loads(resp.read().decode('utf-8'))

            results = []
            if data.get('status') == 1 and data.get('data', {}).get('info'):
                for item in data['data']['info']:
                    # 注意：酷狗API字段名是 album_name（有下划线），不是 albumname
                    album = item.get('album_name', '') or item.get('albumname', '') or ''
                    song = {
                        'title': item.get('songname', '').strip(),
                        'artist': item.get('singername', '').strip(),
                        'album': album.strip(),
                        'duration': int(item.get('duration', 0)),
                        'release_date': '',  # 酷狗搜索接口不直接返回发行日期
                    }
                    # 过滤空标题
                    if song['title']:
                        results.append(song)

            self.cache[cache_key] = results
            self._available = True
            return results

        except Exception:
            self._available = False
            self.cache[cache_key] = []
            return []

    def enrich_metadata(self, meta):
        """
        根据现有 meta 中的 title/artist 搜索酷狗，补全缺失字段。

        Args:
            meta: 元数据字典，需包含 title 和可选的 artist

        Returns:
            (enriched_meta, changed) 元组
            - enriched_meta: 补全后的元数据
            - changed: bool，是否有字段被补全
        """
        title = meta.get('title', '').strip()
        artist = meta.get('artist', '').strip()

        if not title or title == '未知歌曲':
            return meta, False

        # 构建搜索关键词
        if artist and artist != '未知歌手':
            keyword = f"{title} {artist}"
        else:
            keyword = title

        results = self.search(keyword)
        if not results:
            # 如果带歌手搜索无结果，尝试只搜歌名
            if artist and artist != '未知歌手':
                results = self.search(title)
            if not results:
                return meta, False

        # 取最佳匹配（第一条结果）
        best = results[0]
        enriched = dict(meta)
        changed = False

        # 补全歌手
        if (not enriched.get('artist') or enriched['artist'] == '未知歌手') and best.get('artist'):
            enriched['artist'] = best['artist']
            changed = True

        # 补全专辑
        if not enriched.get('album') and best.get('album'):
            enriched['album'] = best['album']
            changed = True

        # 补全标题（如果原标题是从文件名解析的不完整名称）
        if (not enriched.get('title') or enriched['title'] == '未知歌曲') and best.get('title'):
            enriched['title'] = best['title']
            enriched['title_display'] = best['title']
            changed = True

        return enriched, changed

    def is_available(self):
        """检查酷狗接口是否可用"""
        if self._available is None:
            # 发送一个测试请求
            self.search("test", timeout=3)
        return self._available if self._available is not None else False
