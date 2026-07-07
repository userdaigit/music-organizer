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

# 繁简转换器（延迟初始化，避免未安装 opencc 时报错）
_t2s_converter = None


def get_t2s_converter():
    """获取繁简转换器（延迟初始化）"""
    global _t2s_converter
    if _t2s_converter is None:
        try:
            from opencc import OpenCC
            _t2s_converter = OpenCC('t2s')
        except ImportError:
            _t2s_converter = False  # 标记为不可用
    return _t2s_converter


def convert_t2s(text):
    """
    繁体中文转简体中文。
    如果 opencc 未安装，返回原文（不做转换）。
    """
    if not text:
        return text
    converter = get_t2s_converter()
    if converter is False:
        return text
    return converter.convert(text)


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
    latin_ext_count = 0  # Latin-1 Supplement (0x80-0xFF) - 中文误读常见
    for ch in text:
        cat = unicodedata.category(ch)
        cp = ord(ch)
        # CJK 统一汉字范围
        if 0x4e00 <= cp <= 0x9fff or 0x3400 <= cp <= 0x4dbf:
            cjk_count += 1
        # Latin-1 Supplement (0x80-0xFF) - 中文GBK/Big5误读常见
        elif 0x80 <= cp <= 0xff:
            latin_ext_count += 1

    # 如果有大量 Latin-1 Supplement 字符且没有对应的合理上下文
    if latin_ext_count > 2 and cjk_count == 0:
        return True

    # CJK 和 Latin-1 Supplement 混合（不自然）
    if cjk_count > 0 and latin_ext_count >= cjk_count:
        return True

    # 有 CJK 字符但也存在 Latin-1 Supplement 乱码片段（至少 2 个连续）
    if cjk_count > 0 and latin_ext_count >= 2:
        return True

    return False


def try_fix_encoding(text, original_encoding='utf-8'):
    """
    尝试修复乱码文本。
    策略1：整段修复——将文本按 Latin-1 编码回字节，再用中文编码解码。
    策略2：逐段修复——当文本混合了正常中文和乱码时，只修复乱码片段。
    """
    if not text or not is_garbled(text):
        return text, False

    # 策略1：整段修复（纯乱码文本，无 CJK 字符）
    # 尝试所有编码，选择 CJK 字符最多的结果
    best_result = None
    best_cjk = 0
    for src_enc in ['latin-1', 'cp1252']:
        try:
            raw_bytes = text.encode(src_enc)
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        for dst_enc in CHINESE_ENCODINGS:
            try:
                decoded = raw_bytes.decode(dst_enc)
                cjk = sum(1 for ch in decoded if 0x4e00 <= ord(ch) <= 0x9fff)
                if cjk > best_cjk:
                    best_cjk = cjk
                    best_result = decoded
            except (UnicodeDecodeError, UnicodeEncodeError):
                continue
    if best_result and best_cjk > 0:
        return best_result, True

    # 策略3：逐段修复——混合文本（正常中文 + 乱码片段）
    # 乱码段 = 以 Latin-1 Supplement 字符为主，可夹杂 ASCII 字母/数字
    # （Big5 编码第二字节可以是 ASCII 0x40-0x7E，如 O=0x4F, K=0x4B）
    fixed_parts = []
    any_fixed = False
    i = 0
    while i < len(text):
        # 检测乱码段起点：Latin-1 Supplement 字符
        if 0x80 <= ord(text[i]) <= 0xff:
            j = i
            latin_count = 0
            while j < len(text):
                cp = ord(text[j])
                if 0x80 <= cp <= 0xff:
                    # Latin-1 Supplement 字符，属于乱码段
                    latin_count += 1
                    j += 1
                elif (0x41 <= cp <= 0x7a or 0x30 <= cp <= 0x39):
                    # ASCII 字母/数字：如果前后有 Latin-1 Supplement 字符则属于乱码段
                    prev_is_latin = j > i and 0x80 <= ord(text[j - 1]) <= 0xff
                    next_is_latin = j + 1 < len(text) and 0x80 <= ord(text[j + 1]) <= 0xff
                    if prev_is_latin or next_is_latin:
                        j += 1
                    else:
                        break
                else:
                    break
            # text[i:j] 是一个乱码段（至少 2 个 Latin-1 Supplement 字符才尝试修复）
            garbled_segment = text[i:j]
            if latin_count >= 2:
                fixed_segment = _fix_garbled_segment(garbled_segment)
                if fixed_segment:
                    fixed_parts.append(fixed_segment)
                    any_fixed = True
                else:
                    fixed_parts.append(garbled_segment)
            else:
                fixed_parts.append(garbled_segment)
            i = j
        else:
            fixed_parts.append(text[i])
            i += 1

    if any_fixed:
        result = ''.join(fixed_parts)
        return result, True

    # 策略4：直接 UTF-8 字节尝试中文编码解码
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


def _fix_garbled_segment(segment):
    """
    修复单个乱码片段（纯 Latin-1 Supplement 字符段）。
    尝试用 Latin-1/CP1252 编码回字节，再用中文编码解码。
    如果多个编码都能解码，选择 CJK 字符最多的结果。
    返回修复后的字符串，失败返回 None。
    """
    best_result = None
    best_cjk_count = 0

    for src_enc in ['latin-1', 'cp1252']:
        try:
            raw_bytes = segment.encode(src_enc)
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        for dst_enc in CHINESE_ENCODINGS:
            try:
                decoded = raw_bytes.decode(dst_enc)
                cjk = sum(1 for ch in decoded if 0x4e00 <= ord(ch) <= 0x9fff)
                if cjk > best_cjk_count:
                    best_cjk_count = cjk
                    best_result = decoded
            except (UnicodeDecodeError, UnicodeDecodeError):
                continue
    return best_result


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
    """
    统一文本编码：NFC 规范化 + 繁体转简体 + 清理控制字符。
    """
    if not text:
        return text
    # Unicode NFC 规范化（合并组合字符）
    text = unicodedata.normalize('NFC', text)
    # 去除 BOM
    text = text.replace('\ufeff', '')
    # 去除控制字符（保留换行和制表符）
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
    # 繁体转简体
    text = convert_t2s(text)
    return text.strip()