#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞牛NAS 音乐库一键整理工具 v1.0
=============================================
功能：
  1. 递归扫描源目录所有音频文件（支持任意层级错乱）
  2. 修复乱码标签（GBK/GB18030/BIG5 -> UTF-8）
  3. 读取标签 + 文件名 + 目录结构，提取歌手/专辑/歌名/年份
  4. 识别 feat. 合作方，拆分到标题
  5. 歌手名规范化：语言检测、模糊去重、MusicBrainz别名查询
  6. 网络刮削：MusicBrainz API 补全缺失的专辑/年份信息
  7. 音频指纹识别：信息全缺时通过 AcoustID 查询
  8. 保留原专辑序号前缀（如 01-）
  9. 去重校验：歌手文件夹、同专辑内歌曲去重
 10. 按规则复制到新目录（原文件不动）
 11. 补充缺失标签到复制后的新文件
 12. 生成整理报告 + 歌手列表

目标结构:
  /music2/歌手/年份-专辑/序号-歌曲名-歌手-专辑.ext   (专辑歌曲)
  /music2/歌手/其他/序号-歌曲名-歌手.ext             (零散歌曲)

用法:
  python3 organize_music.py --source /music --output /music2
  python3 organize_music.py -s /music -o /music2 --dry-run
  python3 organize_music.py -s /music -o /music2 --write-tags --scrape
  python3 organize_music.py -s /music -o /music2 --fingerprint
