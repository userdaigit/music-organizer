# -*- coding: utf-8 -*-
"""
test_organize.py
测试 organize_music.py 的核心函数。

不测试需要网络的功能（MusicBrainz、AcoustID）。
"""

from pathlib import Path

from organize_music import (
    parse_feat,
    sanitize,
    parse_filename,
    infer_from_directory,
    build_target_path,
    file_hash,
)


# ============================================================
# parse_feat
# ============================================================
def test_parse_feat_feat_dot():
    """feat. 格式"""
    title, feats = parse_feat("Song feat. Artist2")
    assert title == "Song"
    assert feats == ["Artist2"]


def test_parse_feat_ft_dot():
    """ft. 格式"""
    title, feats = parse_feat("Song ft. Artist2")
    assert title == "Song"
    assert feats == ["Artist2"]


def test_parse_feat_featuring():
    """featuring 格式"""
    title, feats = parse_feat("Song featuring Artist2")
    assert title == "Song"
    assert feats == ["Artist2"]


def test_parse_feat_with():
    """with 格式"""
    title, feats = parse_feat("Song with Artist2")
    assert title == "Song"
    assert feats == ["Artist2"]


def test_parse_feat_feat_chinese():
    """中文歌名中的 feat. 识别"""
    title, feats = parse_feat("简单爱 feat. 周杰伦")
    assert title == "简单爱"
    assert feats == ["周杰伦"]


def test_parse_feat_multiple_artists_amp():
    """多个合作歌手（用 & 分隔）"""
    title, feats = parse_feat("Song feat. Artist2 & Artist3")
    assert title == "Song"
    assert "Artist2" in feats
    assert "Artist3" in feats


def test_parse_feat_multiple_artists_comma():
    """多个合作歌手（用逗号分隔）"""
    title, feats = parse_feat("Song feat. Artist2, Artist3")
    assert title == "Song"
    assert "Artist2" in feats
    assert "Artist3" in feats


def test_parse_feat_multiple_artists_chinese_comma():
    """多个合作歌手（用中文逗号分隔）"""
    title, feats = parse_feat("Song feat. Artist2，Artist3")
    assert title == "Song"
    assert "Artist2" in feats
    assert "Artist3" in feats


def test_parse_feat_in_parens():
    """括号中的 feat."""
    title, feats = parse_feat("Song (feat. Artist2)")
    assert title == "Song"
    assert feats == ["Artist2"]


def test_parse_feat_in_chinese_parens():
    """中文括号中的 feat."""
    title, feats = parse_feat("Song（feat. Artist2）")
    assert title == "Song"
    assert feats == ["Artist2"]


def test_parse_feat_no_feat():
    """没有 feat. 的文本应原样返回"""
    title, feats = parse_feat("Song")
    assert title == "Song"
    assert feats == []


def test_parse_feat_empty():
    """空字符串应返回空"""
    title, feats = parse_feat("")
    assert title == ""
    assert feats == []


def test_parse_feat_none():
    """None 输入应安全处理"""
    title, feats = parse_feat(None)
    assert title is None
    assert feats == []


# ============================================================
# sanitize
# ============================================================
def test_sanitize_normal_text():
    """正常文本不应被修改"""
    assert sanitize("周杰伦") == "周杰伦"
    assert sanitize("Hello World") == "Hello World"


def test_sanitize_illegal_chars():
    """非法字符应被替换为下划线"""
    illegal = '<>:"/\\|?*'
    result = sanitize(illegal)
    for ch in illegal:
        assert ch not in result
    # 每个非法字符替换为 _
    assert result == '_' * len(illegal)


def test_sanitize_each_illegal_char():
    """逐一测试每个非法字符"""
    assert sanitize('<') == '_'
    assert sanitize('>') == '_'
    assert sanitize(':') == '_'
    assert sanitize('"') == '_'
    assert sanitize('/') == '_'
    assert sanitize('\\') == '_'
    assert sanitize('|') == '_'
    assert sanitize('?') == '_'
    assert sanitize('*') == '_'


def test_sanitize_empty():
    """空字符串应返回 '未知'"""
    assert sanitize('') == '未知'


def test_sanitize_none():
    """None 应返回 '未知'"""
    assert sanitize(None) == '未知'


def test_sanitize_whitespace():
    """多余空格应被合并"""
    assert sanitize('  hello   world  ') == 'hello world'


