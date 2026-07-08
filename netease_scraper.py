#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
网易云音乐刮削器
=============================================
功能：
  1. 搜索歌曲，补全歌手/专辑信息
  2. 搜索歌手，获取别名（中英文名）
  3. 搜索专辑，补全发行年份

API来源: https://music.163.com/api (公开搜索接口)
参考: https://github.com/Binaryify/NeteaseCloudMusicApi

注意: 网易云API有频率限制，建议每秒不超过1次请求
"""

import re
import json
import time
import urllib.request
import urllib.parse

from version import MB_USER_AGENT


class NetEaseScraper:
    """网易云音乐元数据刮削器"""

    def __init__(self, cache_file=None):
        self.cache_file = cache_file
        self.cache = {}  # {cache_key: result}
        self.last_request_time = 0
        if cache_file:
            self._load_cache()

    def _load_cache(self):
        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                self.cache = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def _save_cache(self):
        if not self.cache_file:
            return
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _rate_limit(self):
        """频率限制：每秒最多1次请求"""
        elapsed = time.time() - self.last_request_time
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)
        self.last_request_time = time.time()

    def _request(self, url, data=None, timeout=10):
        """发送HTTP请求"""
        req = urllib.request.Request(url)
        req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        req.add_header('Referer', 'https://music.163.com')
        if data:
            req.add_header('Content-Type', 'application/x-www-form-urlencoded')
        try:
            if data:
                req.data = data.encode('utf-8')
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except Exception:
            return None

    def search_song(self, keyword, limit=5):
        """
        搜索歌曲
        返回: [{name, artist, album, album_id, artist_id, duration}, ...]
        """
        self._rate_limit()
        url = 'https://music.163.com/api/search/get/web'
        params = urllib.parse.urlencode({
            's': keyword, 'type': 1, 'limit': limit, 'offset': 0
        })
        result = self._request(url, data=params)
        if not result or 'result' not in result:
            return []

        songs = result['result'].get('songs', [])
        results = []
        for s in songs:
            album = s.get('album') or {}
            # publishTime 是毫秒时间戳，转换为年份
            year = ''
            pt = album.get('publishTime', 0)
            if pt:
                try:
                    year = str(time.localtime(pt / 1000).tm_year)
                except Exception:
                    pass
            results.append({
                'name': s.get('name', ''),
                'artist': s['artists'][0]['name'] if s.get('artists') else '',
                'artist_id': s['artists'][0]['id'] if s.get('artists') else 0,
                'album': album.get('name', ''),
                'album_id': album.get('id', 0),
                'year': year,
                'duration': s.get('dt', 0) // 1000,  # 转为秒
            })
        return results

    def search_artist(self, keyword, limit=5):
        """
        搜索歌手
        返回: [{name, artist_id, alias, album_size, music_size}, ...]
        """
        self._rate_limit()
        url = 'https://music.163.com/api/search/get/web'
        params = urllib.parse.urlencode({
            's': keyword, 'type': 100, 'limit': limit, 'offset': 0
        })
        result = self._request(url, data=params)
        if not result or 'result' not in result:
            return []

        artists = result['result'].get('artists', [])
        return [{
            'name': a.get('name', ''),
            'artist_id': a.get('id', 0),
            'alias': a.get('alias', []),
            'album_size': a.get('albumSize', 0),
            'music_size': a.get('musicSize', 0),
        } for a in artists]

    def get_artist_detail(self, artist_id):
        """
        获取歌手详情（含别名和热门专辑）
        返回: {name, alias, album_size, hot_albums: [{name, publish_time}]}
        """
        cache_key = f'artist_{artist_id}'
        if cache_key in self.cache:
            return self.cache[cache_key]

        self._rate_limit()
        url = f'https://music.163.com/api/artist/{artist_id}'
        result = self._request(url)
        if not result or 'artist' not in result:
            return None

        artist = result['artist']
        hot_albums = []
        for a in result.get('hotAlbums', []):
            # publishTime 是毫秒时间戳
            pt = a.get('publishTime', 0)
            year = ''
            if pt:
                try:
                    year = str(time.localtime(pt / 1000).tm_year)
                except Exception:
                    pass
            hot_albums.append({
                'name': a.get('name', ''),
                'year': year,
                'album_id': a.get('id', 0),
            })

        detail = {
            'name': artist.get('name', ''),
            'alias': artist.get('alias', []),
            'album_size': artist.get('albumSize', 0),
            'music_size': artist.get('musicSize', 0),
            'hot_albums': hot_albums,
        }

        self.cache[cache_key] = detail
        self._save_cache()
        return detail

    def search_album(self, keyword, limit=5):
        """
        搜索专辑
        返回: [{name, artist, album_id, artist_id}, ...]
        """
        self._rate_limit()
        url = 'https://music.163.com/api/search/get/web'
        params = urllib.parse.urlencode({
            's': keyword, 'type': 10, 'limit': limit, 'offset': 0
        })
        result = self._request(url, data=params)
        if not result or 'result' not in result:
            return []

        albums = result['result'].get('albums', [])
        return [{
            'name': a.get('name', ''),
            'artist': a.get('artist', {}).get('name', ''),
            'album_id': a.get('id', 0),
            'artist_id': a.get('artist', {}).get('id', 0),
        } for a in albums]

    def enrich_metadata(self, meta):
        """
        补全歌曲元数据。
        策略：用歌手名+歌曲名搜索，匹配最相似的结果。
        返回: (enriched_meta, changed: bool)
        """
        if not meta.get('title') or meta.get('title') == '未知歌曲':
            return meta, False

        artist = meta.get('artist', '')
        is_unknown_artist = (not artist or artist == '未知歌手')

        cache_key = f'song_{artist}_{meta["title"]}'
        if cache_key in self.cache:
            cached = self.cache[cache_key]
            if cached:
                result = dict(meta)
                for k, v in cached.items():
                    if v and not result.get(k):
                        result[k] = v
                return result, bool(cached)
            return meta, False

        # 搜索歌曲：未知歌手时仅用歌名搜索
        if is_unknown_artist:
            keyword = meta['title']
        else:
            keyword = f"{artist} {meta['title']}"
        songs = self.search_song(keyword, limit=5)
        if not songs:
            self.cache[cache_key] = {}
            self._save_cache()
            return meta, False

        # 匹配最相似的结果
        best_match = None
        best_score = 0
        for song in songs:
            score = 0
            # 歌手匹配（未知歌手时不加分也不减分）
            if not is_unknown_artist and artist:
                from artist_normalizer import similarity
                score += similarity(artist.lower(), song['artist'].lower()) * 0.4
            # 歌曲名匹配
            if meta.get('title'):
                from artist_normalizer import similarity
                title_sim = similarity(meta['title'].lower(), song['name'].lower())
                score += title_sim * 0.4
            # 专辑匹配（加分项）
            if meta.get('album') and song.get('album'):
                from artist_normalizer import similarity
                score += similarity(meta['album'].lower(), song['album'].lower()) * 0.2

            if score > best_score:
                best_score = score
                best_match = song

        # 未知歌手时：要求歌名完全匹配（短歌名≤2字更严格）
        # 有歌手时保持原阈值 0.5
        if is_unknown_artist:
            title = meta.get('title', '')
            # 歌名长度≤2时，要求完全匹配（similarity >= 0.95）
            # 歌名长度>2时，要求高度相似（similarity >= 0.85），对应总分 >= 0.34
            from artist_normalizer import similarity
            title_sim = similarity(title.lower(), best_match['name'].lower()) if best_match else 0
            if len(title) <= 2:
                score_threshold = 0.38  # 需要歌名几乎完全匹配
            else:
                score_threshold = 0.34  # 需要歌名高度相似
        else:
            score_threshold = 0.5
        if not best_match or best_score < score_threshold:
            self.cache[cache_key] = {}
            self._save_cache()
            return meta, False

        # 补全信息
        enrichment = {}
        if best_match.get('album') and not meta.get('album'):
            enrichment['album'] = best_match['album']
        # 未知歌手时也补全歌手名（带时长校验防误匹配）
        if is_unknown_artist and best_match.get('artist'):
            # 时长校验：如果本地有时长且与搜索结果差异>20%，不补全歌手名
            local_dur = meta.get('duration')
            remote_dur = best_match.get('duration')
            if local_dur and remote_dur and remote_dur > 0:
                ratio = local_dur / remote_dur
                if ratio < 0.8 or ratio > 1.25:
                    # 时长差异过大，不信任歌手匹配，只补专辑/年份
                    pass
                else:
                    enrichment['artist'] = best_match['artist']
            else:
                # 无时长信息可校验，仍然补全（用户可通过 --dry-run 审核）
                enrichment['artist'] = best_match['artist']
        elif best_match.get('artist') and (not meta.get('artist') or meta['artist'] == '未知歌手'):
            enrichment['artist'] = best_match['artist']
        if best_match.get('duration') and not meta.get('duration'):
            enrichment['duration'] = best_match['duration']
        # 从搜索结果中直接提取年份（publishTime 毫秒时间戳）
        if best_match.get('year') and not meta.get('year'):
            enrichment['year'] = best_match['year']

        if enrichment:
            self.cache[cache_key] = enrichment
            self._save_cache()
            result = dict(meta)
            result.update(enrichment)
            return result, True

        self.cache[cache_key] = {}
        self._save_cache()
        return meta, False

    def _get_album_year(self, album_id):
        """从专辑搜索结果推断年份（专辑详情API需要登录）"""
        cache_key = f'album_year_{album_id}'
        if cache_key in self.cache:
            return self.cache[cache_key]

        # 网易云专辑详情API需要登录，这里用歌手热门专辑反查
        # 或者跳过年份补全
        self.cache[cache_key] = ''
        return ''

    def get_artist_aliases(self, artist_name):
        """
        获取歌手别名（中英文名等）
        返回: [alias1, alias2, ...] 或 []
        """
        cache_key = f'aliases_{artist_name}'
        if cache_key in self.cache:
            return self.cache[cache_key]

        artists = self.search_artist(artist_name, limit=3)
        if not artists:
            self.cache[cache_key] = []
            return []

        # 取最匹配的歌手
        from artist_normalizer import similarity
        best = None
        best_score = 0
        for a in artists:
            score = similarity(artist_name.lower(), a['name'].lower())
            if score > best_score:
                best_score = score
                best = a

        if not best or best_score < 0.7:
            self.cache[cache_key] = []
            return []

        aliases = best.get('alias', [])
        # 如果有artist_id，获取更详细的别名
        if best.get('artist_id'):
            detail = self.get_artist_detail(best['artist_id'])
            if detail and detail.get('alias'):
                for alias in detail['alias']:
                    if alias not in aliases:
                        aliases.append(alias)

        self.cache[cache_key] = aliases
        self._save_cache()
        return aliases
