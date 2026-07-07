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
from pathlib import Path
from collections import defaultdict
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
    '.wav', '.ape', '.alac', '.opus', '.aiff', '.wv'
}

FEAT_PATTERN = re.compile(
    r'\s*[\(（\[]?\s*(?:featuring|feat\.|ft\.|with)\s*[:：]?\s*'
    r'(.+?)(?:[\)）\]]|$)',
    re.IGNORECASE
)

# 文件名中的轨道号前缀（如 "01 - " 或 "01. " 或 "01_"）
TRACK_PREFIX_PATTERN = re.compile(r'^(\d{1,3})\s*[-_.\s]+\s*')


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

    # 按连字符分割
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
        result['title'] = parts[0]

    # 处理文件名本身的乱码
    for key in ['artist', 'album', 'title']:
        if key in result:
            result[key] = normalize_text(result[key])

    return result


def infer_from_directory(filepath):
    """
    从目录结构推断歌手和专辑。
    支持任意层级，智能识别 歌手/专辑 结构。
    """
    parents = list(filepath.parents)
    # 过滤掉根目录和无效目录名
    valid_parents = []
    skip_patterns = re.compile(
        r'^(\d+$|CD\d?$|Disc\s?\d+$|music$|music2$|.*\.trae$|tmp$)',
        re.IGNORECASE
    )
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
        result['artist'] = _extract_chinese_artist(valid_parents[1])  # 祖父目录
        result['album'] = valid_parents[0]   # 父目录
    elif len(valid_parents) == 1:
        result['artist'] = _extract_chinese_artist(valid_parents[0])  # 父目录

    return result


def _extract_chinese_artist(dirname):
    """
    从目录名中提取歌手名。
    处理 "中文名-英文名" 格式，只保留中文名部分。
    如 "周杰伦-Jay Chou" -> "周杰伦"
    如 "陈小春-³¯¤p¬K" -> "陈小春" (乱码部分在 sanitize 中修复)
    如果没有中文名，返回原名。
    """
    if not dirname:
        return dirname
    # 按 dash 分割（中英文之间常见分隔符）
    parts = dirname.split('-', 1)
    if len(parts) == 2:
        left = parts[0].strip()
        # 如果左半部分包含 CJK 字符，认为是中文名
        if any(0x4e00 <= ord(ch) <= 0x9fff for ch in left):
            return left
    return dirname


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

    album = tags.get('album') or fname.get('album') or dir_info.get('album') or ''
    album = normalize_text(album)

    year = tags.get('date') or ''
    if year:
        year_match = re.search(r'(\d{4})', year)
        if year_match:
            year = year_match.group(1)

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
    # 过滤文件名非法字符
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)
    name = re.sub(r'\s+', ' ', name).strip()
    name = name.strip('. ')
    if len(name) > 80:
        name = name[:80]
    return name if name else '未知'


# ============================================================
# 路径计算（支持序号保留）
# ============================================================
# 专辑歌曲阈值：少于这个数的"专辑"降级为单曲处理
ALBUM_MIN_TRACKS = 3

