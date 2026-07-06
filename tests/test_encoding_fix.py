# -*- coding: utf-8 -*-
"""
test_encoding_fix.py
测试 encoding_fix.py 中的编码检测与修复函数。

注意：这些函数需要 import encoding_fix 模块。
"""

from encoding_fix import is_garbled, try_fix_encoding, normalize_text, fix_tags_encoding


# ============================================================
# is_garbled
# ============================================================
def test_is_garbled_empty_string():
    """空字符串不应被判为乱码"""
    assert is_garbled('') is False


def test_is_garbled_none():
    """None 不应被判为乱码"""
    assert is_garbled(None) is False


def test_is_garbled_normal_chinese():
    """正常中文不应被判为乱码"""
    assert is_garbled('周杰伦') is False
    assert is_garbled('范特西专辑') is False


def test_is_garbled_normal_english():
    """正常英文不应被判为乱码"""
    assert is_garbled('Hello World') is False
    assert is_garbled('Jay Chou') is False


def test_is_garbled_mixed_normal():
    """正常中英混合不应被判为乱码"""
    assert is_garbled('周杰伦 Jay Chou') is False


def test_is_garbled_latin1_misread_chinese():
    """GBK 编码的中文被当作 Latin-1 读取时应检测为乱码"""
    # 模拟乱码产生过程：中文 -> GBK 字节 -> 按 Latin-1 解码
    chinese = "周杰伦"
    gbk_bytes = chinese.encode('gbk')
    garbled = gbk_bytes.decode('latin-1')
    assert is_garbled(garbled) is True


def test_is_garbled_replacement_char():
    """包含替换字符 \\ufffd 应判为乱码"""
    assert is_garbled('test\ufffd') is True
    assert is_garbled('音乐\ufffd标签') is True


def test_is_garbled_many_latin_ext():
    """大量 Latin-1 Supplement 字符（无 CJK）应判为乱码"""
    # Latin-1 Supplement 范围: U+00C0 - U+00FF
    garbled_text = ''.join(chr(cp) for cp in range(0xC0, 0xD0))
    assert is_garbled(garbled_text) is True


# ============================================================
# try_fix_encoding
# ============================================================
def test_try_fix_encoding_normal_text():
    """正常文本不应被修改，was_fixed 为 False"""
    text = "周杰伦"
    fixed, was_fixed = try_fix_encoding(text)
    assert fixed == "周杰伦"
    assert was_fixed is False


def test_try_fix_encoding_empty():
    """空文本不应被修改"""
    fixed, was_fixed = try_fix_encoding('')
    assert fixed == ''
    assert was_fixed is False


def test_try_fix_encoding_none():
    """None 输入应原样返回"""
    fixed, was_fixed = try_fix_encoding(None)
    assert fixed is None
    assert was_fixed is False


def test_try_fix_encoding_gbk_garbled():
    """能修复 GBK 乱码：Latin-1 误读 -> 正确中文"""
    # 构造乱码：中文用 GBK 编码，再被 Latin-1 错误解码
    original = "周杰伦"
    garbled = original.encode('gbk').decode('latin-1')
    fixed, was_fixed = try_fix_encoding(garbled)
    assert was_fixed is True
    assert fixed == original


def test_try_fix_encoding_gb18030_garbled():
    """能修复 GB18030 编码的乱码"""
    original = "青花瓷"
    garbled = original.encode('gb18030').decode('latin-1')
    fixed, was_fixed = try_fix_encoding(garbled)
    assert was_fixed is True
    assert fixed == original


def test_try_fix_encoding_english_unchanged():
    """英文文本不应被修改"""
    text = "Hello World"
    fixed, was_fixed = try_fix_encoding(text)
    assert fixed == "Hello World"
    assert was_fixed is False


# ============================================================
# normalize_text
# ============================================================
def test_normalize_text_empty():
    """空字符串应原样返回"""
    assert normalize_text('') == ''


def test_normalize_text_none():
    """None 应原样返回"""
    assert normalize_text(None) is None


def test_normalize_text_strips_whitespace():
    """应去除首尾空白（strip 去除所有首尾空白字符，包括 \\t 和 \\n）"""
    assert normalize_text('  hello  ') == 'hello'
    assert normalize_text('\thello\n') == 'hello'  # \t 和 \n 也属于空白，被 strip 去除


def test_normalize_text_normal_chinese():
    """正常中文应保持不变"""
    assert normalize_text('周杰伦') == '周杰伦'


def test_normalize_text_removes_bom():
    """应去除 BOM 字符 (\\ufeff)"""
    assert normalize_text('\ufeffhello') == 'hello'
    assert normalize_text('\ufeff') == ''


def test_normalize_text_removes_control_chars():
    """应去除控制字符（保留换行 \\n 和制表符 \\t）"""
    # \x00 (NULL) 应被移除
    assert normalize_text('hello\x00world') == 'helloworld'
    # \x01 - \x08 应被移除
    assert normalize_text('a\x01b\x02c') == 'abc'
    # \x0b (垂直制表) 应被移除
    assert normalize_text('a\x0bb') == 'ab'
    # \x0c (换页) 应被移除
    assert normalize_text('a\x0cb') == 'ab'
    # \n (换行) 应保留
    assert normalize_text('hello\nworld') == 'hello\nworld'
    # \t (制表符) 应保留
    assert normalize_text('hello\tworld') == 'hello\tworld'


def test_normalize_text_nfc():
    """应执行 NFC 规范化：分解形式 -> 组合形式"""
    # 'é' 的分解形式: e + U+0301 (combining acute accent)
    decomposed = 'e\u0301'
    normalized = normalize_text(decomposed)
    # NFC 后应为组合形式 U+00E9
    assert normalized == '\u00e9'
    assert len(normalized) == 1  # 组合形式长度为1


def test_normalize_text_already_nfc():
    """已经是 NFC 形式的文本不应改变"""
    text = 'café'
    assert normalize_text(text) == 'café'


# ============================================================
# fix_tags_encoding (额外覆盖)
# ============================================================
def test_fix_tags_encoding_normal():
    """正常标签不应被修改"""
    tags = {'title': '简单爱', 'artist': '周杰伦'}
    fixed, changed = fix_tags_encoding(tags)
    assert fixed == tags
    assert changed is False


def test_fix_tags_encoding_garbled():
    """乱码标签应被修复"""
    garbled_title = "周杰伦".encode('gbk').decode('latin-1')
    tags = {'title': garbled_title}
    fixed, changed = fix_tags_encoding(tags)
    assert changed is True
    assert fixed['title'] == "周杰伦"


def test_fix_tags_encoding_list_values():
    """列表值中的乱码也应被修复"""
    garbled = "范特西".encode('gbk').decode('latin-1')
    tags = {'album': [garbled]}
    fixed, changed = fix_tags_encoding(tags)
    assert changed is True
    assert fixed['album'][0] == "范特西"


def test_fix_tags_encoding_non_string_values():
    """非字符串值应原样保留"""
    tags = {'year': 2001, 'tracknumber': 5}
    fixed, changed = fix_tags_encoding(tags)
    assert fixed == tags
    assert changed is False