def test_sanitize_strips_dots():
    """首尾的点号和空格应被去除"""
    assert sanitize('...hello...') == 'hello'


def test_sanitize_control_chars():
    """控制字符应被替换"""
    result = sanitize('hello\x00world')
    assert '\x00' not in result


def test_sanitize_long_name():
    """超长名称应被截断为 80 字符"""
    long_name = 'a' * 300
    result = sanitize(long_name)
    assert len(result) == 80


def test_sanitize_all_illegal_becomes_unknown():
    """全为非法字符且截断后为空时应返回 '未知'"""
    # 仅含点号和空格 -> strip('. ') 后为空 -> '未知'
    assert sanitize('...   ...') == '未知'


# ============================================================
# parse_filename
# ============================================================
def test_parse_filename_three_parts(tmp_path):
    """三段式文件名：序号-歌手-专辑-歌曲名"""
    f = tmp_path / "01 - 周杰伦-范特西-简单爱.mp3"
    result = parse_filename(f)
    assert result['track'] == '01'
    assert result['artist'] == '周杰伦'
    assert result['album'] == '范特西'
    assert result['title'] == '简单爱'


def test_parse_filename_two_parts(tmp_path):
    """两段式文件名：歌手-歌曲名"""
    f = tmp_path / "周杰伦-简单爱.mp3"
    result = parse_filename(f)
    assert result['track'] == ''
    assert result['artist'] == '周杰伦'
    assert result['title'] == '简单爱'


def test_parse_filename_one_part(tmp_path):
    """单段文件名：仅歌曲名"""
    f = tmp_path / "简单爱.mp3"
    result = parse_filename(f)
    assert result['track'] == ''
    assert result['title'] == '简单爱'


def test_parse_filename_no_track_prefix(tmp_path):
    """无序号前缀的三段文件名"""
    f = tmp_path / "周杰伦-范特西-简单爱.mp3"
    result = parse_filename(f)
    assert result['track'] == ''
    assert result['artist'] == '周杰伦'
    assert result['album'] == '范特西'
    assert result['title'] == '简单爱'


def test_parse_filename_dot_separator(tmp_path):
    """点号分隔的序号前缀"""
    f = tmp_path / "01. 简单爱.mp3"
    result = parse_filename(f)
    assert result['track'] == '01'
    assert result['title'] == '简单爱'


def test_parse_filename_underscore_separator(tmp_path):
    """下划线分隔的序号前缀"""
    f = tmp_path / "01_简单爱.mp3"
    result = parse_filename(f)
    assert result['track'] == '01'
    assert result['title'] == '简单爱'


def test_parse_filename_flac_extension(tmp_path):
    """FLAC 扩展名文件"""
    f = tmp_path / "02 - 周杰伦-范特西-东风破.flac"
    result = parse_filename(f)
    assert result['track'] == '02'
    assert result['artist'] == '周杰伦'
    assert result['album'] == '范特西'
    assert result['title'] == '东风破'


def test_parse_filename_strips_whitespace(tmp_path):
    """文件名中的空格应被正确处理"""
    f = tmp_path / "01 - 周杰伦 - 范特西 - 简单爱.mp3"
    result = parse_filename(f)
    assert result['track'] == '01'
    assert result['artist'] == '周杰伦'
    assert result['album'] == '范特西'
    assert result['title'] == '简单爱'


# ============================================================
# infer_from_directory
# ============================================================
def test_infer_from_directory_artist_and_album():
    """歌手/专辑/歌曲 结构：应推断出歌手和专辑"""
    f = Path("/music/周杰伦/范特西/简单爱.mp3")
    result = infer_from_directory(f)
    assert result.get('artist') == '周杰伦'
    assert result.get('album') == '范特西'


def test_infer_from_directory_artist_only():
    """歌手/歌曲 结构（父目录被 music 跳过）：应只推断出歌手"""
    f = Path("/music/周杰伦/简单爱.mp3")
    result = infer_from_directory(f)
    assert result.get('artist') == '周杰伦'
    assert 'album' not in result


def test_infer_from_directory_skips_cd_number():
    """应跳过 CD1 等目录名"""
    f = Path("/music/周杰伦/CD1/简单爱.mp3")
    result = infer_from_directory(f)
    # CD1 被跳过，周杰伦和 music(跳过) -> 仅一个有效父目录
    assert result.get('artist') == '周杰伦'
    assert 'album' not in result