"""

import os
import re
import json
import shutil
import argparse
import hashlib
import time
import threading
from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime

# 本地模块
from encoding_fix import fix_tags_encoding, normalize_text, is_garbled, try_fix_encoding
from artist_normalizer import ArtistNormalizer, detect_language, similarity
from scraper import MusicBrainzScraper
from kugou_scraper import KugouScraper
from fingerprint import FingerprintIdentifier, is_default_key, validate_api_key
from version import __version__
from progress import ProgressBar, progress_iter

# ============================================================
# 配置
# ============================================================
AUDIO_EXTENSIONS = {
    '.mp3', '.flac', '.m4a', '.aac', '.ogg', '.wma',
    '.wav', '.ape', '.alac', '.opus', '.aiff', '.wv',
    '.dsf', '.dff'  # DSD 音频格式
}

FEAT_PATTERN = re.compile(
    r'\s*[\(（\[]?\s*(?:featuring|feat\.|ft\.|with)\s*[:：]?\s*'
    r'(.+?)(?:[\)）\]]|$)',
    re.IGNORECASE
)

# 文件名中的轨道号前缀（如 "01 - " 或 "01. " 或 "01_"）
TRACK_PREFIX_PATTERN = re.compile(r'^(\d{1,3})\s*[-_.\s]+\s*')


# ============================================================
# 年份提取
# ============================================================
# 匹配目录名/文件名中的年份模式
YEAR_PATTERN = re.compile(
    r'(?:^|\D)('  # 年份前不能是数字（避免匹配到更大的数字）
    r'(?:19|20)\d{2}'  # 1900-2099 年份
    r')(?:\D|$)'  # 年份后不能是数字
)
# 匹配方括号/圆括号中的年份: [1999], (1999), 【1999】
YEAR_BRACKET_PATTERN = re.compile(r'[\[【\(（]\s*((?:19|20)\d{2})\s*[\]】\)）]')
# 匹配开头的年份前缀: "1999 - ", "2010.", "1999_"
YEAR_PREFIX_PATTERN = re.compile(r'^((?:19|20)\d{2})\s*[-.\s_]+\s*')


def _extract_year_from_string(text):
    """
    从字符串中提取年份。
    优先匹配方括号/圆括号中的年份，其次是开头年份前缀，最后是任意位置。
    返回年份字符串或空字符串。
    """
    if not isinstance(text, str) or not text:
        return ''
    # 优先：方括号/圆括号中的年份
    m = YEAR_BRACKET_PATTERN.search(text)
    if m:
        return m.group(1)
    # 次优先：开头年份前缀
    m = YEAR_PREFIX_PATTERN.match(text)
    if m:
        return m.group(1)
    # 兜底：字符串中任意位置
    m = YEAR_PATTERN.search(text)
    if m:
        return m.group(1)
    return ''


# ============================================================
# 演唱会/Live 检测（修复 Bug Q/W）
# ============================================================
# 匹配路径中包含"演唱会"/"Live"/"Concert"的目录或文件名
# project_memory 硬约束：Must skip directory names containing '演唱会', 'Live', or 'Concert'
# 用户决策：演唱会作为类似专辑复制，文件夹名前加"演唱会-"标识，不混入录音室专辑
CONCERT_PATTERN = re.compile(r'演唱会|Live|Concert', re.IGNORECASE)

# 合辑类歌手名（修复 Bug AA）：当提取到这些名字时，检查更上层目录是否有明确歌手
COMPILATION_ARTIST_PATTERN = re.compile(
    r'^(群星|华语群星|華語群星|華納羣星|天乐群星|天樂群星|'
    r'Various\s*Artists?|VA|Various|Unknown\s*Artist|未知歌手|未知)$',
    re.IGNORECASE
)


def _is_compilation_artist(name):
    """判断名字是否是合辑类歌手名（群星、Various Artists 等）"""
    if not name:
        return False
    return bool(COMPILATION_ARTIST_PATTERN.match(name.strip()))


def detect_concert(filepath):
    """
    检测文件路径是否属于演唱会/Live/Concert 资源。
    只扫描目录名（不含文件名），因为演唱会是专辑级概念，由目录名决定。
    修复(Bug CC)：原代码扫描文件名，导致文件名含"Live"的非演唱会歌曲被误判，
    同一专辑被拆散到录音室和演唱会两个目录。
    返回: True/False
    """
    try:
        parts = list(filepath.parts)
    except Exception:
        parts = str(filepath).replace('\\', '/').split('/')
    # 只扫描目录名（排除最后一个部分=文件名）
    for p in parts[:-1]:
        if CONCERT_PATTERN.search(p):
            return True
    return False


# ============================================================
# feat. 识别
# ============================================================
def parse_feat(text):
    """识别并拆分 feat. 合作方"""
    if not text:
        return text, []
    match = FEAT_PATTERN.search(text)
    if not match:
        return text.strip(), []
    feat_raw = match.group(1).strip()
    feat_raw = re.sub(r'[\)）\]]+$', '', feat_raw).strip()
    feat_artists = [a.strip() for a in re.split(r'[,，&、]', feat_raw) if a.strip()]
    main_text = FEAT_PATTERN.sub('', text).strip()
    main_text = main_text.strip(' ()（）[]【】').strip()
    return main_text, feat_artists


# ============================================================
# 标签读取（带编码修复）
# ============================================================
def read_tags(filepath):
    """读取音频标签，自动修复乱码"""
    try:
        from mutagen import File as MutagenFile
    except ImportError:
        print("错误: 需要安装 mutagen 库 (pip install mutagen)")
        raise

    try:
        audio = MutagenFile(str(filepath), easy=True)
        if audio is None:
            return {}, False
    except Exception:
        return {}, False

    tags = {}
    field_map = {
        'title': ['title'],
        'artist': ['artist'],
        'album': ['album'],
        'albumartist': ['albumartist', 'album artist'],
        'date': ['date', 'year'],
        'tracknumber': ['tracknumber', 'track'],
    }

    for canonical, keys in field_map.items():
        for k in keys:
            if k in audio:
                val = audio[k]
                if isinstance(val, list):
                    val = val[0] if val else ''
                tags[canonical] = str(val).strip()
                break

    # 修复编码
    fixed_tags, was_fixed = fix_tags_encoding(tags)

    # 统一规范化文本
    for k, v in fixed_tags.items():
        if isinstance(v, str):
            fixed_tags[k] = normalize_text(v)

    return fixed_tags, was_fixed


# ============================================================
# 文件名解析（支持错乱层级）
# ============================================================
def parse_filename(filepath):
    """从文件名解析元数据"""
    stem = filepath.stem
    # 提取轨道号
    track_match = TRACK_PREFIX_PATTERN.match(stem)
    track_num = ''
    if track_match:
        track_num = track_match.group(1)
        stem = TRACK_PREFIX_PATTERN.sub('', stem)

    # 按连字符分割（主要分隔符）
    parts = [p.strip() for p in stem.split('-') if p.strip()]
    result = {'track': track_num}

    if len(parts) >= 3:
        result['artist'] = parts[0]
        result['album'] = parts[1]
        result['title'] = parts[-1]
    elif len(parts) == 2:
        result['artist'] = parts[0]
        result['title'] = parts[1]
    elif len(parts) == 1:
        # 没有连字符，尝试按点号分割（如 "31.张学友.佛诞吉祥"）
        dot_parts = [p.strip() for p in stem.split('.') if p.strip()]
        if len(dot_parts) >= 3:
            # 格式: track.artist.title 或 artist.album.title
            # 如果第一段是纯数字且长度<=3（合理曲目号范围），认为是 track number
            if dot_parts[0].isdigit() and len(dot_parts[0]) <= 3:
                result['track'] = dot_parts[0]
                result['artist'] = dot_parts[1]
                # 剩余所有段合并为 title，避免截断
                result['title'] = '.'.join(dot_parts[2:])
            else:
                result['artist'] = dot_parts[0]
                result['album'] = dot_parts[1]
                # 剩余所有段合并为 title，避免截断
                result['title'] = '.'.join(dot_parts[2:])
        elif len(dot_parts) == 2:
            # 修复(Bug X)：整轨文件（如 "张学友.饿狼传说 LPCD1630.flac"）无单曲 title，
            # 第二段实际是专辑名。启发式：含音质标识或长度>15时识别为整轨。
            second = dot_parts[1]
            is_whole_album = (
                re.search(r'\b(LPCD|SACD|DSD|K2HD|HQCD|HDCD|CD|APE|FLAC|WAV)\b',
                          second, re.IGNORECASE)
                or len(second) > 15
            )
            if is_whole_album:
                result['artist'] = dot_parts[0]
                result['album'] = second
                result['title'] = '未知'
            else:
                result['artist'] = dot_parts[0]
                result['title'] = second
        else:
            # 尝试按下划线分割（如 "简单爱_周杰伦"）
            us_parts = [p.strip() for p in stem.split('_') if p.strip()]
            if len(us_parts) >= 3:
                if us_parts[0].isdigit() and len(us_parts[0]) <= 3:
                    result['track'] = us_parts[0]
                    result['artist'] = us_parts[1]
                    result['title'] = '_'.join(us_parts[2:])
                else:
                    result['artist'] = us_parts[0]
                    result['album'] = us_parts[1]
                    result['title'] = '_'.join(us_parts[2:])
            elif len(us_parts) == 2:
                result['artist'] = us_parts[0]
                result['title'] = us_parts[1]
            else:
                result['title'] = parts[0]

    # 处理文件名本身的乱码
    for key in ['artist', 'album', 'title']:
        if key in result:
            result[key] = normalize_text(result[key])

    # 从文件名中提取年份
    year = _extract_year_from_string(stem)
    if year:
        result['year'] = year

    return result


def infer_from_directory(filepath):
    """
    从目录结构推断歌手和专辑。
    支持任意层级，智能识别 歌手/专辑 结构。
    跳过非歌手/非专辑的中间目录（Single/EP/Albums/CD1 等）。
    当所有中间目录都被跳过时，从更远的祖先中提取歌手名。
    """
    parents = list(filepath.parents)
    # 需要跳过的目录名（不是歌手名也不是专辑名）
    skip_patterns = re.compile(
        r'^(\d+$|CD\d?$|Disc\s?\d+$|music$|music2$|.*\.trae$|tmp$'
        r'|Single$|Singles?$|EP$|Albums?$|专辑$|合集$|无损合集$'
        r'|演唱会$|演唱会专辑$|Live$|Concert$'
        r'|vol\.?\d*$|volume\s*\d*$'
        r'| FLAC$|MP3$|WAV$|APE$'
        r'| BONUS$|Bonus$|EXTRA$|Extra$'
        r'|未知歌手$|未知$|Unknown Artist$'
        r'|无损音乐专辑$|无损专辑$)',
        re.IGNORECASE
    )

    # 模式1: 跳过只包含skip目录的中间层，识别 歌手/专辑 结构
    valid_parents = []
    for p in parents:
        name = p.name
        if not name or skip_patterns.match(name):
            continue
        valid_parents.append(name)
        if len(valid_parents) >= 3:
            break

    result = {}
    if len(valid_parents) >= 2:
        # 歌手/专辑/歌曲 结构
        artist_dir = valid_parents[1]  # 祖父目录
        album_dir = valid_parents[0]   # 父目录
        result['artist'] = _extract_chinese_artist(artist_dir)
        # 修复(Bug AA)：合辑名（群星等）在歌手目录下时，用更上层目录的歌手名
        # 如 "周杰伦/2007.群星.我们都爱这个伦 2CD/歌曲" 应归到周杰伦而非群星
        if _is_compilation_artist(result.get('artist', '')) and len(valid_parents) >= 3:
            upper_artist = _extract_chinese_artist(valid_parents[2])
            if upper_artist and not _is_compilation_artist(upper_artist):
                result['artist'] = upper_artist
        result['album'] = clean_album_dir_name(album_dir)
        year = _extract_year_from_string(album_dir)
        if year:
            result['year'] = year
        if not result.get('year'):
            year = _extract_year_from_string(artist_dir)
            if year:
                result['year'] = year
    elif len(valid_parents) == 1:
        # 只有一个有效父目录，需要仔细判断它是歌手名还是专辑名/排序编号
        maybe_artist = valid_parents[0]

        # 区分三种情况：
        # 1. 纯数字（01/02/03）：只是排序编号，不推断任何信息
        # 2. 数字前缀+内容（17 - New Divide）：可能是专辑名
        # 3. 非数字开头：可能是歌手名
        is_pure_number = re.match(r'^\d+$', maybe_artist)
        is_number_prefix = re.match(r'^\d{1,3}\s*[-._]\s*', maybe_artist)

        # 无论哪种情况，都尝试从更远的祖先中找歌手名
        fallback_artist = _find_artist_from_ancestors(parents, skip_patterns)
        if fallback_artist:
            result['artist'] = fallback_artist

        if is_pure_number:
            # 纯数字目录只是排序编号，不推断 album
            pass
        elif is_number_prefix:
            # 数字前缀+内容，提取内容部分判断是否有意义
            content_part = re.sub(r'^\d{1,3}\s*[-._]\s*', '', maybe_artist).strip()
            if content_part and len(content_part) >= 3 and not content_part.isdigit():
                # 内容部分有实际意义（如 "New Divide"），可能是专辑名
                result['album'] = clean_album_dir_name(maybe_artist)
            # 否则不推断 album（如 "01-" 后面内容太短或纯数字）
        else:
            # 非数字开头，尝试作为歌手名（但只在没找到祖先歌手时）
            if not result.get('artist'):
                result['artist'] = _extract_chinese_artist(maybe_artist)
            year = _extract_year_from_string(maybe_artist)
            if year:
                result['year'] = year

    return result


def _find_artist_from_ancestors(all_parents, skip_patterns):
    """
    在所有祖先目录中查找歌手名。
    策略：从近到远扫描，跳过skip目录和数字开头目录，
    找到第一个看起来像歌手名的目录，并从中提取歌手名。
    """
    for p in all_parents:
        name = p.name
        if not name or skip_patterns.match(name):
            continue
        # 跳过数字开头的目录（通常是专辑排序号）
        if re.match(r'^\d{1,3}\s*[-._]\s*', name):
            continue
        # 跳过纯数字
        if name.isdigit():
            continue
        # 检查是否包含 CJK 字符或合理的英文名（至少2个字母）
        has_cjk = any(0x4e00 <= ord(ch) <= 0x9fff for ch in name)
        has_letters = any(ch.isalpha() for ch in name)
        if (has_cjk or has_letters) and len(name) >= 2:
            # 从目录名中提取歌手名（处理 "Linkin Park Discography" -> "Linkin Park"）
            candidate = _extract_chinese_artist(name)
            # 修复(Bug AA)：合辑名（群星等）不是真实歌手，继续往上找
            if _is_compilation_artist(candidate):
                continue
            return candidate
    return None


def _extract_chinese_artist(dirname):
    """
    从目录名中提取歌手名。
    处理各种目录命名格式：
    - "中文名-英文名" -> "中文名"
    - "中文名[1999-专辑]" -> "中文名"
    - "中文名(1999)" -> "中文名"
    - "2010.中文名.专辑" -> "中文名"
    - "中文名" -> "中文名"
    """
    if not dirname:
        return dirname
    name = dirname.strip()

    # 去除"专辑无损合集""无损合集""精选集"等后缀
    name = re.sub(r'(专辑)?(无损)?合集.*$', '', name)
    name = re.sub(r'(精选集|精选|作品集|全集|大碟).*$', '', name)

    # 按 "+" 分割取第一段（如 "张学友.未收录单曲+合唱歌曲" -> "张学友.未收录单曲"）
    if '+' in name:
        name = name.split('+')[0].strip()

    # 按 "未收录" 等关键词截断（如 "张学友.未收录单曲" -> "张学友"）
    name = re.sub(r'[.\-_\s](未收录|合集|精选|杂锦|混音|Demo|Remix).*$', '', name)

    # 去除开头的年份前缀: "2010.张学友.xxx" -> "张学友.xxx"
    name = re.sub(r'^\d{4}[.\-_]\s*', '', name)

    # 去除方括号/圆括号中的年份: "五月天[1999]" / "五月天(1999)" -> "五月天"
    name = re.sub(r'[\[【\(（]\s*\d{4}\s*[\]】\)）]?', '', name)

    # 按 dash 分割（中英文之间常见分隔符）
    parts = name.split('-', 1)
    if len(parts) == 2:
        left = parts[0].strip()
        # 如果左半部分包含 CJK 字符，认为是中文名
        if any(0x4e00 <= ord(ch) <= 0x9fff for ch in left):
            # 去除左半部分末尾的年份残留: "五月天[1999" -> "五月天"
            left = re.sub(r'[\[【\(（].*$', '', left)
            return left.strip()
    # 没有 dash，检查是否有 CJK 或日文假名
    has_cjk = any(0x4e00 <= ord(ch) <= 0x9fff for ch in name)
    has_kana = any(0x3040 <= ord(ch) <= 0x30ff for ch in name)
    if has_cjk or has_kana:
        # 去除可能的年份残留
        name = re.sub(r'[\[【\(（].*$', '', name)
        # 处理 "歌手.专辑名" 格式：只取第一段（歌手名）
        if '.' in name:
            parts = name.split('.', 1)
            candidate = parts[0].strip()
            # 如果是合理的歌手名（2-10个字符），取第一段
            if 2 <= len(candidate) <= 10:
                if all(0x4e00 <= ord(ch) <= 0x9fff or 0x3040 <= ord(ch) <= 0x30ff or
                       0x61 <= ord(ch) <= 0x7a or 0x41 <= ord(ch) <= 0x5a
                       for ch in candidate):
                    return candidate
        # 日文场景：如果名字过长（>15字符）且包含空格，可能是 "歌手 专辑名" 格式
        # 取第一个空格前的部分作为歌手名
        if len(name) > 15 and ' ' in name:
            first_part = name.split(' ', 1)[0].strip()
            if 2 <= len(first_part) <= 15:
                return first_part
        return name.strip()

    # 纯英文/拉丁文场景：如果名字过长（>20字符）且包含空格，取第一个词或前两个词
    if len(name) > 20 and ' ' in name:
        words = name.split()
        # 取前两个词（通常是 "FirstName LastName" 或 "Band Name"）
        if len(words) >= 2:
            candidate = ' '.join(words[:2])
            if len(candidate) <= 20:
                return candidate
        # 或者只取第一个词
        if len(words[0]) >= 2:
            return words[0]

    return name.strip()


def clean_album_dir_name(dirname):
    """
    从目录名中清洗出专辑名，去除年份前缀。
    只去除合理的年份范围(1900-2099)，避免误删专辑名中的其他4位数字。
    "1999-吻别" -> "吻别"
    "[1999]吻别" -> "吻别"
    "1999.吻别" -> "吻别"
    "吻别(1999)" -> "吻别"
    "10000 Days" -> "10000 Days" (保留，10000不是年份)
    """
    if not dirname:
        return dirname
    name = dirname.strip()
    # 去除开头的年份前缀: "1999.吻别" / "1999-吻别" / "1999_吻别"
    # 限制为 19xx 或 20xx，避免误删如 "10000 Days" 中的 "1000"
    name = re.sub(r'^(?:19|20)\d{2}[.\-_\s]\s*', '', name)
    # 去除方括号/圆括号中的年份: "吻别[1999]" / "吻别(1999)"
    name = re.sub(r'[\[【\(（]\s*(?:19|20)\d{2}\s*[\]】\)）]', '', name)
    # 去除末尾的年份: "吻别 1999" -> "吻别"
    name = re.sub(r'\s*(?:19|20)\d{2}$', '', name)
    return name.strip() or dirname


def _clean_album_name(album):
    """
    清洗专辑名，去除无关前缀和后缀。
    "2010.张学友.歌神热辣辣 3CD 引进版" -> "歌神热辣辣"
    "张学友-歌神热辣辣" -> "歌神热辣辣"
    """
    if not album:
        return album
    name = album.strip()
    # 去除开头的年份前缀: "2010.专辑名" / "2010-专辑名"
    name = re.sub(r'^\d{4}[.\-_\s]\s*', '', name)
    # 去除开头的歌手名: "张学友.专辑名" / "张学友-专辑名"
    # 只去除点号或dash分隔的第一段（如果是中文名）
    if re.match(r'^[\u4e00-\u9fff]+[.\-]', name):
        parts = re.split(r'[.\-]', name, 1)
        if len(parts) == 2 and parts[1].strip():
            # 确保第一段是歌手名（2-4个中文字符）
            if 2 <= len(parts[0].strip()) <= 4:
                name = parts[1].strip()
    # 修复(Bug R/X)：去除 CD 数量后缀 "3CD"/"2CD"/"CD1"/"CD 2"/"Disc 1"
    # 原正则 `\s*\d*\s*CD\s*` 只删 CD 前的数字，不删后面的，导致 "演唱会CD2" → "演唱会2"
    # 且会误伤 "LPCD1630"（删掉 CD 后残留 LP1630）
    # 新正则：CD 前后数字都删，且 CD 后不能跟字母（避免误伤 LPCD/HCDC 等），但可跟数字
    name = re.sub(r'\s*\d*\s*CD(?![A-Za-z])\s*\d*\s*', ' ', name, flags=re.IGNORECASE)
    name = re.sub(r'\s*Disc\s*\d+\s*', ' ', name, flags=re.IGNORECASE)
    # 去除末尾裸碟号: "专辑名1"/"专辑名2"（来自源标签的碟号拼接，如 "Eason's Life1"）
    # 仅当末尾是单数字且前面是字母或中文时才去除（避免误伤 "21"/"1989" 等数字专辑名）
    name = re.sub(r'(?<=[A-Za-z\u4e00-\u9fff])\d{1,2}$', '', name)
    # 去除版本标注: "引进版", "日本版", "港版", "内地版"
    name = re.sub(r'\s*(引进版|日本版|港版|内地版|台版|欧美版|韩版|日版)\s*', '', name)
    # 去除音质标注: "SACD", "DSD", "K2HD", "24K GOLD", "HQCD", "HQ"
    name = re.sub(r'\s*(SACD|DSD|K2HD|24K\s*GOLD|HQCD|HQ|HDCD|LPCD)\s*', ' ', name, flags=re.IGNORECASE)
    # 合并多余空格
    name = re.sub(r'\s+', ' ', name).strip()
    # 去除末尾的点和空格
    name = name.strip('. ')
    return name if name else album


# 修复(Bug T)：合辑名/榜单名模式，刮削器返回这些名称时拒绝采纳
COMPILATION_ALBUM_PATTERNS = re.compile(
    r'热门华语|热门单曲|热门英文|精选合辑|国语精选|华语精选|'
    r'Top\s*\d+|Billboard\s*\d+|'
    r'^\d{0,4}大碟$|^\d{0,4}金曲$|'
    r'热门\d+|Best\s*\d+|Greatest\s*Hits',
    re.IGNORECASE
)


def _is_compilation_album(name):
    """检测专辑名是否为合辑/榜单名（Bug T）"""
    if not name:
        return False
    return bool(COMPILATION_ALBUM_PATTERNS.search(name))


# 修复(Bug S)：智能融合专辑名 —— tag 与目录名对比，取更可靠的
def _choose_better_album(tag_album, dir_album):
    """
    智能选择更可靠的专辑名。
    启发式规则：
      1. 空值/未知 → 用另一个
      2. tag 含裸碟号后缀（如 "Life1"）→ 用目录名
      3. tag 是合辑名 → 用目录名
      4. tag 与目录名相似度 < 0.3 → 用目录名（明显是不同专辑，目录名更可靠）
      5. 目录名比 tag 更"脏"（含年份/CD号/歌手名前缀）→ 用 tag
      6. 否则用 tag（保持原优先级，向后兼容）
    """
    if not tag_album or tag_album in ('未知', '未知专辑'):
        return dir_album or tag_album or ''
    if not dir_album:
        return tag_album
    # tag 含裸碟号后缀
    if re.search(r'[A-Za-z\u4e00-\u9fff]\d{1,2}$', tag_album):
        return dir_album
    # tag 是合辑名
    if _is_compilation_album(tag_album):
        return dir_album
    # 相似度
    sim = similarity(tag_album.lower().strip(), dir_album.lower().strip())
    if sim < 0.3:
        return dir_album
    return tag_album


# 非歌手名模式（这些词被误识别为歌手时，应替换为"未知歌手"）
NON_ARTIST_PATTERNS = re.compile(
    r'^(\d+$|'
    r'\d+\s*[-._]\s*\w+.*$|'  # 修复(Bug J)：原 `[-._]?` 可选分隔符误杀 "10 Years"/"3 Doors Down" 等数字开头乐队名；改为必须显式分隔符
    r'Single$|Singles$|EP$|Albums?$|专辑$|合集$|无损合集$'
    r'|vol\.?\d*$|volume\s*\d*$'
    r'|BONUS$|Bonus$|EXTRA$|Extra$'
    r'|OST$|Soundtrack$|原声$|原声带$'
    r'|FLAC$|MP3$|WAV$|APE$'
    r'|.*\(PRO-CDR.*\).*$|'  # "Linkin Park ENTH E ND (PRO-CDR-101...)" 等 promo CD 标签
    r'.*\(Demo\).*$|.*\(Live\).*$|.*\(Acoustic\).*$'  # 包含版本标注的通常是歌曲/专辑名
    r')',
    re.IGNORECASE
)

# 合辑类歌手名 → 统一为"群星"
VARIOUS_ARTIST_PATTERNS = re.compile(
    r'^(Various\s*Artists?|VA|Various|群星|华语群星|華語群星|華納羣星|天乐群星|天樂群星)$',
    re.IGNORECASE
)

# 未知类歌手名 → 统一为"未知歌手"
UNKNOWN_ARTIST_PATTERNS = re.compile(
    r'^(Unknown|Unknown\s*Artist|未知|未知歌手)$',
    re.IGNORECASE
)


def _filter_non_artist(name):
    """过滤非歌手名，统一变体。"""
    if not name:
        return '未知歌手'
    name = name.strip()
    # 修复(Bug J)：name_map 中的已知歌手（含数字开头乐队如 "10 Years"）一律保护，不过滤
    if name in _GLOBAL_NAME_MAP_KEYS:
        return name
    if NON_ARTIST_PATTERNS.match(name):
        return '未知歌手'
    if VARIOUS_ARTIST_PATTERNS.match(name):
        return '群星'
    if UNKNOWN_ARTIST_PATTERNS.match(name):
        return '未知歌手'
    # 过长名字（>25字符）可能是歌曲名/专辑名而非歌手名
    if len(name) > 25:
        return '未知歌手'
    # 修复(Bug J)：原 `re.match(r'^\d{1,3}\s+\w+.*$', name)` 过于宽泛，
    # 误杀 "10 Years"/"3 Doors Down"/"4 Non Blondes" 等数字开头乐队名。
    # 改为：数字+(空格或分隔符)+内容，仅当内容是已知歌曲名时才过滤。
    if re.match(r'^\d{1,3}\s*[-._ ]\s*', name):
        content = re.sub(r'^\d{1,3}\s*[-._ ]\s*', '', name).strip()
        known_song_names = [
            'bleed it out', 'in the end', 'one step closer', 'new divide',
            'papercut', 'numb', 'faint', 'crawling', 'what i\'ve done',
            'leave out all the rest', 'breaking the habit', 'somewhere i belong',
            'given up', 'shadow of the day', 'valentine\'s day',
            'waiting for the end', 'burning in the skies', 'iridescent',
            'lost in the echo', 'castle of glass', 'a light that never comes',
            'final masquerade', 'heavy', 'talking to myself', 'good goodbye',
            'battle symphony', 'invisible', 'one more light',
        ]
        if content.lower() in known_song_names:
            return '未知歌手'
    # 包含明显歌曲名特征
    known_song_patterns = [
        r'We Made It', r'Enth E Nd', r'Frgt.?10', r'Leave Out All the Rest',
    ]
    for pattern in known_song_patterns:
        if re.search(pattern, name, re.IGNORECASE):
            return '未知歌手'
    # 名字包含不匹配的方括号/圆括号（如 "27]" "[经典" 等标签解析错误）
    # 正常歌手名不应包含单个的括号
    if re.search(r'[\[\](){}][^\[\](){}]*$', name) or re.search(r'^[\[\](){}]', name):
        return '未知歌手'
    # 名字主要由数字和标点组成（如 "27]" "16." "01-"）
    if len(name) <= 5 and sum(c.isdigit() for c in name) >= 1 and sum(c.isalpha() for c in name) == 0:
        return '未知歌手'
    return name


def _try_identify_unknown_artist(meta):
    """
    对未知歌手的歌曲，尝试多种方式识别。
    策略：
      1. 路径名识别：从源文件路径中重新提取歌手名
      2. 返回是否识别成功
    """
    if meta.get('artist') != '未知歌手':
        return False

    source_path = meta.get('source_path', '')
    if not source_path:
        return False

    try:
        from pathlib import Path
        filepath = Path(source_path)
        # 从路径中重新提取
        dir_info = infer_from_directory(filepath)
        if dir_info.get('artist'):
            dir_artist = normalize_text(dir_info['artist'])
            dir_artist = _filter_non_artist(dir_artist)
            if dir_artist and dir_artist not in ('未知歌手', '群星', 'Unknown Artist'):
                meta['artist'] = dir_artist
                meta['dir_artist'] = dir_artist
                return True

        # 从文件名中提取
        fname = parse_filename(filepath)
        if fname.get('artist'):
            fn_artist = normalize_text(fname['artist'])
            fn_artist = _filter_non_artist(fn_artist)
            if fn_artist and fn_artist not in ('未知歌手', '群星', 'Unknown Artist'):
                meta['artist'] = fn_artist
                return True
    except Exception:
        pass

    return False


# ============================================================
# 元数据提取
# ============================================================
def extract_metadata(filepath, encoding_fixed_count=None):
    """
    综合标签、文件名和目录结构，提取完整元数据。
    优先级：标签 > 文件名 > 目录结构
    """
    tags, was_fixed = read_tags(filepath)
    if was_fixed and encoding_fixed_count is not None:
        encoding_fixed_count[0] += 1

    fname = parse_filename(filepath)
    dir_info = infer_from_directory(filepath)

    # 合并信息（标签优先，文件名次之，目录结构兜底）
    title = tags.get('title') or fname.get('title') or filepath.stem
    title = normalize_text(title)

    artist = (tags.get('artist')
              or tags.get('albumartist')
              or fname.get('artist')
              or dir_info.get('artist')
              or '未知歌手')
    artist = normalize_text(artist)
    # 过滤非歌手名（Single/EP/Album/专辑 等被误识别为歌手）
    artist = _filter_non_artist(artist)

    album = tags.get('album') or fname.get('album') or dir_info.get('album') or ''
    album = normalize_text(album)
    album = _clean_album_name(album)

    # 修复(Bug S)：智能融合专辑名 —— tag 与目录名对比，取更可靠的
    # 演唱会/tag专辑名可疑时，目录名更可靠
    dir_album_raw = normalize_text(dir_info.get('album', '') or '')
    dir_album_clean = _clean_album_name(dir_album_raw) if dir_album_raw else ''
    if dir_album_clean and dir_album_clean != album:
        album = _choose_better_album(album, dir_album_clean)
    dir_year = dir_info.get('year', '') or ''

    # 年份提取：分离 tag 年份和目录/文件名年份
    # tag 年份中的当前年份通常是软件处理日期，不可靠；目录名年份是用户标注，更可靠
    tag_year_raw = tags.get('date') or ''
    tag_year = ''
    if tag_year_raw:
        m = re.search(r'(\d{4})', tag_year_raw)
        if m:
            tag_year = m.group(1)

    # tag 年份校验：拒绝当前年份及未来年份（tag 中的当前年份通常是处理日期，非真实发行年份）
    current_year = str(datetime.now().year)
    if tag_year and tag_year.isdigit() and int(tag_year) >= int(current_year):
        tag_year = ''

    # 合并：tag 年份 > 文件名年份 > 目录年份
    year = tag_year or fname.get('year') or dir_info.get('year') or ''

    track = tags.get('tracknumber') or fname.get('track') or ''
    if track:
        track_match = re.match(r'(\d{1,3})', track)
        if track_match:
            track = track_match.group(1).zfill(2)

    meta = {
        'title': title,
        'artist': artist,
        'album': album,
        'year': year,
        'track': track,
        'source_path': str(filepath),
        'tag_source': 'tags' if tags.get('title') else 'filename',
        'encoding_fixed': was_fixed,
        'dir_artist': normalize_text(dir_info.get('artist', '')),  # 目录推断的歌手，用于保持专辑完整性
        'dir_album': dir_album_clean,  # 目录推断的专辑名，用于源目录归组对齐(Bug EE)
        'dir_year': dir_year,  # 目录推断的年份，用于源目录归组对齐(Bug EE)
        'is_concert': detect_concert(filepath),  # 标记演唱会资源：文件夹名前加"演唱会-"标识+不触发刮削改写
    }

    # 处理标题中的 feat.
    title_clean, feat_from_title = parse_feat(meta['title'])
    if feat_from_title:
        meta['title'] = title_clean
        meta['feat'] = feat_from_title
        meta['title_display'] = f"{title_clean} feat. {', '.join(feat_from_title)}"
    else:
        meta['title_display'] = meta['title']

    # 处理歌手字段中的 feat.
    artist_clean, feat_from_artist = parse_feat(meta['artist'])
    if feat_from_artist:
        meta['artist'] = artist_clean
        if not feat_from_title:
            meta['feat'] = feat_from_artist
            meta['title_display'] = f"{meta['title']} feat. {', '.join(feat_from_artist)}"

    return meta


# ============================================================
# 文件名清理
# ============================================================
# 广告/无关信息过滤词表（正则，大小写不敏感）
AD_PATTERNS = [
    re.compile(r'捌零音乐论坛', re.IGNORECASE),
    re.compile(r'捌零音乐', re.IGNORECASE),
    re.compile(r'FLT字幕组', re.IGNORECASE),
    re.compile(r' raided\.net', re.IGNORECASE),
    re.compile(r'\[.*?音乐论坛.*?\]', re.IGNORECASE),
    re.compile(r'【.*?音乐论坛.*?】', re.IGNORECASE),
    re.compile(r'\(.*?音乐论坛.*?\)', re.IGNORECASE),
    re.compile(r'（.*?音乐论坛.*?）', re.IGNORECASE),
    re.compile(r'\[FLAC\]', re.IGNORECASE),
    re.compile(r'【无损音乐】', re.IGNORECASE),
    re.compile(r'\[www\..*?\]', re.IGNORECASE),
    re.compile(r'http[s]?://\S+', re.IGNORECASE),
    # 常见音乐论坛/资源站广告
    re.compile(r'发烧.*?论坛', re.IGNORECASE),
    re.compile(r'HiFi.*?论坛', re.IGNORECASE),
    re.compile(r' PT\b', re.IGNORECASE),
    # 经过 hash 校验，可以安全删除的尾巴
    re.compile(r'[\-_\s]+$', re.IGNORECASE),  # 结尾的 -_ 空格
]


def remove_ads(text):
    """移除广告和无关信息"""
    if not text:
        return text
    for pattern in AD_PATTERNS:
        text = pattern.sub('', text)
    # 清理因移除广告产生的连续分隔符
    text = re.sub(r'[\-_\s]{2,}', ' ', text)
    return text.strip(' -_')


def sanitize(name):
    """清理文件名中的非法字符，修复乱码，繁体转简体，移除广告"""
    if not name:
        return '未知'
    # 先修复乱码（Latin-1 误读的 GBK/BIG5）
    name, _ = try_fix_encoding(name)
    # NFC 规范化 + 繁体转简体 + 清理控制字符
    name = normalize_text(name)
    # 移除广告和无关信息
    name = remove_ads(name)
    # 去重：如果名字是 X-X 格式且两边相同（如"陈小春-陈小春"），只保留一边
    if '-' in name:
        parts = name.split('-', 1)
        if len(parts) == 2 and parts[0].strip() == parts[1].strip() and parts[0].strip():
            name = parts[0].strip()
    # 去除装饰性括号（不影响文件系统，但影响显示）
    name = re.sub(r'[\[\]【】《》〈〉「」『』]', '', name)
    # 过滤文件名非法字符（替换为下划线）
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)
    name = re.sub(r'\s+', ' ', name).strip()
    # 修复(Bug O)：保留缩写中的合法尾点（如 F.I.R.、G.E.M.）。
    # 首部点始终是装饰性的，去除；尾部点仅在非"单字母+点"缩写模式时去除。
    name = name.lstrip('. ')
    if not re.search(r'([A-Za-z]\.){2,}$', name):
        name = name.rstrip('. ')
    if len(name) > 80:
        name = name[:80]
    return name if name else '未知'


# ============================================================
# 路径计算（支持序号保留）
# ============================================================
# 专辑歌曲阈值：少于这个数的"专辑"降级为单曲处理
ALBUM_MIN_TRACKS = 3

# 修复(Bug GG)：整轨文件识别
# 整轨文件：单个文件包含整张专辑（通常搭配 .cue 分轨文件）
# 常见文件名：CDImage.ape/flac/wav, image.ape/flac, 整轨.flac 等
# 修复前：整轨文件只有1个，被 <3 首规则降级为单曲，丢失专辑归属
WHOLE_ALBUM_FILENAME_PATTERN = re.compile(
    r'^(CDImage|cdimage|image|Image|CDIMAGE|整轨|整盤|整盤轉檔|CDimage|cd_image|cdimage\.wav)$',
    re.IGNORECASE
)
# 整轨文件大小阈值（字节）：单文件 >50MB 且文件名无单曲特征时视为整轨
WHOLE_ALBUM_MIN_SIZE = 50 * 1024 * 1024  # 50MB


def _is_whole_album_file(filepath):
    """
    判断是否是整轨文件（单文件包含整张专辑）。
    判据（满足任一）：
    1. 文件名匹配整轨模式（CDImage/image/整轨 等）
    2. 同目录存在同名 .cue 文件（cue 是分轨信息，存在则说明是整轨）
    3. 文件 >50MB 且文件名是通用名（无歌手/歌名信息，如 image.flac）
    """
    p = Path(filepath)
    stem = p.stem
    name = p.name

    # 判据1：文件名匹配整轨模式
    if WHOLE_ALBUM_FILENAME_PATTERN.match(stem):
        return True

    # 判据2：同目录存在同名 .cue 文件
    cue_file = p.with_suffix('.cue')
    if cue_file.exists():
        return True

    # 判据3：文件 >50MB 且文件名是通用名（无连字符/点号分隔，长度短）
    try:
        size = p.stat().st_size
        if size > WHOLE_ALBUM_MIN_SIZE:
            # 通用名：无分隔符（- _ .），长度<=20，不是具体歌名
            if not re.search(r'[-_.]', stem) and len(stem) <= 20:
                return True
    except OSError:
        pass

    return False


# 全局国籍表，由 organize() 加载时填充（键为 display 名）
_GLOBAL_NATIONALITIES = {}

# 全局 name_map 键集合，由 organize() 加载时填充（用于 _filter_non_artist 保护已知歌手）
_GLOBAL_NAME_MAP_KEYS = set()

# 全局 name_map 完整映射，由 organize() 加载时填充（用于 _short_artist_name 反查 display 名）
# 修复(Bug P)：_GLOBAL_NATIONALITIES 只含 display 名键，别名/繁体/变体需经 name_map 反查
_GLOBAL_NAME_MAP = {}


def _lookup_nationality(name):
    """
    多层反查国籍信息（修复 Bug P/U）。
    _GLOBAL_NATIONALITIES 的键是 display 名（如 "周杰伦-Jay Chou"），
    但传入的 name 可能是别名/原标签名/繁体名/变体/带空格，导致直接 .get() miss。
    查询顺序：
      1. 直接查 _GLOBAL_NATIONALITIES[name]
      2. 通过 _GLOBAL_NAME_MAP 反查：name -> display -> nationality
      3. 繁简转换后再查（如 "陳奕迅" -> "陈奕迅"）
      4. 去除中文间空格后查（如 "中島 美雪" -> "中岛美雪"）（修复 Bug U）
      5. 大小写不敏感查
    返回: "cn" / "foreign" / None
    """
    if not name:
        return None

    def _try_query(n):
        """单次查询：直接查 + name_map 反查"""
        if not n:
            return None
        r = _GLOBAL_NATIONALITIES.get(n)
        if r:
            return r
        display = _GLOBAL_NAME_MAP.get(n)
        if display:
            r = _GLOBAL_NATIONALITIES.get(display)
            if r:
                return r
        return None

    # 1. 直接命中
    n = _try_query(name)
    if n:
        return n
    # 2. 繁简转换 + 特殊字符规范化后查
    try:
        simplified = normalize_text(name)
        if simplified != name:
            n = _try_query(simplified)
            if n:
                return n
    except Exception:
        pass
    # 3. 修复(Bug U)：去除中文之间的空格后查（如 "中島 美雪" -> "中岛美雪"）
    # 仅去除 CJK 字符之间的空格，保留英文单词间的空格
    no_cjk_space = re.sub(r'(?<=[\u4e00-\u9fff\u3040-\u30ff])\s+(?=[\u4e00-\u9fff\u3040-\u30ff])', '', name)
    if no_cjk_space != name:
        n = _try_query(no_cjk_space)
        if n:
            return n
        # 再做繁简转换
        try:
            simplified2 = normalize_text(no_cjk_space)
            if simplified2 != no_cjk_space:
                n = _try_query(simplified2)
                if n:
                    return n
        except Exception:
            pass
    # 4. 大小写不敏感查（针对英文歌手名变体，如 "linkin park" vs "Linkin Park"）
    name_lower = name.lower()
    for k, v in _GLOBAL_NATIONALITIES.items():
        if k.lower() == name_lower:
            return v
    for alias, display in _GLOBAL_NAME_MAP.items():
        if alias.lower() == name_lower:
            n = _GLOBAL_NATIONALITIES.get(display)
            if n:
                return n
    # 5. 修复(Bug U)：复合名按"-"拆分后逐段查（如 "Miyuki Nakajima-中島 美雪" -> 试 "Miyuki Nakajima"）
    # 仅对长度>=3的段做查询，避免短段误匹配（如 "A-Mei" 的 "A"）
    if '-' in name:
        for part in name.split('-'):
            part = part.strip()
            if len(part) < 3:
                continue
            n = _try_query(part)
            if n:
                return n
            # 每段也做去 CJK 空格 + 繁简转换
            part_no_space = re.sub(r'(?<=[\u4e00-\u9fff\u3040-\u30ff])\s+(?=[\u4e00-\u9fff\u3040-\u30ff])', '', part)
            if part_no_space != part:
                n = _try_query(part_no_space)
                if n:
                    return n
                try:
                    simplified3 = normalize_text(part_no_space)
                    if simplified3 != part_no_space:
                        n = _try_query(simplified3)
                        if n:
                            return n
                except Exception:
                    pass
            try:
                simplified4 = normalize_text(part)
                if simplified4 != part:
                    n = _try_query(simplified4)
                    if n:
                        return n
            except Exception:
                pass
    return None


def _short_artist_name(name):
    """
    从"中文名-英文名"或"外文名-中文译名"格式中提取简化名用于文件名。
    中国歌手(中文名-英文名): 只保留中文名，如 "周杰伦-Jay Chou" -> "周杰伦"
    外国歌手(外文名-中文译名): 只保留外文原名，如 "Linkin Park-林肯公园" -> "Linkin Park"
    纯英文名中国歌手(如 S.H.E): 保持原样
    无分隔符: 直接返回原名
    优先使用 _GLOBAL_NATIONALITIES 中的国籍信息（多层反查，修复 Bug P）。
    """
    if not name:
        return name
    # 优先使用国籍表（多层反查）
    nationality = _lookup_nationality(name)
    if nationality == 'cn':
        # 中国歌手：取中文名（如果有）
        if '-' in name:
            parts = name.split('-', 1)
            left = parts[0].strip()
            if any(0x4e00 <= ord(ch) <= 0x9fff for ch in left):
                return left
            # 纯英文名中国歌手(如 S.H.E)，display 可能就是原名
            return name
        return name
    elif nationality == 'foreign':
        # 外国歌手：取外文原名
        if '-' in name:
            parts = name.split('-', 1)
            left = parts[0].strip()
            return left
        return name
    # 无国籍信息，按格式推断
    if '-' in name:
        parts = name.split('-', 1)
        left = parts[0].strip()
        # 如果左半部分包含 CJK 字符，说明是中国歌手(中文名-英文名)，返回中文名
        if any(0x4e00 <= ord(ch) <= 0x9fff for ch in left):
            return left
        # 左半部分是外文，说明是外国歌手(外文名-中文译名)，返回外文原名
        return left
    return name


def build_target_path(meta, is_singleton, artist_canonical):
    """
    根据命名规则构建目标相对路径。
    目录名: 中文名-英文名（完整格式）
    文件名歌手: 中国歌手只保留中文名，外国歌手只保留外文原名
    专辑(3首以上): 歌手/年份-专辑/序号-歌曲名-歌手-专辑-实唱歌手.ext
    单曲(含原专辑名): 歌手/其他/序号-歌曲名-歌手-专辑-实唱歌手.ext
    当实唱歌手与专辑歌手相同时，不重复显示。
    """
    artist_display = sanitize(artist_canonical)
    title = sanitize(meta['title_display'])
    artist = sanitize(meta['artist'])
    track = meta.get('track', '')
    album = sanitize(meta.get('album')) or ''

    # 群星歌曲：歌手名含3个或更多歌手时，目录名用"群星"避免路径过长
    # 修复(Bug D)：原逻辑用 count('.')>=2 误判 S.H.E/F.I.R./G.E.M. 为群星。
    # 新逻辑：按分隔符(./,/、)切分，仅当切出3+段且非全单字母缩写时才判为群星；
    # 且基于 artist_display（目录规范名）而非 tag artist 判断。
    _sep_parts = re.split(r'[.,、]', artist_display)
    _sep_parts = [p.strip() for p in _sep_parts if p.strip()]
    _is_multi_artist = (len(_sep_parts) >= 3 and not all(len(p) == 1 for p in _sep_parts))
    if _is_multi_artist:
        artist_dir = '群星'
    else:
        artist_dir = artist_display  # 目录名保持完整格式

    # 演唱会/Live/Concert 资源：作为类似专辑复制，文件夹名前加"演唱会-"标识
    # 避免演唱会歌曲混入录音室专辑目录，同时保持专辑结构
    is_concert = meta.get('is_concert', False)

    # 文件名中的歌手用简化名（中国歌手只中文名，外国歌手只外文名）
    artist_short = _short_artist_name(artist_display)

    # 序号前缀
    track_prefix = f"{track}-" if track else ''

    # 实唱歌手：当 tag 中的歌手与专辑目录歌手不同时，追加到文件名末尾
    feat_artist = ''
    raw_dir_artist = meta.get('dir_artist', '')
    tag_artist = sanitize(meta.get('artist', ''))
    dir_artist = sanitize(raw_dir_artist) if raw_dir_artist else ''
    # 只有 dir_artist 存在且与 tag_artist 不同时才标记为嘉宾歌曲
    if dir_artist and dir_artist != '未知' and tag_artist and tag_artist != dir_artist:
        feat_artist = _short_artist_name(tag_artist)

    if is_singleton:
        # 演唱会单曲归入 歌手/演唱会-其他/
        album_part = '演唱会-其他' if is_concert else '其他'
        # 单曲也带上专辑名（如果有）
        if album:
            filename = f"{track_prefix}{title}-{artist_short}-{album}"
        else:
            filename = f"{track_prefix}{title}-{artist_short}"
    else:
        year = meta.get('year') or '未知'
        album_part = f"{year}-{album or '未知专辑'}"
        # 演唱会专辑：文件夹名前加"演唱会-"标识，如 歌手/演唱会-2013-Eason's Life/
        if is_concert:
            album_part = f"演唱会-{album_part}"
        # 专辑歌曲：用简化歌手名
        filename = f"{track_prefix}{title}-{artist_short}-{album}"

    # 追加实唱歌手（如果与专辑歌手不同）
    if feat_artist and feat_artist != artist_short:
        filename += f"-{feat_artist}"

    return str(Path(artist_dir) / album_part / filename)


# ============================================================
# 去重校验
# ============================================================
def file_hash(filepath, algorithm='md5', chunk_size=65536):
    """计算文件哈希（用于检测完全相同的文件）"""
    h = hashlib.new(algorithm)
    total_size = 0
    try:
        with open(str(filepath), 'rb') as f:
            while chunk := f.read(chunk_size):
                h.update(chunk)
                total_size += len(chunk)
        # 空文件或极小文件（<1KB）不用于去重判断
        if total_size < 1024:
            return None
        return h.hexdigest()
    except Exception:
        return None


def deduplicate_songs(songs, source_dir):
    """
    同一专辑内歌曲去重。
    策略：先按文件大小快速分组，只对大小相同的文件计算哈希。
    返回: (去重后的歌曲列表, 被去重的歌曲列表)
    """
    if len(songs) <= 1:
        return songs, []

    # 第1步：按文件大小分组（快速，不读文件内容）
    size_groups = defaultdict(list)
    for song in songs:
        try:
            size = os.path.getsize(song['source_path'])
        except OSError:
            size = 0
        size_groups[size].append(song)

    unique = []
    duplicates = []

    for size, group_songs in size_groups.items():
        if len(group_songs) == 1:
            # 大小唯一，不可能重复，直接保留
            unique.extend(group_songs)
        elif size < 1024:
            # 极小文件不可靠，全部保留
            unique.extend(group_songs)
        else:
            # 大小相同，需要计算哈希进一步判断
            for song in group_songs:
                h = file_hash(song['source_path'])
                if h:
                    song['_hash'] = h
                else:
                    # 修复(Bug K)：原用 title 作为回退，导致同名不同内容文件被误判为重复而删除。
                    # 改用 source_path（每文件唯一），确保哈希失败时不误删。
                    song['_hash'] = f"nofp_{song['source_path']}"

            # 按哈希分组
            hash_groups = defaultdict(list)
            for song in group_songs:
                hash_groups[song['_hash']].append(song)

            for hash_key, h_songs in hash_groups.items():
                if len(h_songs) == 1:
                    unique.extend(h_songs)
                else:
                    # 哈希相同=完全重复，保留第一个
                    unique.append(h_songs[0])
                    for dup in h_songs[1:]:
                        duplicates.append(dup)
                    # 清理临时字段
                    for s in h_songs:
                        s.pop('_hash', None)

    # 清理临时字段
    for song in unique:
        song.pop('_hash', None)
    for song in duplicates:
        song.pop('_hash', None)

    return unique, duplicates


# ============================================================
# 标签写入
# ============================================================
def write_tags(filepath, meta):
    """将元数据写入音频文件标签（支持多种格式）"""
    try:
        from mutagen import File as MutagenFile
        # 不用 easy=True，手动处理不同格式
        audio = MutagenFile(str(filepath))
        if audio is None:
            return False
    except Exception:
        return False

    changed = False
    fields = {
        'title': meta.get('title'),
        'artist': meta.get('artist'),
        'album': meta.get('album'),
        'date': meta.get('year'),
        'tracknumber': meta.get('track'),
    }

    try:
        for key, value in fields.items():
            if value and key not in audio:
                audio[key] = str(value)
                changed = True

        if changed:
            audio.save()
            return True
    except Exception:
        return False
    return False


# ============================================================
# 扫描
# ============================================================
def scan_audio_files(source_dir):
    """递归扫描所有音频文件"""
    files = []
    for root, dirs, filenames in os.walk(source_dir):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for fn in filenames:
            if fn.startswith('.'):
                continue
            ext = os.path.splitext(fn)[1].lower()
            if ext in AUDIO_EXTENSIONS:
                files.append(Path(root) / fn)
    return files


# ============================================================
# 主整理逻辑
# ============================================================
def organize(source_dir, output_dir, name_map_path,
             dry_run=False, do_write_tags=False,
             use_scrape=False, use_fingerprint=False,
             use_network_artist=True, clear_cache=False):
    """主整理函数"""
    print("=" * 70)
    print(f"  飞牛NAS 音乐库一键整理工具 v{__version__}")
    print("=" * 70)
    print(f"  源目录:     {source_dir}")
    print(f"  输出目录:   {output_dir}")
    print(f"  映射文件:   {name_map_path}")
    print(f"  模式:       {'试运行(不复制)' if dry_run else '实际复制'}")
    print(f"  补充标签:   {'是' if do_write_tags else '否'}")
    print(f"  网络刮削:   {'是' if use_scrape else '否'}")
    print(f"  音频指纹:   {'是' if use_fingerprint else '否'}")
    print(f"  歌手规范化: {'联网' if use_network_artist else '仅本地'}")
    print("=" * 70)
    print()

    # 检查源目录
    if not Path(source_dir).is_dir():
        print(f"[错误] 源目录不存在或不是目录: {source_dir}")
        print(f"       请用 -s 参数指定有效的源音乐目录路径")
        return

    # 检查/创建输出目录
    output_path = Path(output_dir)
    if not output_path.exists():
        if dry_run:
            print(f"[提示] 输出目录不存在（试运行模式不自动创建）: {output_dir}")
            print(f"       正式运行时会自动创建该目录")
        else:
            print(f"[提示] 输出目录不存在，正在自动创建: {output_dir}")
            try:
                output_path.mkdir(parents=True, exist_ok=True)
                print(f"       创建成功")
            except PermissionError:
                print(f"[错误] 无权限创建输出目录: {output_dir}")
                print(f"       请手动创建该目录，或指定一个有写权限的路径")
                return
            except Exception as e:
                print(f"[错误] 创建输出目录失败: {e}")
                print(f"       请手动创建该目录: mkdir -p \"{output_dir}\"")
                return
    elif not output_path.is_dir():
        print(f"[错误] 输出路径已存在但不是目录: {output_dir}")
        return
    print()

    # 加载配置
    # 加载 name_map.json（支持新旧两种格式）
    name_map = {}
    artist_nationalities = {}  # {display_name: "cn"/"foreign"}
    try:
        with open(name_map_path, 'r', encoding='utf-8') as f:
            raw_map = json.load(f)

        if 'artists' in raw_map:
            # 新格式: {"artists": {"周杰伦": {"display": "周杰伦-Jay Chou", "nationality": "cn"}}}
            for alias, info in raw_map['artists'].items():
                display = info.get('display', alias)
                name_map[alias] = display
                nationality = info.get('nationality')
                if nationality:
                    artist_nationalities[display] = nationality
        else:
            # 旧格式: {"周杰伦": "周杰伦-Jay Chou"}（向后兼容）
            for k, v in raw_map.items():
                if not k.startswith('_'):
                    name_map[k] = v
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    name_map_count = len(name_map)

    # 填充全局国籍表，供 _short_artist_name() 使用
    global _GLOBAL_NATIONALITIES
    _GLOBAL_NATIONALITIES = artist_nationalities

    # 填充全局 name_map 键集合，供 _filter_non_artist() 保护已知歌手（修复 Bug J）
    global _GLOBAL_NAME_MAP_KEYS
    _GLOBAL_NAME_MAP_KEYS = set(name_map.keys())

    # 填充全局 name_map 完整映射，供 _short_artist_name() 反查 display 名（修复 Bug P）
    global _GLOBAL_NAME_MAP
    _GLOBAL_NAME_MAP = name_map

    config_dir = Path(name_map_path).parent
    args_clear_cache = clear_cache

    # 初始化各模块
    print("[初始化] 加载模块...")

    # --clear-cache: 在模块初始化前清除全部缓存文件（修复：原逻辑只清2个且时机太晚）
    # 覆盖全部5个缓存：artist_cache / scraper_cache / netease_cache / fingerprint_cache / shazam_cache
    if args_clear_cache:
        cache_file_names = [
            'artist_cache.json',
            'scraper_cache.json',
            'netease_cache.json',
            'fingerprint_cache.json',
            'shazam_cache.json',
        ]
        cleared = []
        for cfn in cache_file_names:
            cf = config_dir / cfn
            if cf.exists():
                try:
                    cf.unlink()
                    cleared.append(cfn)
                except Exception as e:
                    print(f"  清除缓存失败 {cfn}: {e}")
        if cleared:
            print(f"  已清除全部缓存: {', '.join(cleared)}")
        else:
            print(f"  无缓存文件可清除")

    # 删除旧的歌手缓存（name_map 更新后需要重新查询）
    artist_cache_file = config_dir / 'artist_cache.json'
    if artist_cache_file.exists():
        try:
            with open(artist_cache_file, 'r', encoding='utf-8') as f:
                cached_data = json.load(f)
            cached_count = len(cached_data.get('cache', {}))
            # name_map 条目数差异超过20%时刷新缓存
            diff = abs(name_map_count - cached_count)
            threshold = max(10, int(cached_count * 0.2))
            if cached_count > 0 and diff > threshold:
                artist_cache_file.unlink()
                print(f"  歌手缓存已刷新 (name_map {name_map_count} 条 vs 缓存 {cached_count} 条, 差异 {diff} > 阈值 {threshold})")
            else:
                print(f"  歌手缓存保留 (name_map {name_map_count} 条 vs 缓存 {cached_count} 条)")
        except Exception as e:
            print(f"  歌手缓存检查异常: {e}")
            pass

    artist_normalizer = ArtistNormalizer(
        name_map=name_map,
        use_network=use_network_artist,
        cache_file=str(artist_cache_file),
    )

    scraper = MusicBrainzScraper(
        cache_file=str(config_dir / 'scraper_cache.json')
    ) if use_scrape else None

    fp_identifier = FingerprintIdentifier(
        cache={},
        cache_file=str(config_dir / 'fingerprint_cache.json')
    ) if use_fingerprint else None

    # 初始化 Shazam 指纹识别（优先级最高，完全免费无需 API Key）
    shazam_identifier = None
    if use_fingerprint:
        try:
            from shazam_fingerprint import ShazamIdentifier
            shazam_identifier = ShazamIdentifier(
                cache_file=str(config_dir / 'shazam_cache.json')
            )
            print(f"  Shazam指纹:  {'可用' if shazam_identifier.is_available() else '不可用(shazamio未安装)'}")
        except Exception as e:
            print(f"  Shazam指纹:  初始化失败 ({e})")

    # 初始化酷狗刮削器
    kugou_scraper = KugouScraper(
        cache={}
    ) if use_scrape else None

    # 初始化网易云音乐刮削器
    netease_scraper = None
    if use_scrape:
        try:
            from netease_scraper import NetEaseScraper
            netease_scraper = NetEaseScraper(
                cache_file=str(config_dir / 'netease_cache.json')
            )
            print(f"  网易云刮削: 可用")
        except Exception as e:
            print(f"  网易云刮削: 初始化失败 ({e})")

    if use_fingerprint:
        fp_available = fp_identifier.is_available()
        fp_backend = fp_identifier.is_backend_available()
        fp_key_status = fp_identifier.get_key_status()
        if fp_key_status == "default":
            if fp_backend:
                print(f"  音频指纹: 后端可用(pyacoustid/fpcalc)，但未配置API KEY")
                print(f"           请在 https://acoustid.org/api-key 申请免费 KEY")
                print(f"           配置方式: 设置环境变量 ACOUSTID_API_KEY 或修改 fingerprint.py")
            else:
                print(f"  音频指纹: 后端不可用 + 未配置API KEY")
                print(f"           安装后端: pip install pyacoustid")
                print(f"           或: apt-get install -y libchromaprint-tools (fpcalc)")
                print(f"           API KEY: 请在 https://acoustid.org/api-key 申请免费 KEY")
                print(f"           配置方式: 设置环境变量 ACOUSTID_API_KEY")
        elif fp_key_status is False:
            if fp_backend:
                print(f"  音频指纹: 后端可用，但API KEY无效")
                print(f"           请检查 ACOUSTID_API_KEY 是否正确")
            else:
                print(f"  音频指纹: 后端不可用 + API KEY无效")
                print(f"           安装后端: pip install pyacoustid")
                print(f"           或: apt-get install -y libchromaprint-tools (fpcalc)")
                print(f"           API KEY: 请检查 ACOUSTID_API_KEY 是否正确")
        else:
            # KEY 有效 (fp_key_status is True)
            if fp_available:
                print(f"  音频指纹: 可用")
            elif not fp_backend:
                print(f"  音频指纹: API KEY已配置，但后端不可用")
                print(f"           安装后端: pip install pyacoustid")
                print(f"           或: apt-get install -y libchromaprint-tools (fpcalc)")
            else:
                print(f"  音频指纹: 不可用")

    if kugou_scraper and use_scrape:
        kugou_available = kugou_scraper.is_available()
        if not kugou_available:
            print(f"  酷狗刮削: 接口不可用（可能已失效，不影响其他功能）")
        else:
            print(f"  酷狗刮削: 可用（非官方接口，可能随时失效）")

    # 1. 扫描
    print()
    print("[1/8] 扫描音频文件...")
    audio_files = scan_audio_files(source_dir)
    print(f"  找到 {len(audio_files)} 个音频文件")
    if not audio_files:
        print("  未找到音频文件，退出。")
        return

    # 2. 提取元数据（含编码修复）
    print()
    print("[2/8] 读取标签和文件名信息...")
    encoding_fixed_count = [0]
    all_meta = []
    tag_count = 0
    fname_count = 0

    bar = ProgressBar("提取元数据", len(audio_files), unit="首")
    for i, fp in enumerate(audio_files):
        meta = extract_metadata(fp, encoding_fixed_count)
        all_meta.append(meta)
        if meta['tag_source'] == 'tags':
            tag_count += 1
        else:
            fname_count += 1
        bar.update(i + 1)
    bar.finish()

    print(f"  标签完整: {tag_count} 首")
    print(f"  从文件名解析: {fname_count} 首")
    if encoding_fixed_count[0] > 0:
        print(f"  修复乱码标签: {encoding_fixed_count[0]} 首")

    # 3. 歌手名规范化
    print()
    print("[3/8] 歌手名规范化...")
    all_artists = sorted(set(m['artist'] for m in all_meta if m['artist'] != '未知歌手'))
    print(f"  发现 {len(all_artists)} 位歌手，正在规范化...")

    # 歌手规范化内部有网络查询，逐个显示进度
    artist_mapping = {}
    bar = ProgressBar("规范化歌手", len(all_artists), unit="位")
    for i, artist in enumerate(all_artists):
        bar.set_description(f"规范化: {artist}")
        result = artist_normalizer.normalize_one(artist)
        artist_mapping[artist] = result
        bar.update(i + 1)
    bar.set_description("规范化歌手")  # 恢复默认描述
    bar.finish()

    # 用网易云音乐补充未识别的歌手别名
    if netease_scraper:
        # 只补充 name_map 中没有的歌手（避免覆盖 name_map 的正确映射）
        unresolved = [a for a in all_artists
                      if artist_mapping.get(a, a) == a and a not in name_map]
        if unresolved:
            bar = ProgressBar("网易云补全", len(unresolved), unit="位")
            netease_enriched = 0
            for i, artist in enumerate(unresolved):
                try:
                    aliases = netease_scraper.get_artist_aliases(artist)
                    if aliases:
                        # 如果有别名，用"原名-别名"格式
                        from artist_normalizer import detect_language
                        zh_names = []
                        en_names = []
                        for alias in aliases + [artist]:
                            lang = detect_language(alias)
                            if lang == 'zh' and alias not in zh_names:
                                zh_names.append(alias)
                            elif lang == 'en' and alias not in en_names:
                                en_names.append(alias)
                        if zh_names and en_names:
                            canonical = f"{zh_names[0]}-{en_names[0]}"
                        elif zh_names:
                            canonical = zh_names[0]
                        elif en_names:
                            canonical = en_names[0]
                        else:
                            canonical = artist
                        if canonical != artist:
                            artist_mapping[artist] = canonical
                            netease_enriched += 1
                except (OSError, ValueError, KeyError, TypeError):
                    pass
                bar.update(i + 1)
            bar.finish()
            print(f"  网易云补充歌手别名: {netease_enriched} 位")

    # 统计合并情况
    merged_count = sum(1 for k, v in artist_mapping.items() if k != v)
    print(f"  规范化完成: 合并 {merged_count} 个变体")

    # 更新元数据中的歌手名
    for meta in all_meta:
        if meta['artist'] in artist_mapping:
            meta['artist_original'] = meta['artist']
            meta['artist'] = artist_mapping[meta['artist']]

    # 3a. 强制应用 name_map 映射（确保即使 artist_normalizer 缓存/网络有问题，
    #     name_map 中的映射也能生效）
    name_map_applied = 0
    for meta in all_meta:
        raw_artist = meta.get('artist_original', meta['artist'])
        if raw_artist in name_map:
            mapped = name_map[raw_artist]
            if meta['artist'] != mapped:
                meta['artist'] = mapped
                name_map_applied += 1
    if name_map_applied > 0:
        print(f"  name_map 强制映射: {name_map_applied} 首")

    # 3b. 对未知歌手尝试路径名识别（在刮削之前）
    unknown_count = sum(1 for m in all_meta if m['artist'] == '未知歌手')
    if unknown_count > 0:
        path_identified = 0
        for meta in all_meta:
            if _try_identify_unknown_artist(meta):
                path_identified += 1
        if path_identified > 0:
            print(f"  路径识别: {path_identified}/{unknown_count} 首未知歌曲识别出歌手")
            # 重新规范化新识别的歌手
            new_artists = set(m['artist'] for m in all_meta
                              if m['artist'] != '未知歌手' and m['artist'] not in artist_mapping)
            for artist in new_artists:
                artist_mapping[artist] = artist_normalizer.normalize_one(artist)
            for meta in all_meta:
                if meta['artist'] in artist_mapping:
                    meta['artist_original'] = meta.get('artist_original', meta['artist'])
                    meta['artist'] = artist_mapping[meta['artist']]

    # 4. 多刮削源并行补全（每个源独立线程，互不干扰）
    if use_scrape:
        print()
        print("[4/8] 网络刮削补全元数据（3源并行）...")

        # 检测并提示过期缓存文件
        cache_files = []
        netease_cache = config_dir / 'netease_cache.json'
        scraper_cache = config_dir / 'scraper_cache.json'
        if netease_cache.exists():
            cache_files.append(netease_cache)
        if scraper_cache.exists():
            cache_files.append(scraper_cache)
        if cache_files:
            from datetime import datetime as _dt
            now = _dt.now()
            stale_threshold = 7 * 86400  # 7 天
            stale_files = []
            for cf in cache_files:
                try:
                    mtime = cf.stat().st_mtime
                    age = now.timestamp() - mtime
                    if age > stale_threshold:
                        stale_files.append(cf.name)
                except Exception:
                    pass
            if stale_files:
                print(f"  [提示] 检测到过期缓存文件: {', '.join(stale_files)}")
                print(f"         过期缓存可能导致刮削结果为空，建议使用 --clear-cache 清除后重试")
            else:
                print(f"  [提示] 检测到缓存文件，刮削会使用已有缓存（使用 --clear-cache 可清除）")
        # 注：--clear-cache 已在模块初始化前清除全部缓存，此处无需再处理

        scraped_mb_count = 0
        scraped_kugou_count = 0
        scraped_netease_count = 0
        need_scrape_items = [(i, m) for i, m in enumerate(all_meta)
                             if (not m.get('album') or not m.get('year'))]

        if need_scrape_items:
            # 构建可用刮削器列表
            available_scrapers = {}
            if netease_scraper:
                available_scrapers['netease'] = netease_scraper
            if scraper:
                available_scrapers['musicbrainz'] = scraper
            if kugou_scraper and kugou_scraper.is_available():
                available_scrapers['kugou'] = kugou_scraper

            if available_scrapers:
                # 并行策略：每个刮削器独占一个线程，内部串行处理所有歌曲
                # 线程安全：每个刮削器只在自己的线程中被调用，无竞态
                results_lock = threading.Lock()
                all_results = {}  # scraper_name -> [(orig_i, enriched_meta), ...]
                # 实时计数器：记录每个刮削器已处理的歌曲数（用于进度条）
                processed_count = {}  # scraper_name -> int
                # 中断标志：用于 Ctrl+C 优雅中断
                scrape_interrupted = threading.Event()

                def _run_scraper(scraper_obj, name, songs):
                    """单刮削器线程：串行处理所有歌曲，实时更新结果"""
                    local_results = []
                    for idx, (orig_i, meta) in enumerate(songs):
                        if scrape_interrupted.is_set():
                            break
                        try:
                            if name == 'musicbrainz':
                                enriched, changed = scraper_obj.enrich_metadata(
                                    dict(meta), use_fingerprint=None
                                )
                            else:
                                enriched, changed = scraper_obj.enrich_metadata(dict(meta))
                            if changed:
                                local_results.append((orig_i, enriched))
                        except Exception:
                            pass
                        # 每处理完一首就更新共享计数器，使进度条实时反映
                        with results_lock:
                            processed_count[name] = idx + 1
                    with results_lock:
                        all_results[name] = local_results

                # 启动所有刮削器线程
                threads = []
                for name, scraper_obj in available_scrapers.items():
                    songs = [(i, m) for i, m in need_scrape_items]
                    processed_count[name] = 0
                    t = threading.Thread(
                        target=_run_scraper,
                        args=(scraper_obj, name, songs),
                        daemon=True
                    )
                    t.start()
                    threads.append(t)

                # 等所有线程完成，进度条基于最快刮削器的进度
                # （只需要任一源成功即可，所以显示最快进度更合理）
                num_scrapers = len(available_scrapers)
                bar = ProgressBar("刮削补全  ", len(need_scrape_items), unit="首")
                processed = 0
                log_interval = max(50, len(need_scrape_items) // 10)  # 每50首或10%打印一次
                logged_milestones = {}  # scraper_name -> last_logged_count
                try:
                    while any(t.is_alive() for t in threads):
                        time.sleep(0.5)
                        # 基于最快刮削器的已处理数计算进度（取 max 而非平均）
                        max_processed = 0
                        with results_lock:
                            for name in available_scrapers:
                                cnt = processed_count.get(name, 0)
                                max_processed = max(max_processed, cnt)
                                # 每隔 log_interval 首打印各源独立进度（只在新里程碑时打印）
                                last_logged = logged_milestones.get(name, 0)
                                if cnt >= last_logged + log_interval:
                                    logged_milestones[name] = (cnt // log_interval) * log_interval
                                    print(f"\n  [刮削进度] {name}: {cnt}/{len(need_scrape_items)}")
                        if max_processed > processed:
                            processed = max_processed
                            bar.update(min(processed, len(need_scrape_items)))
                except KeyboardInterrupt:
                    print(f"\n  [中断] 收到 Ctrl+C，正在停止刮削线程...")
                    scrape_interrupted.set()
                    # 等待线程结束（最多3秒）
                    for t in threads:
                        t.join(timeout=3.0)
                bar.finish()

                # 合并结果：取第一个刮削器返回的结果（网易云优先，其次MB，最后酷狗）
                priority = ['netease', 'musicbrainz', 'kugou']
                merged = {}  # orig_i -> (enriched, src_name)
                for src_name in priority:
                    if src_name in all_results:
                        for orig_i, enriched in all_results[src_name]:
                            if orig_i not in merged:
                                merged[orig_i] = (enriched, src_name)

                # 应用结果
                for orig_i, (enriched, src_name) in merged.items():
                    orig_meta = all_meta[orig_i]
                    # 刮削器补全的 artist 可能包含非歌手信息，需要过滤
                    if enriched.get('artist'):
                        enriched['artist'] = _filter_non_artist(enriched['artist'])
                    # 修复(Bug T)：拒绝刮削返回的合辑名/榜单名
                    if enriched.get('album') and _is_compilation_album(enriched['album']):
                        enriched['album'] = orig_meta.get('album', '')
                    # 修复(Bug W)：演唱会文件不让刮削覆盖 album（演唱会 tag 不可靠，
                    # 且刮削器容易匹配到录音室版本）
                    if orig_meta.get('is_concert') and enriched.get('album'):
                        # 演唱会只补 year，不覆盖 album
                        enriched['album'] = orig_meta.get('album', '')
                    # 修复(Bug W)：演唱会文件不让刮削覆盖 artist（避免被改成录音室原唱）
                    if orig_meta.get('is_concert') and enriched.get('artist'):
                        enriched['artist'] = orig_meta.get('artist', '')
                    # 修复(Bug FF)：目录推断的歌手(dir_artist)是用户整理标注，比刮削器可靠。
                    # 当 dir_artist 有效时，拒绝刮削器覆盖 artist。
                    # 案例：ZARD 的《素直に言えなくて》被网易云刮削器误识别成杨采妮
                    # （杨采妮有同名翻唱版本），但源路径 /Zard/Single/... 明确是 ZARD。
                    orig_dir_artist = orig_meta.get('dir_artist', '')
                    if orig_dir_artist and orig_dir_artist != '未知' and \
                       not _is_compilation_artist(orig_dir_artist) and \
                       enriched.get('artist') and enriched['artist'] != orig_meta.get('artist', ''):
                        enriched['artist'] = orig_meta.get('artist', '')
                    # 保留原始 is_concert 标记
                    enriched['is_concert'] = orig_meta.get('is_concert', False)
                    all_meta[orig_i] = enriched
                    if src_name == 'netease':
                        scraped_netease_count += 1
                    elif src_name == 'musicbrainz':
                        scraped_mb_count += 1
                    elif src_name == 'kugou':
                        scraped_kugou_count += 1

                print(f"  网易云音乐补全: {scraped_netease_count} 首")
                print(f"  MusicBrainz 补全: {scraped_mb_count} 首")
                print(f"  酷狗音乐补全: {scraped_kugou_count} 首")
                if scrape_interrupted.is_set():
                    print(f"  [注意] 刮削被用户中断，已完成的 {len(merged)} 首结果已应用")
            else:
                print(f"  刮削: 无可用刮削器")
        else:
            print(f"  刮削: 无需补全（所有歌曲已有完整信息）")

        total_scraped = scraped_mb_count + scraped_kugou_count + scraped_netease_count
        print(f"  刮削总计: {total_scraped} 首")
    else:
        print()
        print("[4/8] 网络刮削: 跳过(未启用)")

    # 4b. 刮削后二次歌手规范化（刮削器可能补全了新的歌手名；含 dir_artist）
    if use_scrape:
        print()
        print("[4b/8] 刮削后歌手名规范化...")
        # 修复(Bug H)：不再用 "not in artist_mapping" 过滤——刮削器可能把已规范名
        # 重置为原名（如 "Jay Chou"），而 "Jay Chou" 恰是 artist_mapping 的键会被跳过。
        # 改为收集所有非未知歌手名，normalize_one 对已规范名幂等。
        # 修复(Bug B)：同时规范化 dir_artist。
        post_scrape_artists = set()
        for m in all_meta:
            a = m.get('artist', '')
            if a and a != '未知歌手':
                post_scrape_artists.add(a)
            d = m.get('dir_artist', '')
            if d and d != '未知歌手' and d != '未知':
                post_scrape_artists.add(d)
        post_scrape_artists = sorted(post_scrape_artists)
        if post_scrape_artists:
            post_bar = ProgressBar("歌手规范(后)", len(post_scrape_artists), unit="位")
            post_scrape_mapping = {}
            for i, artist in enumerate(post_scrape_artists):
                # 先过滤非歌手名（Various Artists / 未知 / 数字开头歌曲名等）
                filtered = _filter_non_artist(artist)
                if filtered != artist:
                    post_scrape_mapping[artist] = filtered
                else:
                    post_scrape_mapping[artist] = artist_normalizer.normalize_one(artist)
                post_bar.update(i + 1)
            post_bar.finish()
            # 应用二次映射到 artist 和 dir_artist
            applied = 0
            for meta in all_meta:
                a = meta.get('artist', '')
                if a in post_scrape_mapping and post_scrape_mapping[a] != a:
                    meta['artist'] = post_scrape_mapping[a]
                    applied += 1
                d = meta.get('dir_artist', '')
                if d and d != '未知' and d in post_scrape_mapping and post_scrape_mapping[d] != d:
                    meta['dir_artist'] = post_scrape_mapping[d]
                    applied += 1
            # 合并到 artist_mapping（供步骤7 build_target_path 使用）
            artist_mapping.update(post_scrape_mapping)
            if applied > 0:
                print(f"  二次规范化: {applied} 处歌手名已修正")

    # 5. 音频指纹识别（信息全缺的歌曲）
    # 优先级: Shazam → AcoustID
    fp_shazam_count = 0
    fp_acoustid_count = 0
    shazam_available = shazam_identifier and shazam_identifier.is_available()
    acoustid_available = fp_identifier and fp_identifier.is_available()
    if shazam_available or acoustid_available:
        print()
        sources = []
        if shazam_available:
            sources.append("Shazam")
        if acoustid_available:
            sources.append("AcoustID")
        print(f"[5/8] 音频指纹识别（{' → '.join(sources)}）...")

        need_fp_items = [m for m in all_meta
                         if m['artist'] == '未知歌手' or not m.get('title')]
        if need_fp_items:
            fp_shazam_count = 0
            fp_acoustid_count = 0
            remaining_for_acoustid = []

            # 5a. Shazam 识别（优先，免费且曲库最大）
            if shazam_available:
                bar = ProgressBar("Shazam     ", len(need_fp_items), unit="首")
                for j, meta in enumerate(need_fp_items):
                    try:
                        result = shazam_identifier.identify(meta['source_path'])
                        if result and result.get('title'):
                            if result.get('title'):
                                meta['title'] = result['title']
                                meta['title_display'] = result['title']
                            if result.get('artist'):
                                meta['artist'] = result['artist']
                            fp_shazam_count += 1
                        else:
                            remaining_for_acoustid.append(meta)
                    except Exception:
                        remaining_for_acoustid.append(meta)
                    bar.update(j + 1)
                bar.finish()
                print(f"  Shazam 识别: {fp_shazam_count} 首")
            else:
                remaining_for_acoustid = need_fp_items

            # 5b. AcoustID 识别（Shazam 未识别的）
            if acoustid_available and remaining_for_acoustid:
                bar = ProgressBar("AcoustID   ", len(remaining_for_acoustid), unit="首")
                for j, meta in enumerate(remaining_for_acoustid):
                    result = fp_identifier.identify(meta['source_path'])
                    if result:
                        if result.get('title'):
                            meta['title'] = result['title']
                            meta['title_display'] = result['title']
                        if result.get('artist'):
                            meta['artist'] = result['artist']
                        fp_acoustid_count += 1
                    bar.update(j + 1)
                bar.finish()
                print(f"  AcoustID 识别: {fp_acoustid_count} 首")

            print(f"  指纹识别总计: {fp_shazam_count + fp_acoustid_count} 首")
        else:
            print(f"  无需指纹识别（所有歌曲已有基本信息）")
    else:
        print()
        print("[5/8] 音频指纹: 跳过(未启用)")

    # 5b. 最终统一规范化收口（架构层修复 Bug B/C）
    #     指纹识别(Shazam/AcoustID)和刮削器可能引入未经规范化的新歌手名
    #     （繁体、别名、Various Artists 变体等），历次修补只在步骤3/4b做局部规范化，
    #     新增富集步骤后就又漏。此处作为分组前的最终收口：
    #     对 meta['artist'] 和 meta['dir_artist'] 统一过
    #     _filter_non_artist → artist_normalizer.normalize_one → name_map 兜底，
    #     再更新 artist_mapping 供步骤7 build_target_path 使用。
    print()
    print("[5b/8] 最终统一规范化收口...")
    final_collect = set()
    for m in all_meta:
        a = m.get('artist', '')
        if a and a != '未知歌手':
            final_collect.add(a)
        d = m.get('dir_artist', '')
        if d and d != '未知歌手' and d != '未知':
            final_collect.add(d)
    final_mapping = {}
    if final_collect:
        bar = ProgressBar("歌手规范(终)", len(final_collect), unit="位")
        for i, artist in enumerate(sorted(final_collect)):
            # 先过滤非歌手名（Various Artists / 未知 / 数字开头歌曲名等）
            filtered = _filter_non_artist(artist)
            if filtered != artist:
                final_mapping[artist] = filtered
            else:
                normalized = artist_normalizer.normalize_one(artist)
                # name_map 强制映射兜底（normalize_one 内部已查，此处双保险）
                if normalized in name_map:
                    normalized = name_map[normalized]
                final_mapping[artist] = normalized
            bar.update(i + 1)
        bar.finish()
    # 应用最终映射到 artist 和 dir_artist
    applied_artist = 0
    applied_dir = 0
    for meta in all_meta:
        a = meta.get('artist', '')
        if a in final_mapping and final_mapping[a] != a:
            meta['artist'] = final_mapping[a]
            applied_artist += 1
        d = meta.get('dir_artist', '')
        if d and d != '未知' and d in final_mapping and final_mapping[d] != d:
            meta['dir_artist'] = final_mapping[d]
            applied_dir += 1
    # 合并到 artist_mapping（步骤7用 artist_mapping.get(group_artist, group_artist) 取规范名）
    artist_mapping.update(final_mapping)
    if applied_artist or applied_dir:
        print(f"  收口修正: {applied_artist} 首 artist, {applied_dir} 首 dir_artist")

    # 6. 分组 + 去重
    print()
    print("[6/8] 按歌手和专辑分组，执行去重...")
    import time as _time
    _t6_start = _time.time()

    # 修复(Bug EE): 同一源专辑目录内 tag album/year 不一致
    # （大小写 JAY/Jay、异体字 肖邦/萧邦、tag错误 魔天伦/魔杰座、tag date 年份不同），
    # 导致同一专辑被拆散到多个目标文件夹。
    # 方案：按源专辑目录预归组，统一 album 和 year（目录推断优先，否则取组内频次最高）。
    # 原则：源目录是用户整理时定义的专辑边界，比 tag 更可靠。
    src_dir_groups = defaultdict(list)
    for meta in all_meta:
        src_dir = str(Path(meta['source_path']).parent)
        src_dir_groups[src_dir].append(meta)

    aligned_album = 0
    aligned_year = 0
    for src_dir, metas in src_dir_groups.items():
        if len(metas) <= 1:
            continue
        # 统一 album：处理多版本差异 + 空 album 填充
        albums_all = [m.get('album', '') for m in metas]
        albums_nonempty = [a for a in albums_all if a]
        if albums_nonempty:
            # 确定统一值：目录推断优先，否则取频次最高
            dir_albums = [m.get('dir_album', '') for m in metas if m.get('dir_album')]
            if dir_albums:
                unified_album = Counter(dir_albums).most_common(1)[0][0]
            else:
                unified_album = Counter(albums_nonempty).most_common(1)[0][0]
            # 需要统一的条件：存在多版本差异，或存在空 album 需填充
            if len(set(albums_nonempty)) > 1 or '' in albums_all:
                for m in metas:
                    if m.get('album', '') != unified_album:
                        m['album'] = unified_album
                        aligned_album += 1
        # 统一 year：同理
        years_all = [m.get('year', '') for m in metas]
        years_nonempty = [y for y in years_all if y]
        if years_nonempty:
            dir_years = [m.get('dir_year', '') for m in metas if m.get('dir_year')]
            if dir_years:
                unified_year = Counter(dir_years).most_common(1)[0][0]
            else:
                unified_year = Counter(years_nonempty).most_common(1)[0][0]
            if len(set(years_nonempty)) > 1 or '' in years_all:
                for m in metas:
                    if m.get('year', '') != unified_year:
                        m['year'] = unified_year
                        aligned_year += 1
    if aligned_album or aligned_year:
        print(f"  源目录归组对齐: 统一 {aligned_album} 首专辑名, {aligned_year} 首年份(Bug EE)")

    groups = defaultdict(list)
    for meta in all_meta:
        # 优先用目录推断的歌手分组，保持专辑完整性
        # （电影原声带/演唱会等专辑中嘉宾歌曲不会被拆散）
        group_artist = meta.get('dir_artist') or meta['artist']
        key = (group_artist, meta['album'])
        groups[key].append(meta)

    # 统计歌手和专辑数量
    unique_artists = set()
    unique_albums = set()
    for (artist, album) in groups.keys():
        unique_artists.add(artist)
        if album:
            unique_albums.add((artist, album))

    print(f"  共 {len(unique_artists)} 位歌手, {len(unique_albums)} 个专辑, {len(groups)} 组")

    album_songs = []
    singleton_songs = []
    total_dups = 0
    downgraded_albums = 0
    hash_computed = 0  # 统计实际计算哈希的文件数

    group_items = list(groups.items())
    bar = ProgressBar("分组去重", len(group_items), unit="组")
    for i, ((artist, album), songs) in enumerate(group_items):
        # 修复(Bug GG)：整轨文件（单文件含整张专辑，如 CDImage.ape + .cue）
        # 即使只有1个文件也作为专辑保留，不降级为单曲
        has_whole_album = any(_is_whole_album_file(s['source_path']) for s in songs)
        if album and (len(songs) >= ALBUM_MIN_TRACKS or has_whole_album):
            # 专辑歌曲（3首以上，或含整轨文件）：去重
            # 先统计哈希计算数（优化前需要计算所有文件，优化后只算大小相同的）
            import os as _os
            size_set = set()
            for s in songs:
                try:
                    sz = _os.path.getsize(s['source_path'])
                except OSError:
                    sz = 0
                if sz in size_set:
                    hash_computed += 1
                else:
                    size_set.add(sz)

            unique, dups = deduplicate_songs(songs, source_dir)
            album_songs.extend(unique)
            singleton_songs.extend(dups)  # 重复的转为单曲保留
            total_dups += len(dups)
        elif album and len(songs) > 1:
            # 1-2首的"专辑"降级为单曲，但保留专辑名在文件名中
            singleton_songs.extend(songs)
            downgraded_albums += 1
        else:
            singleton_songs.extend(songs)
        bar.update(i + 1)
    bar.finish()

    _t6_elapsed = _time.time() - _t6_start
    print(f"  专辑歌曲: {len(album_songs)} 首")
    print(f"  零散歌曲: {len(singleton_songs)} 首 (含 {downgraded_albums} 个专辑降级)")
    print(f"  去重: {total_dups} 首(转为零散保留)")
    if hash_computed > 0:
        print(f"  哈希计算: {hash_computed} 首(仅大小相同的文件)")

    # 修复(Bug BB): 小专辑降级 — 预计算目标文件夹，只有1-2首歌的降级为单曲放到"其他"
    # 避免"单曲"等专辑因年份分叉产生大量只有1首歌的专辑文件夹
    _target_folder_counts = defaultdict(int)
    for m in album_songs:
        year = m.get('year') or '未知'
        album = m.get('album') or '未知专辑'
        is_concert = m.get('is_concert', False)
        folder = f"{year}-{album}"
        if is_concert:
            folder = f"演唱会-{folder}"
        _target_folder_counts[folder] += 1

    _downgraded_bb = 0
    _kept_album = []
    for m in album_songs:
        year = m.get('year') or '未知'
        album = m.get('album') or '未知专辑'
        is_concert = m.get('is_concert', False)
        folder = f"{year}-{album}"
        if is_concert:
            folder = f"演唱会-{folder}"
        # 修复(Bug GG)：整轨文件不参与小专辑降级（单文件即整张专辑）
        is_whole = _is_whole_album_file(m['source_path'])
        if _target_folder_counts[folder] < ALBUM_MIN_TRACKS and not is_whole:
            singleton_songs.append(m)
            _downgraded_bb += 1
        else:
            _kept_album.append(m)
    album_songs = _kept_album
    if _downgraded_bb:
        print(f"  小专辑降级: {_downgraded_bb} 首(目标文件夹<3首,转入'其他')")

    # feat. 统计
    feat_count = sum(1 for m in all_meta if m.get('feat'))
    if feat_count:
        print(f"  识别到 feat. 合作: {feat_count} 首")

    # 7. 复制
    print()
    print("[7/8] 复制文件到目标目录...")
    copied = 0
    skipped = 0
    errors = 0
    tags_written = 0
    report = []

    tasks = [(m, False) for m in album_songs] + \
            [(m, True) for m in singleton_songs]

    bar = ProgressBar("复制文件", len(tasks), unit="首")
    for task_idx, (meta, is_singleton) in enumerate(tasks):
        try:
            # 专辑歌曲和有目录推断歌手的单曲都用 dir_artist，保持归组完整性
            # 修复(Bug I)：原代码单曲(is_singleton=True)只用 tag artist，
            # 导致2首降级专辑歌曲散落到不同歌手目录，丢失专辑归组。
            raw_dir = meta.get('dir_artist', '')
            if raw_dir and raw_dir != '未知' and raw_dir != '未知歌手':
                group_artist = raw_dir
            else:
                group_artist = meta['artist']
            artist_canonical = artist_mapping.get(group_artist, group_artist)
            target_rel = build_target_path(meta, is_singleton, artist_canonical)
            ext = Path(meta['source_path']).suffix
            target_path = Path(output_dir) / f"{target_rel}{ext}"

            # 幂等：目标已存在则跳过
            if target_path.exists():
                skipped += 1
                report.append({
                    'source': meta['source_path'],
                    'target': str(target_path),
                    'status': 'skipped',
                    'artist': meta['artist'],
                    'title': meta.get('title_display', meta['title']),
                    'type': 'singleton' if is_singleton else 'album',
                })
                bar.update(task_idx + 1)
                continue

            if dry_run:
                print(f"\r  [DRY-RUN] {Path(meta['source_path']).name} -> {target_rel}{ext}")
                copied += 1
                report.append({
                    'source': meta['source_path'],
                    'target': str(target_path),
                    'status': 'dry-run',
                    'artist': meta['artist'],
                    'title': meta.get('title_display', meta['title']),
                    'type': 'singleton' if is_singleton else 'album',
                })
                bar.update(task_idx + 1)
                continue

            target_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(meta['source_path'], str(target_path))
            except OSError:
                # 跨文件系统时 copy2 可能因元数据保留失败，回退到 copy
                shutil.copy(meta['source_path'], str(target_path))
            copied += 1

            # 补充标签到新文件
            if do_write_tags and meta['tag_source'] != 'tags':
                if write_tags(target_path, meta):
                    tags_written += 1

            report.append({
                'source': meta['source_path'],
                'target': str(target_path),
                'status': 'copied',
                'artist': meta['artist'],
                'title': meta.get('title_display', meta['title']),
                'type': 'singleton' if is_singleton else 'album',
            })
        except OSError as e:
            print(f"\n  [错误] {meta['source_path']}: {e}")
            errors += 1
        except Exception as e:
            print(f"\n  [错误] {meta['source_path']}: {e}")
            errors += 1

        bar.update(task_idx + 1)
    bar.finish()

    # 7b. 复制完整专辑文件夹中的非音频文件（封面/视频/cue等）
    # 修复(Bug DD)：原逻辑只复制音频文件，遗漏同目录下的封面图片、MV视频、cue等
    if not dry_run:
        print()
        print("[7b/8] 复制专辑附加文件（封面/视频/cue等）...")
        extra_copied = 0
        extra_skipped = 0

        # 收集所有已复制的专辑目录: 源专辑目录 -> 目标专辑目录
        # 只处理专辑歌曲（非单曲），单曲的"其他"目录不复制附加文件
        album_dir_mapping = {}  # 源专辑目录 -> 目标专辑目录
        for meta in album_songs:
            src_path = Path(meta['source_path'])
            src_album_dir = src_path.parent  # 源专辑目录
            if str(src_album_dir) in album_dir_mapping:
                continue
            # 构建目标专辑目录
            raw_dir = meta.get('dir_artist', '')
            if raw_dir and raw_dir != '未知' and raw_dir != '未知歌手':
                group_artist = raw_dir
            else:
                group_artist = meta['artist']
            artist_canonical = artist_mapping.get(group_artist, group_artist)
            target_rel = build_target_path(meta, False, artist_canonical)
            # target_rel = 歌手/年份-专辑/文件名，取目录部分
            target_album_dir = Path(output_dir) / Path(target_rel).parent
            album_dir_mapping[str(src_album_dir)] = target_album_dir

        bar = ProgressBar("复制附加文件", len(album_dir_mapping), unit="目录")
        for idx, (src_dir_str, target_dir) in enumerate(album_dir_mapping.items()):
            src_dir = Path(src_dir_str)
            try:
                if not src_dir.is_dir():
                    bar.update(idx + 1)
                    continue
                # 扫描源目录中的所有非音频文件
                for item in src_dir.iterdir():
                    if item.is_file() and not item.name.startswith('.'):
                        ext = item.suffix.lower()
                        if ext not in AUDIO_EXTENSIONS:
                            # 复制非音频文件到目标专辑目录
                            dst_file = target_dir / item.name
                            if dst_file.exists():
                                extra_skipped += 1
                                continue
                            try:
                                target_dir.mkdir(parents=True, exist_ok=True)
                                try:
                                    shutil.copy2(str(item), str(dst_file))
                                except OSError:
                                    shutil.copy(str(item), str(dst_file))
                                extra_copied += 1
                            except OSError:
                                extra_skipped += 1
            except OSError:
                pass
            bar.update(idx + 1)
        bar.finish()

        if extra_copied or extra_skipped:
            print(f"  附加文件: 复制 {extra_copied}, 跳过 {extra_skipped}")

    # 8. 导出报告
    print()
    print("[8/8] 生成整理报告...")
    report_file = config_dir / 'organize_report.txt'
    artists_file = config_dir / 'artists_found.txt'
    artist_variants_file = config_dir / 'artist_variants.json'

    # 导出歌手列表
    artists = sorted(set(m['artist'] for m in all_meta))
    with open(artists_file, 'w', encoding='utf-8') as f:
        for a in artists:
            canonical = artist_mapping.get(a, a)
            mark = "[已规范]" if a != canonical else "[原始]"
            f.write(f"{mark} {a}" + (f" -> {canonical}" if a != canonical else "") + "\n")

    # 导出变体映射
    with open(artist_variants_file, 'w', encoding='utf-8') as f:
        json.dump(artist_mapping, f, ensure_ascii=False, indent=2)

    # 生成报告
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write("=" * 70 + "\n")
        f.write(f"  音乐库整理报告 v{__version__}\n")
        f.write(f"  生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"  源目录: {source_dir}\n")
        f.write(f"  输出目录: {output_dir}\n")
        f.write("=" * 70 + "\n\n")
        f.write(f"总文件数: {len(all_meta)}\n")
        f.write(f"标签完整: {tag_count}\n")
        f.write(f"从文件名解析: {fname_count}\n")
        f.write(f"修复乱码: {encoding_fixed_count[0]}\n")
        f.write(f"歌手规范化: 合并 {merged_count} 个变体\n")
        if scraper:
            f.write(f"网络刮削补全: {scraped_mb_count + scraped_kugou_count + scraped_netease_count} (MusicBrainz: {scraped_mb_count}, 网易云: {scraped_netease_count}, 酷狗: {scraped_kugou_count})\n")
        if fp_identifier and fp_identifier.is_available():
            f.write(f"音频指纹识别: {fp_shazam_count + fp_acoustid_count} (Shazam: {fp_shazam_count}, AcoustID: {fp_acoustid_count})\n")
        f.write(f"feat.识别: {feat_count}\n")
        f.write(f"专辑歌曲: {len(album_songs)}\n")
        f.write(f"零散歌曲: {len(singleton_songs)}\n")
        f.write(f"去重: {total_dups}\n")
        f.write(f"已复制: {copied}\n")
        f.write(f"已跳过: {skipped}\n")
        f.write(f"错误: {errors}\n")
        if do_write_tags:
            f.write(f"标签补充: {tags_written}\n")
        f.write(f"\n歌手列表 ({len(artists)} 位):\n")
        for a in artists:
            canonical = artist_mapping.get(a, a)
            mark = "[已规范]" if a != canonical else "[原始]"
            f.write(f"  {mark} {a}" + (f" -> {canonical}" if a != canonical else "") + "\n")
        f.write(f"\n详细操作记录:\n")
        for r in report:
            f.write(f"  [{r['status']}] {r['source']}\n")
            f.write(f"    -> {r['target']}\n")

    print(f"  报告: {report_file}")
    print(f"  歌手列表: {artists_file}")
    print(f"  变体映射: {artist_variants_file}")

    # 汇总
    print()
    print("=" * 70)
    print("  整理完成!")
    print("=" * 70)
    print(f"  已复制: {copied}")
    print(f"  已跳过: {skipped}")
    print(f"  错误:   {errors}")
    if do_write_tags:
        print(f"  标签补充: {tags_written}")
    print(f"  修复乱码: {encoding_fixed_count[0]}")
    print(f"  歌手规范化: 合并 {merged_count} 个变体")
    if scraper or kugou_scraper:
        print(f"  网络刮削: {scraped_mb_count + scraped_kugou_count + scraped_netease_count} 首 (MB: {scraped_mb_count}, 网易云: {scraped_netease_count}, 酷狗: {scraped_kugou_count})")
    if fp_shazam_count or fp_acoustid_count:
        print(f"  指纹识别: {fp_shazam_count + fp_acoustid_count} 首 (Shazam: {fp_shazam_count}, AcoustID: {fp_acoustid_count})")
    print(f"  feat.识别: {feat_count} 首")
    print(f"  去重: {total_dups} 首")
    print("=" * 70)


# ============================================================
# 命令行入口
# ============================================================
if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description=f'飞牛NAS 音乐库一键整理工具 v{__version__}',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 试运行
  python3 organize_music.py -s /music -o /music2 --dry-run

  # 基础整理（复制 + 补充标签）
  python3 organize_music.py -s /music -o /music2 --write-tags

  # 完整模式（标签补充 + 网络刮削 + 歌手规范化）
  python3 organize_music.py -s /music -o /music2 --write-tags --scrape

  # 全功能（含音频指纹识别）
  python3 organize_music.py -s /music -o /music2 --write-tags --scrape --fingerprint

  # 不联网（仅本地整理）
  python3 organize_music.py -s /music -o /music2 --no-network

注意: /music 和 /music2 仅为示例路径，请替换为你的实际路径。
        """
    )
    parser.add_argument('--source', '-s', default='./music',
                        help='源音乐目录（请替换为你的实际路径）')
    parser.add_argument('--output', '-o', default='./music2',
                        help='输出目录（请替换为你的实际路径，不存在时自动创建）')
    parser.add_argument('--name-map', '-m', default='name_map.json', help='中英文名映射JSON')
    parser.add_argument('--dry-run', '-n', action='store_true', help='试运行模式')
    parser.add_argument('--write-tags', '-w', action='store_true', help='补充缺失标签')
    parser.add_argument('--scrape', action='store_true', help='启用MusicBrainz网络刮削')
    parser.add_argument('--fingerprint', action='store_true', help='启用音频指纹识别')
    parser.add_argument('--no-network', action='store_true', help='禁用所有网络功能')
    parser.add_argument('--clear-cache', action='store_true', help='清除刮削缓存文件后重新刮削')

    args = parser.parse_args()

    use_network = not args.no_network

    organize(
        source_dir=args.source,
        output_dir=args.output,
        name_map_path=args.name_map,
        dry_run=args.dry_run,
        do_write_tags=args.write_tags,
        use_scrape=args.scrape and use_network,
        use_fingerprint=args.fingerprint,
        use_network_artist=use_network,
        clear_cache=args.clear_cache,
    )