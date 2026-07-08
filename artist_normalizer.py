#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
歌手名规范化模块
=============================================
功能：
  1. 语言检测：判断歌手名是中文/英文/日文/韩文等
  2. 模糊匹配去重：合并同一歌手的不同写法（如"周杰伦"和"Jay Chou"）
  3. MusicBrainz 别名查询：联网获取歌手的别名列表，自动建立映射
  4. 规范化策略：
     - 中国歌手只有中文名的，只用中文名
     - 外国歌手只用其原名（英文名）
     - 其他语言歌手用原语言名
     - 同时有中英文名的，用"中文名-英文名"格式

参考:
  - MusicBrainz API artist 查询（含 aliases）:
    https://musicbrainz.org/doc/MusicBrainz_API
  - rate limiting: 每秒不超过1次请求
"""

import re
import json
import time
import urllib.request
import urllib.parse
from difflib import SequenceMatcher
from version import MB_USER_AGENT

# ============================================================
# 语言检测
# ============================================================
def detect_language(text):
    """
    检测文本的主要语言。
    返回: 'zh'(中文), 'en'(英文), 'ja'(日文), 'ko'(韩文), 'other'(其他)
    """
    if not text:
        return 'other'

    # 统计各语言字符数
    cjk_count = 0      # CJK 统一汉字
    hiragana_count = 0  # 平假名
    katakana_count = 0  # 片假名
    hangul_count = 0    # 韩文音节
    latin_count = 0     # 拉丁字母

    for ch in text:
        cp = ord(ch)
        if 0x4e00 <= cp <= 0x9fff or 0x3400 <= cp <= 0x4dbf:
            cjk_count += 1
        elif 0x3040 <= cp <= 0x309f:
            hiragana_count += 1
        elif 0x30a0 <= cp <= 0x30ff:
            katakana_count += 1
        elif 0xac00 <= cp <= 0xd7af:
            hangul_count += 1
        elif (0x41 <= cp <= 0x5a) or (0x61 <= cp <= 0x7a):
            latin_count += 1

    # 判断逻辑
    if hiragana_count > 0 or katakana_count > 0:
        return 'ja'
    if hangul_count > 0 and cjk_count == 0:
        return 'ko'
    if cjk_count > 0:
        return 'zh'
    if latin_count > 0 and cjk_count == 0 and hangul_count == 0:
        return 'en'
    return 'other'


def is_chinese_name(name):
    """判断是否为纯中文名"""
    return detect_language(name) == 'zh'


def is_english_name(name):
    """判断是否为纯英文名"""
    return detect_language(name) == 'en'


# ============================================================
# 模糊匹配去重
# ============================================================
def similarity(a, b):
    """计算两个字符串的相似度（0-1）"""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def normalize_for_compare(name):
    """规范化歌手名用于比较（去空格、统一大小写、去标点）"""
    if not name:
        return ''
    name = name.lower().strip()
    # 去除常见标点和空格
    name = re.sub(r'[\s\-_.,&\'`\'""()（）\[\]【】]', '', name)
    # 中文常见变体统一
    name = name.replace('ａ', 'a').replace('ｂ', 'b')
    return name


def find_similar_artists(artists, threshold=0.85):
    """
    在歌手列表中找出可能是同一人的歌手名对。
    返回: [(name_a, name_b, similarity_score), ...]
    """
    pairs = []
    normalized = {a: normalize_for_compare(a) for a in artists}

    for i, a in enumerate(artists):
        for b in artists[i+1:]:
            # 方法1：直接相似度比较
            sim = similarity(normalized[a], normalized[b])
            if sim >= threshold:
                pairs.append((a, b, sim))
                continue

            # 方法2：一个包含另一个（如 "Jay Chou" 和 "JayChou"）
            if normalized[a] and normalized[b]:
                if normalized[a] in normalized[b] or normalized[b] in normalized[a]:
                    # 但排除短名（如 "A" 和 "AB"）
                    if len(normalized[a]) > 3 and len(normalized[b]) > 3:
                        pairs.append((a, b, 0.9))
                        continue

            # 方法3：中英文名交叉验证（通过 name_map 或网络查询）
            # 这里只做本地判断，网络查询在 merge_artist_variants 中处理

    return pairs


# ============================================================
# 乱码检测
# ============================================================
def _contains_garbage_chars(text):
    """
    检测字符串是否包含乱码字符。
    乱码特征：
      - 包含控制字符 (\x00-\x1F，排除 \t\n\r)
      - 包含未分配的 Unicode 私用区字符 (U+E000-U+F8FF, U+F0000-U+FFFFD)
      - 中文场景：包含 Big5/Latin-1 误解码产生的常见乱码模式
        (如 ³¯¤p¬K, °Ê¤O¤õ¨® 等)
    """
    if not text:
        return False

    # 检查控制字符
    for ch in text:
        code = ord(ch)
        if code < 32 and code not in (9, 10, 13):
            return True
        # 私用区字符 (PUA) — 通常是乱码或字体私有编码
        if 0xE000 <= code <= 0xF8FF:
            return True

    # 检测 Big5 误解码模式：连续出现 0xA1-0xFE 范围内的字符
    # 这些字符在 UTF-8 中通常表示 Latin-1 扩展区的乱码
    big5_garbage_count = 0
    for ch in text:
        code = ord(ch)
        # 0x00A1-0x00BF, 0x00C0-0x00FF 是 Latin-1 补充区
        # Big5 误解码后常见这些字符
        if 0x00A1 <= code <= 0x00FF:
            big5_garbage_count += 1

    # 如果超过 30% 的字符是疑似乱码，判定为乱码
    if len(text) > 0 and big5_garbage_count / len(text) > 0.3:
        return True

    return False


# ============================================================
# MusicBrainz 歌手查询
# ============================================================
MB_API_BASE = "https://musicbrainz.org/ws/2/artist"
# User-Agent 从 version.py 统一管理（文件顶部已导入）


def query_musicbrainz_artist(artist_name, timeout=10):
    """
    查询 MusicBrainz 获取歌手信息（含别名）。
    返回: dict 或 None
    {
        'mbid': '...',
        'name': '规范名',
        'sort_name': '排序名',
        'aliases': ['别名1', '别名2', ...],
        'country': '国家代码',
    }
    """
    params = urllib.parse.urlencode({
        'query': artist_name,
        'limit': 5,
        'fmt': 'json',
    })
    url = f"{MB_API_BASE}?{params}"

    req = urllib.request.Request(url)
    req.add_header('User-Agent', MB_USER_AGENT)
    req.add_header('Accept', 'application/json')

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        return None

    if not data.get('artists'):
        return None

    # 取第一个匹配结果
    artist = data['artists'][0]

    result = {
        'mbid': artist.get('id', ''),
        'name': artist.get('name', ''),
        'sort_name': artist.get('sort-name', ''),
        'country': artist.get('country', ''),
        'aliases': [],
    }

    # 提取别名
    for alias in artist.get('aliases', []):
        alias_name = alias.get('name', '')
        if alias_name and alias_name not in result['aliases']:
            result['aliases'].append(alias_name)

    # sort_name 也加入别名
    if result['sort_name'] and result['sort_name'] not in result['aliases']:
        result['aliases'].append(result['sort_name'])

    return result


def build_artist_canonical_name(mb_result, original_name):
    """
    根据 MusicBrainz 查询结果构建规范歌手名。
    策略:
      - 用 MB country 判断国籍：JP/KR → foreign 格式，CN/TW/HK → cn 格式
      - 中国歌手: "中文名-英文名"
      - 外国歌手: "外文名-中文译名"
      - 无国籍信息: 按原语言推断
    """
    if not mb_result:
        return original_name

    name = mb_result.get('name', original_name)
    aliases = mb_result.get('aliases', [])
    country = mb_result.get('country', '').upper()

    # 修复(Bug Y)：MusicBrainz 经常返回 "姓, 名" 格式（如 "Li, Xuhao"），
    # 转换为 "名 姓" 格式（如 "Xuhao Li"）以保持一致性
    def _fix_comma_name(n):
        if not n or ',' not in n:
            return n
        parts = [p.strip() for p in n.split(',', 1)]
        if len(parts) == 2 and parts[0] and parts[1]:
            # 仅对英文名做转换（中文名带逗号通常是"姓,名"且不常见）
            from encoding_fix import normalize_text
            if detect_language(parts[0]) == 'en' and detect_language(parts[1]) == 'en':
                return f"{parts[1]} {parts[0]}"
        return n

    name = _fix_comma_name(name)
    aliases = [_fix_comma_name(a) for a in aliases]
    all_names = [name] + [a for a in aliases if a != name]

    # 分类收集各语言的名称
    zh_names = []
    en_names = []
    for n in all_names:
        lang = detect_language(n)
        if lang == 'zh' or lang == 'ja':
            if n not in zh_names and not any(0x3040 <= ord(c) <= 0x30ff for c in n):
                zh_names.append(n)
        elif lang == 'en':
            if n not in en_names:
                en_names.append(n)

    # 根据 MB country 决定格式
    is_foreign = country in ('JP', 'KR', 'US', 'GB', 'DE', 'FR', 'SE', 'NO', 'SG', 'CA', 'AU')

    if is_foreign:
        # 外国歌手: "外文名-中文译名"
        en = en_names[0] if en_names else name
        if zh_names:
            return f"{en}-{zh_names[0]}"
        return en
    elif country in ('CN', 'TW', 'HK'):
        # 中国歌手: "中文名-英文名"
        zh = zh_names[0] if zh_names else original_name
        if en_names:
            return f"{zh}-{en_names[0]}"
        return zh
    else:
        # 无国籍信息，按原始语言推断
        orig_lang = detect_language(original_name)
        if orig_lang == 'en':
            if zh_names:
                return f"{en_names[0] if en_names else original_name}-{zh_names[0]}"
            return en_names[0] if en_names else original_name
        else:
            if en_names:
                zh = zh_names[0] if zh_names else original_name
                return f"{zh}-{en_names[0]}"
            return zh_names[0] if zh_names else original_name


# ============================================================
# 合唱歌曲处理
# ============================================================
def _extract_primary_artist(artist_name):
    """
    从合唱歌手名中提取第一个歌手。
    "周杰伦.曾志伟.麦烝玮" -> "周杰伦"
    "张学友,黎明" -> "张学友"
    "陈奕迅&杨千嬅" -> "陈奕迅"
    "陈奕迅/张学友" -> "陈奕迅"
    "Linkin Park" -> "Linkin Park" (无分隔符，原样返回)
    """
    if not artist_name:
        return artist_name
    # 按各种分隔符分割，取第一段
    for sep in ['.', '、', ',', '&', '/', ' feat.', ' ft.', ' feat ', ' ft ']:
        if sep in artist_name:
            first = artist_name.split(sep)[0].strip()
            if first:
                return first
    return artist_name


# ============================================================
# 歌手名规范化器
# ============================================================
class ArtistNormalizer:
    """
    歌手名规范化器。
    缓存查询结果，避免重复网络请求。
    """

    def __init__(self, name_map=None, use_network=True, cache_file=None):
        """
        Args:
            name_map: 手动映射表 {原始名: 规范名}
            use_network: 是否联网查询 MusicBrainz
            cache_file: 缓存文件路径，用于持久化网络查询结果
        """
        self.name_map = name_map or {}
        self.use_network = use_network
        self.cache_file = cache_file
        self.cache = {}  # 查询缓存 {原始名: 规范名}
        self.mb_cache = {}  # MusicBrainz 查询缓存
        self.last_request_time = 0

        # 加载缓存
        if cache_file:
            self._load_cache()

    def _load_cache(self):
        """从文件加载缓存，自动清理错误映射"""
        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                raw_cache = data.get('cache', {})
                self.mb_cache = data.get('mb_cache', {})

                # 清理 cache 中的错误映射
                name_map_values = set(self.name_map.values())
                cleaned = 0
                for key, value in list(raw_cache.items()):
                    remove = False
                    # 规则1: value 包含乱码字符
                    if _contains_garbage_chars(value):
                        remove = True
                    # 规则2: key 是 name_map 的 value（被错误覆盖的映射）
                    if key in name_map_values:
                        remove = True
                    # 规则3: key 在 name_map 中，但 cache 值与 name_map 不一致
                    if key in self.name_map:
                        expected = self.name_map[key]
                        if isinstance(expected, dict):
                            expected = expected.get('display', key)
                        if value != expected:
                            remove = True
                    # 规则4: value 是明显错误的 MusicBrainz 结果
                    # （如 "华语群星" -> "華納羣星"，value 包含不常见繁体组合）
                    if not remove and value not in name_map_values:
                        # 检测 value 是否包含 MusicBrainz 常见的错误模式
                        # 如 "華納羣星"、"動力火車" 等（这些是繁体，但不是 name_map 的值）
                        has_rare_chars = any(0xE000 <= ord(ch) <= 0xF8FF for ch in value)
                        if has_rare_chars:
                            remove = True
                    if remove:
                        del raw_cache[key]
                        cleaned += 1

                self.cache = raw_cache
                if cleaned > 0:
                    print(f"  歌手缓存已清理 {cleaned} 条错误映射")
                    self._save_cache()
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def _save_cache(self):
        """保存缓存到文件"""
        if not self.cache_file:
            return
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'cache': self.cache,
                    'mb_cache': self.mb_cache,
                }, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _rate_limit(self):
        """MusicBrainz API 限流：每秒最多1次请求"""
        elapsed = time.time() - self.last_request_time
        if elapsed < 1.1:
            time.sleep(1.1 - elapsed)
        self.last_request_time = time.time()

    def normalize(self, artist_name):
        """
        规范化歌手名。
        优先级：
          1. 手动映射表（先尝试原始名，再尝试取第一个歌手）
          2. 查询缓存
          3. MusicBrainz 网络查询（结果需经过 name_map 二次校验）
          4. 模糊匹配已有名称
          5. 返回原始名
        """
        if not artist_name:
            return '未知歌手'

        # 1a. 手动映射表（原始名直接匹配）
        if artist_name in self.name_map:
            return self.name_map[artist_name]

        # 1b. 合唱歌曲：取第一个歌手再查 name_map
        # "周杰伦.曾志伟.麦烝玮" -> "周杰伦" -> name_map -> "周杰伦-Jay Chou"
        primary = _extract_primary_artist(artist_name)
        if primary != artist_name and primary in self.name_map:
            return self.name_map[primary]

        # 2. 查询缓存
        if artist_name in self.cache:
            return self.cache[artist_name]

        # 2b. 缓存中也尝试取第一个歌手
        if primary != artist_name and primary in self.cache:
            return self.cache[primary]

        # 3. MusicBrainz 网络查询
        if self.use_network and artist_name not in self.mb_cache:
            self._rate_limit()
            # 查询时用第一个歌手名（更准确）
            query_name = primary if primary != artist_name else artist_name
            mb_result = query_musicbrainz_artist(query_name)
            self.mb_cache[artist_name] = mb_result

            if mb_result:
                canonical = build_artist_canonical_name(mb_result, query_name)

                # 保护 name_map 的已有映射：如果 artist_name 已经是 name_map 的 value，
                # 说明它已经被手动配置过，MusicBrainz 结果不应覆盖
                name_map_values = set(self.name_map.values())
                if artist_name in name_map_values:
                    # 返回原始名（保持 name_map 的映射结果）
                    self.cache[artist_name] = artist_name
                    self._save_cache()
                    return artist_name

                # 检测乱码：如果 canonical 包含乱码字符，不使用 MusicBrainz 结果
                if _contains_garbage_chars(canonical):
                    self.cache[artist_name] = artist_name
                    self._save_cache()
                    return artist_name

                # 二次校验：如果 canonical 在 name_map 中有更好的映射，用 name_map
                if canonical in self.name_map:
                    canonical = self.name_map[canonical]
                # 繁简转换后再查一次 name_map
                try:
                    from encoding_fix import normalize_text
                    simplified = normalize_text(canonical)
                    if simplified != canonical and simplified in self.name_map:
                        canonical = self.name_map[simplified]
                except ImportError:
                    pass
                # 如果是合唱歌曲，用第一个歌手的 canonical
                if primary != artist_name:
                    primary_canonical = self.name_map.get(primary, canonical)
                    canonical = primary_canonical

                self.cache[artist_name] = canonical
                self._save_cache()
                return canonical

        # 如果网络查询过但没结果
        if artist_name in self.mb_cache and self.mb_cache[artist_name] is None:
            # 4. 模糊匹配已有名称
            for cached_name, canonical in self.cache.items():
                if similarity(artist_name, cached_name) > 0.9:
                    self.cache[artist_name] = canonical
                    self._save_cache()
                    return canonical

            # 5. 返回原始名
            self.cache[artist_name] = artist_name
            self._save_cache()
            return artist_name

        # 网络未启用或查询失败
        return artist_name

    def normalize_one(self, artist_name):
        """
        规范化单个歌手名（含本地模糊匹配优化）。
        适合需要逐个显示进度的场景。
        """
        if not artist_name:
            return '未知歌手'

        # 1. 手动映射表
        if artist_name in self.name_map:
            return self.name_map[artist_name]

        # 2. 查询缓存
        if artist_name in self.cache:
            return self.cache[artist_name]

        # 3. 本地模糊匹配（在已缓存的名称中找相似项）
        for cached_name, canonical in self.cache.items():
            if similarity(artist_name, cached_name) > 0.9:
                self.cache[artist_name] = canonical
                self._save_cache()
                return canonical

        # 4. MusicBrainz 网络查询 / 返回原始名
        result = self.normalize(artist_name)
        return result

    def normalize_batch(self, artist_names):
        """
        批量规范化歌手名。
        先做本地模糊去重，再对未匹配的联网查询。
        返回: {原始名: 规范名}
        """
        result = {}

        # 第一轮：手动映射 + 缓存
        unresolved = []
        for name in artist_names:
            if name in self.name_map:
                result[name] = self.name_map[name]
            elif name in self.cache:
                result[name] = self.cache[name]
            else:
                unresolved.append(name)

        # 第二轮：本地模糊匹配（在已解析的名称中找相似项）
        all_canonical = set(result.values()) | set(self.cache.values())
        still_unresolved = []
        for name in unresolved:
            matched = False
            for canonical in all_canonical:
                if similarity(name, canonical) > 0.9:
                    result[name] = canonical
                    self.cache[name] = canonical
                    matched = True
                    break
            if not matched:
                still_unresolved.append(name)

        # 第三轮：联网查询
        if self.use_network:
            for name in still_unresolved:
                canonical = self.normalize(name)
                result[name] = canonical

        # 未联网的，用原始名
        if not self.use_network:
            for name in still_unresolved:
                result[name] = name

        self._save_cache()
        return result

    def get_all_variants(self):
        """获取所有已知歌手名的变体映射"""
        all_variants = {}
        all_variants.update(self.name_map)
        all_variants.update(self.cache)
        return all_variants