def test_infer_from_directory_skips_disc():
    """应跳过 Disc 1 等目录名"""
    f = Path("/music/周杰伦/Disc 1/简单爱.mp3")
    result = infer_from_directory(f)
    assert result.get('artist') == '周杰伦'
    assert 'album' not in result


def test_infer_from_directory_skips_music2():
    """应跳过 music2 目录"""
    f = Path("/music2/周杰伦/范特西/简单爱.mp3")
    result = infer_from_directory(f)
    assert result.get('artist') == '周杰伦'
    assert result.get('album') == '范特西'


def test_infer_from_directory_skips_number_only():
    """应跳过纯数字目录名"""
    f = Path("/music/周杰伦/2023/简单爱.mp3")
    result = infer_from_directory(f)
    # 2023 被跳过（纯数字），周杰伦和 music(跳过)
    assert result.get('artist') == '周杰伦'
    assert 'album' not in result


def test_infer_from_directory_deep_nested():
    """深层嵌套目录也应正确推断"""
    f = Path("/music/周杰伦/范特西/简单爱.mp3")
    result = infer_from_directory(f)
    assert result.get('artist') == '周杰伦'
    assert result.get('album') == '范特西'


# ============================================================
# build_target_path
# ============================================================
def test_build_target_path_album():
    """专辑路径构建：歌手/年份-专辑/序号-歌曲名-歌手-专辑"""
    meta = {
        'title_display': '简单爱',
        'artist': '周杰伦',
        'album': '范特西',
        'year': '2001',
        'track': '01',
    }
    path = build_target_path(meta, is_singleton=False, artist_canonical='周杰伦')
    assert path == '周杰伦/2001-范特西/01-简单爱-周杰伦-范特西'


def test_build_target_path_singleton():
    """单曲路径构建：歌手/其他/序号-歌曲名-歌手-专辑"""
    meta = {
        'title_display': '简单爱',
        'artist': '周杰伦',
        'album': '范特西',
        'track': '01',
    }
    path = build_target_path(meta, is_singleton=True, artist_canonical='周杰伦')
    assert path == '周杰伦/其他/01-简单爱-周杰伦-范特西'


def test_build_target_path_album_no_year():
    """专辑无年份时使用 '未知'"""
    meta = {
        'title_display': '简单爱',
        'artist': '周杰伦',
        'album': '范特西',
        'track': '01',
    }
    path = build_target_path(meta, is_singleton=False, artist_canonical='周杰伦')
    assert path == '周杰伦/未知-范特西/01-简单爱-周杰伦-范特西'


def test_build_target_path_album_no_track():
    """无序号时文件名不带序号前缀"""
    meta = {
        'title_display': '简单爱',
        'artist': '周杰伦',
        'album': '范特西',
        'year': '2001',
        'track': '',
    }
    path = build_target_path(meta, is_singleton=False, artist_canonical='周杰伦')
    assert path == '周杰伦/2001-范特西/简单爱-周杰伦-范特西'


def test_build_target_path_singleton_no_track():
    """单曲无序号"""
    meta = {
        'title_display': '简单爱',
        'artist': '周杰伦',
        'album': '范特西',
        'track': '',
    }
    path = build_target_path(meta, is_singleton=True, artist_canonical='周杰伦')
    assert path == '周杰伦/其他/简单爱-周杰伦-范特西'


def test_build_target_path_album_no_album():
    """专辑无专辑名时使用 '未知专辑'"""
    meta = {
        'title_display': '简单爱',
        'artist': '周杰伦',
        'album': '',
        'year': '2001',
        'track': '01',
    }
    path = build_target_path(meta, is_singleton=False, artist_canonical='周杰伦')
    # sanitize('') 返回 '未知'，但 album 在 build_target_path 中:
    # album = sanitize(meta.get('album')) or '' -> sanitize('') = '未知' -> '未知' or '' = '未知'
    # album_part = '2001-未知' (因为 album='未知' 不是 falsy)
    # filename 中 album 也为 '未知'
    assert path == '周杰伦/2001-未知/01-简单爱-周杰伦-未知'


