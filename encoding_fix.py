#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
编码修复模块
=============================================
检测并修复音乐标签和文件名中的乱码。
常见问题：GBK/GB18030 编码的 ID3v1 标签被当作 UTF-8 读取，产生乱码。

参考:
  - python-mutagen 处理 GBK 编码:
    https://blog.51cto.com/walkerqt/2054425
  - convmv 文件名编码转换:
    http://yysfire.github.io/linux/rhythmbox-garbled.html
"""

import re
import unicodedata


# 常见中文编码（按优先级尝试）
CHINESE_ENCODINGS = ['gb18030', 'gbk', 'gb2312', 'big5']

# 乱码特征字符（UTF-8 误读 GBK 时常见的替换字符）
GARBLED_INDICATORS = re.compile(r'[\ufffd\x80-\xff\u00c0-\u00ff]')


def is_garbled(text):
    """
    检测字符串是否可能是乱码。
    判断依据：
    1. 包含替换字符 \ufffd
    2. 连续的拉丁扩展字符（中文被误读为 ISO-8859-1）
    3. 文本中 CJK 字符与拉丁扩展字符混合（不自然）
    """
    if not text:
        return False

    # 包含替换字符
    if '\ufffd' in text:
        return True

    # 统计字符类型
    cjk_count = 0
    latin_ext_count = 0  # Latin Extended / Supplement (中文误读常见)
    for ch in text:
        cat = unicodedata.category(ch)
        cp = ord(ch)
        # CJK 统一汉字范围
        if 0x4e00 <= cp <= 0x9fff or 0x3400 <= cp <= 0x4dbf:
            cjk_count += 1
        # Latin-1 Supplement (À-ÿ) - 中文GBK误读常见
        elif 0xc0 <= cp <= 0xff:
            latin_ext_count += 1

    # 如果有大量 Latin-1 Supplement 字符且没有对应的合理上下文
    if latin_ext_count > 2 and cjk_count == 0:
        return True

    # CJK 和 Latin-1 Supplement 混合（不自然）
    if cjk_count > 0 and latin_ext_count >= cjk_count:
        return True

    return False


def try_fix_encoding(text, original_encoding='utf-8'):
    """
    尝试修复乱码文本。
    策略：将文本按 ISO-8859-1/Latin-1 编码回字节，再用中文编码解码。
    """
    if not text or not is_garbled(text):
        return text, False

    # 策略1：UTF-8 -> Latin-1 字节 -> GBK/GB18030
    try:
        raw_bytes = text.encode('latin-1')
        for enc in CHINESE_ENCODINGS:
            try:
                decoded = raw_bytes.decode(enc)
                # 验证解码结果是否合理（包含 CJK 字符）
                if _is_valid_chinese_text(decoded):
                    return decoded, True
            except (UnicodeDecodeError, UnicodeEncodeError):
                continue
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass

    # 策略2：UTF-8 -> CP1252 字节 -> GBK/GB18030
    try:
        raw_bytes = text.encode('cp1252')
        for enc in CHINESE_ENCODINGS:
            try:
                decoded = raw_bytes.decode(enc)
                if _is_valid_chinese_text(decoded):
                    return decoded, True
            except (UnicodeDecodeError, UnicodeEncodeError):
                continue
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass

    # 策略3：直接尝试不同编码间的转换
    try:
        raw_bytes = text.encode('utf-8')
        for enc in CHINESE_ENCODINGS:
            try:
                decoded = raw_bytes.decode(enc)
                if _is_valid_chinese_text(decoded):
                    return decoded, True
            except (UnicodeDecodeError, UnicodeDecodeError):
                continue
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass

    return text, False


def _is_valid_chinese_text(text):
    """验证文本是否包含合理的中文内容"""
    if not text:
        return False
    cjk_count = sum(1 for ch in text if 0x4e00 <= ord(ch) <= 0x9fff)
    # 至少有1个中文字符，且中文字符占比合理
    return cjk_count > 0 and cjk_count / len(text) > 0.1


def fix_tags_encoding(tags):
    """
    修复标签字典中所有字符串值的编码。
    返回 (修复后的字典, 是否有修改)
    """
    fixed = {}
    changed = False
    for key, value in tags.items():
        if isinstance(value, str):
            fixed_value, was_fixed = try_fix_encoding(value)
            fixed[key] = fixed_value
            if was_fixed:
                changed = True
        elif isinstance(value, list):
            fixed_list = []
            for item in value:
                if isinstance(item, str):
                    fixed_item, was_fixed = try_fix_encoding(item)
                    fixed_list.append(fixed_item)
                    if was_fixed:
                        changed = True
                else:
                    fixed_list.append(item)
            fixed[key] = fixed_list
        else:
            fixed[key] = value
    return fixed, changed


def normalize_text(text):
    """统一文本编码为 NFC Unicode 规范化形式"""
    if not text:
        return text
    # Unicode NFC 规范化（合并组合字符）
    text = unicodedata.normalize('NFC', text)
    # 去除 BOM
    text = text.replace('\ufeff', '')
    # 去除控制字符（保留换行和制表符）
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
    return text.strip()