def build_target_path(meta, is_singleton, artist_canonical):
    """
    根据命名规则构建目标相对路径。
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
    if artist.count('.') + artist.count(',') + artist.count('、') >= 2:
        artist_dir = '群星'
    else:
        artist_dir = artist_display

    # 序号前缀
    track_prefix = f"{track}-" if track else ''

    # 实唱歌手：当 tag 中的歌手与专辑目录歌手不同时，追加到文件名末尾
    # 例如：周杰伦专辑中江语晨唱的歌，文件名为 歌名-周杰伦-专辑-江语晨
    feat_artist = ''
    raw_dir_artist = meta.get('dir_artist', '')
    tag_artist = sanitize(meta.get('artist', ''))
    dir_artist = sanitize(raw_dir_artist) if raw_dir_artist else ''
    # 只有 dir_artist 存在且与 tag_artist 不同时才标记为嘉宾歌曲
    if dir_artist and dir_artist != '未知' and tag_artist and tag_artist != dir_artist:
        feat_artist = tag_artist

    if is_singleton:
        album_part = '其他'
        # 单曲也带上专辑名（如果有）
        if album:
            filename = f"{track_prefix}{title}-{artist}-{album}"
        else:
            filename = f"{track_prefix}{title}-{artist}"
    else:
        year = meta.get('year') or '未知'
        album_part = f"{year}-{album or '未知专辑'}"
        # 专辑歌曲：用专辑歌手（artist_display）作为主歌手
        filename = f"{track_prefix}{title}-{artist_display}-{album}"

    # 追加实唱歌手（如果与专辑歌手不同）
    if feat_artist and feat_artist != artist_display:
        filename += f"-{feat_artist}"

    return f"{artist_dir}/{album_part}/{filename}"


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
    策略：比较文件哈希 + 音频指纹 + 文件大小 + 时长
    返回: (去重后的歌曲列表, 被去重的歌曲列表)
    """
    if len(songs) <= 1:
        return songs, []

    # 计算每个文件的哈希
    hashes = {}
    for song in songs:
        h = file_hash(song['source_path'])
        if h:
            hashes[song['source_path']] = h

    # 按哈希分组
    hash_groups = defaultdict(list)
    for song in songs:
        h = hashes.get(song['source_path'])
        if h:
            hash_groups[h].append(song)
        else:
            # 无法计算哈希的，按文件名相似度分组
            hash_groups[f"nofp_{song['title']}"].append(song)

    unique = []
    duplicates = []

    for group_key, group_songs in hash_groups.items():
        if len(group_songs) == 1:
            unique.extend(group_songs)
        else:
            # 保留第一个，其余标记为重复
            unique.append(group_songs[0])
            for dup in group_songs[1:]:
                duplicates.append(dup)

    # 对无法哈希的组，按文件名相似度去重
    # （已在上面 hash_groups 中处理，此处可扩展指纹比较）

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
             use_network_artist=True):
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
    name_map = {}
    try:
        with open(name_map_path, 'r', encoding='utf-8') as f:
            name_map = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    config_dir = Path(name_map_path).parent

    # 初始化各模块
    print("[初始化] 加载模块...")
    artist_normalizer = ArtistNormalizer(
        name_map=name_map,
        use_network=use_network_artist,
        cache_file=str(config_dir / 'artist_cache.json'),
    )

    scraper = MusicBrainzScraper(
        cache_file=str(config_dir / 'scraper_cache.json')
    ) if use_scrape else None

    fp_identifier = FingerprintIdentifier(
        cache={},
        cache_file=str(config_dir / 'fingerprint_cache.json')
    ) if use_fingerprint else None

    # 初始化酷狗刮削器
    kugou_scraper = KugouScraper(
        cache={}
    ) if use_scrape else None

    if use_fingerprint:
        fp_available = fp_identifier.is_available()
        fp_key_status = fp_identifier.get_key_status()
        if fp_key_status == "default":
            print(f"  音频指纹: 未配置API KEY，或API KEY无效，无法使用音频指纹识别")
            print(f"           请在 https://acoustid.org/api-key 申请免费 KEY")
            print(f"           配置方式: 设置环境变量 ACOUSTID_API_KEY 或修改 fingerprint.py")
        elif fp_key_status is False:
            print(f"  音频指纹: API KEY 无效，无法使用音频指纹识别")
        else:
            print(f"  音频指纹: {'可用' if fp_available else '不可用(需安装chromaprint)'}")

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
        result = artist_normalizer.normalize_one(artist)
        artist_mapping[artist] = result
        bar.update(i + 1)
    bar.finish()

    # 统计合并情况
    merged_count = sum(1 for k, v in artist_mapping.items() if k != v)
    print(f"  规范化完成: 合并 {merged_count} 个变体")

    # 更新元数据中的歌手名
    for meta in all_meta:
        if meta['artist'] in artist_mapping:
            meta['artist_original'] = meta['artist']
            meta['artist'] = artist_mapping[meta['artist']]

    # 4. 多刮削源补全（MusicBrainz → 酷狗音乐）
    if use_scrape:
        print()
        print("[4/8] 网络刮削补全元数据（MusicBrainz → 酷狗音乐）...")
        scraped_mb_count = 0
        scraped_kugou_count = 0
        need_scrape_items = [(i, m) for i, m in enumerate(all_meta)
                             if (not m.get('album') or not m.get('year'))
                             and m['artist'] != '未知歌手']

        # 4a. MusicBrainz 刮削
        if scraper:
            bar = ProgressBar("MusicBrainz", len(need_scrape_items), unit="首")
            remaining_items = []
            for j, (i, meta) in enumerate(need_scrape_items):
                enriched, changed = scraper.enrich_metadata(
                    meta,
                    use_fingerprint=None  # 指纹在步骤5单独处理
                )
                if changed:
                    all_meta[i] = enriched
                    scraped_mb_count += 1
                else:
                    remaining_items.append((i, all_meta[i]))
                bar.update(j + 1)
            bar.finish()
            print(f"  MusicBrainz 补全: {scraped_mb_count} 首")
        else:
            remaining_items = need_scrape_items

        # 4b. 酷狗音乐刮削（对 MusicBrainz 未补全的歌曲）
        if kugou_scraper and kugou_scraper.is_available() and remaining_items:
            bar = ProgressBar("酷狗音乐  ", len(remaining_items), unit="首")
            for j, (i, meta) in enumerate(remaining_items):
                enriched, changed = kugou_scraper.enrich_metadata(meta)
                if changed:
                    all_meta[i] = enriched
                    scraped_kugou_count += 1
                bar.update(j + 1)
            bar.finish()
            print(f"  酷狗音乐补全: {scraped_kugou_count} 首")
        else:
            if not kugou_scraper:
                print(f"  酷狗音乐: 跳过(未启用)")
            elif not kugou_scraper.is_available():
                print(f"  酷狗音乐: 接口不可用")

        total_scraped = scraped_mb_count + scraped_kugou_count
        print(f"  刮削总计: {total_scraped} 首")
    else:
        print()
        print("[4/8] 网络刮削: 跳过(未启用)")

    # 5. 音频指纹识别（信息全缺的歌曲）
    if fp_identifier and fp_identifier.is_available():
        print()
        print("[5/8] 音频指纹识别...")
        fp_count = 0
        need_fp_items = [m for m in all_meta
                         if m['artist'] == '未知歌手' or not m.get('title')]
        if need_fp_items:
            bar = ProgressBar("指纹识别", len(need_fp_items), unit="首")
            for j, meta in enumerate(need_fp_items):
                result = fp_identifier.identify(meta['source_path'])
                if result:
                    if result.get('title'):
                        meta['title'] = result['title']
                        meta['title_display'] = result['title']
                    if result.get('artist'):
                        meta['artist'] = result['artist']
                    fp_count += 1
                bar.update(j + 1)
            bar.finish()
            print(f"  指纹识别: {fp_count} 首")
        else:
            print(f"  无需指纹识别（所有歌曲已有基本信息）")
    else:
        print()
        print("[5/8] 音频指纹: 跳过(未启用或API KEY未配置)")

    # 6. 分组 + 去重
    print()
    print("[6/8] 按歌手和专辑分组，执行去重...")
    groups = defaultdict(list)
    for meta in all_meta:
        # 优先用目录推断的歌手分组，保持专辑完整性
        # （电影原声带/演唱会等专辑中嘉宾歌曲不会被拆散）
        group_artist = meta.get('dir_artist') or meta['artist']
        key = (group_artist, meta['album'])
        groups[key].append(meta)

    album_songs = []
    singleton_songs = []
    total_dups = 0
    downgraded_albums = 0

    group_items = list(groups.items())
    bar = ProgressBar("分组去重", len(group_items), unit="组")
    for i, ((artist, album), songs) in enumerate(group_items):
        if album and len(songs) >= ALBUM_MIN_TRACKS:
            # 专辑歌曲（3首以上）：去重
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

    print(f"  专辑歌曲: {len(album_songs)} 首")
    print(f"  零散歌曲: {len(singleton_songs)} 首 (含 {downgraded_albums} 个专辑降级)")
    print(f"  去重: {total_dups} 首(转为零散保留)")

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
            # 专辑歌曲用目录推断的歌手作为主歌手，保持专辑完整性
            # 单曲用标签歌手
            if not is_singleton and meta.get('dir_artist'):
                group_artist = meta['dir_artist']
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
            shutil.copy2(meta['source_path'], str(target_path))
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
            f.write(f"网络刮削补全: {scraped_mb_count + scraped_kugou_count} (MusicBrainz: {scraped_mb_count}, 酷狗: {scraped_kugou_count})\n")
        if fp_identifier and fp_identifier.is_available():
            f.write(f"音频指纹识别: {fp_count}\n")
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
        print(f"  网络刮削: {scraped_mb_count + scraped_kugou_count} 首 (MB: {scraped_mb_count}, 酷狗: {scraped_kugou_count})")
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
    parser.add_argument('--source', '-s', default='/music',
                        help='源音乐目录（请替换为你的实际路径）')
    parser.add_argument('--output', '-o', default='/music2',
                        help='输出目录（请替换为你的实际路径，不存在时自动创建）')
    parser.add_argument('--name-map', '-m', default='name_map.json', help='中英文名映射JSON')
    parser.add_argument('--dry-run', '-n', action='store_true', help='试运行模式')
    parser.add_argument('--write-tags', '-w', action='store_true', help='补充缺失标签')
    parser.add_argument('--scrape', action='store_true', help='启用MusicBrainz网络刮削')
    parser.add_argument('--fingerprint', action='store_true', help='启用音频指纹识别')
    parser.add_argument('--no-network', action='store_true', help='禁用所有网络功能')

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
    )