def test_build_target_path_artist_canonical_differs():
    """artist_canonical 与 meta['artist'] 不同时使用 canonical 作为目录名和文件名中的歌手"""
    meta = {
        'title_display': '简单爱',
        'artist': 'Jay Chou',
        'album': '范特西',
        'year': '2001',
        'track': '01',
    }
    path = build_target_path(meta, is_singleton=False, artist_canonical='周杰伦')
    # 目录名用 canonical，文件名中也用 canonical（专辑歌曲统一用专辑歌手）
    assert path == '周杰伦/2001-范特西/01-简单爱-周杰伦-范特西'


def test_build_target_path_feat_artist():
    """专辑中嘉宾歌曲：实唱歌手与专辑歌手不同时追加到文件名末尾"""
    meta = {
        'title_display': '彩虹',
        'artist': '江语晨',
        'album': '不能说的秘密',
        'year': '2007',
        'track': '05',
        'dir_artist': '周杰伦',
    }
    path = build_target_path(meta, is_singleton=False, artist_canonical='周杰伦-Jay Chou')
    # 目录用专辑歌手，文件名中专辑歌手+实唱歌手
    assert path == '周杰伦-Jay Chou/2007-不能说的秘密/05-彩虹-周杰伦-Jay Chou-不能说的秘密-江语晨'


def test_build_target_path_same_artist_no_feat():
    """专辑中歌手与专辑歌手相同时不追加实唱歌手"""
    meta = {
        'title_display': '简单爱',
        'artist': '周杰伦',
        'album': '范特西',
        'year': '2001',
        'track': '01',
        'dir_artist': '周杰伦',
    }
    path = build_target_path(meta, is_singleton=False, artist_canonical='周杰伦-Jay Chou')
    # 歌手相同，不追加实唱歌手
    assert path == '周杰伦-Jay Chou/2001-范特西/01-简单爱-周杰伦-Jay Chou-范特西'


def test_build_target_path_sanitizes_illegal_chars():
    """路径中的非法字符应被清理"""
    meta = {
        'title_display': 'A/B:C',
        'artist': ' Artist? ',
        'album': 'Album*',
        'year': '2020',
        'track': '01',
    }
    path = build_target_path(meta, is_singleton=False, artist_canonical=' Artist? ')
    # 非法字符被替换为 _，首尾空格被去除
    assert '/' not in path.split('_')[0]  # 路径分隔符 / 保留，非法 / 被替换
    assert '?' not in path
    assert '*' not in path


# ============================================================
# file_hash
# ============================================================
def test_file_hash_empty_file(tmp_path):
    """空文件应返回 None"""
    f = tmp_path / "empty.mp3"
    f.write_bytes(b'')
    assert file_hash(f) is None


def test_file_hash_small_file(tmp_path):
    """小于 1KB 的文件应返回 None"""
    f = tmp_path / "small.mp3"
    f.write_bytes(b'small content')  # 12 bytes < 1024
    assert file_hash(f) is None


def test_file_hash_normal_file(tmp_path):
    """正常文件（>= 1KB）应返回哈希字符串"""
    f = tmp_path / "normal.mp3"
    f.write_bytes(b'a' * 2048)  # 2KB
    h = file_hash(f)
    assert h is not None
    assert isinstance(h, str)
    assert len(h) == 32  # MD5 hex digest 长度


def test_file_hash_consistency(tmp_path):
    """相同内容的文件应返回相同哈希"""
    f1 = tmp_path / "file1.mp3"
    f2 = tmp_path / "file2.mp3"
    content = b'x' * 2048
    f1.write_bytes(content)
    f2.write_bytes(content)
    assert file_hash(f1) == file_hash(f2)


def test_file_hash_different_content(tmp_path):
    """不同内容的文件应返回不同哈希"""
    f1 = tmp_path / "file1.mp3"
    f2 = tmp_path / "file2.mp3"
    f1.write_bytes(b'a' * 2048)
    f2.write_bytes(b'b' * 2048)
    assert file_hash(f1) != file_hash(f2)


def test_file_hash_nonexistent_file():
    """不存在的文件应返回 None"""
    f = Path("/nonexistent/path/file.mp3")
    assert file_hash(f) is None


def test_file_hash_sha256_algorithm(tmp_path):
    """支持指定其他哈希算法"""
    f = tmp_path / "test.mp3"
    f.write_bytes(b'a' * 2048)
    h = file_hash(f, algorithm='sha256')
    assert h is not None
    assert isinstance(h, str)
    assert len(h) == 64  # SHA-256 hex digest 长度
