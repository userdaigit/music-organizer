# -*- coding: utf-8 -*-
"""
test_fingerprint.py
测试 fingerprint.py 中新增的 KEY 检查功能：
  - is_default_key()
  - validate_api_key()

所有网络请求均通过 unittest.mock.patch 进行 mock，不实际联网。
"""

import json
from unittest.mock import patch, MagicMock

import fingerprint
from fingerprint import (
    is_default_key,
    validate_api_key,
    DEFAULT_API_KEY,
    ACOUSTID_API_KEY,
)


def _mock_response(data):
    """构造 mock HTTP 响应对象，read() 返回 JSON 字节流。"""
    mock = MagicMock()
    mock.read.return_value = json.dumps(data).encode('utf-8')
    return mock


# ============================================================
# is_default_key
# ============================================================
def test_is_default_key_default_key():
    """默认 KEY 'lmv7m8k7Fe' 应返回 True"""
    assert is_default_key('lmv7m8k7Fe') is True
    assert is_default_key(DEFAULT_API_KEY) is True


def test_is_default_key_custom_key():
    """自定义 KEY 应返回 False"""
    assert is_default_key('myCustomKey123') is False


def test_is_default_key_empty_string_falls_back():
    """空字符串 KEY（falsy）会回落到模块级 ACOUSTID_API_KEY"""
    # is_default_key 内部使用 `api_key or ACOUSTID_API_KEY`，空串为 falsy，
    # 因此回落到 ACOUSTID_API_KEY（默认即 DEFAULT_API_KEY），返回 True
    with patch.object(fingerprint, 'ACOUSTID_API_KEY', DEFAULT_API_KEY):
        assert is_default_key('') is True
    # 若模块级 KEY 为自定义值，空串应回落到该自定义值，返回 False
    with patch.object(fingerprint, 'ACOUSTID_API_KEY', 'customKey'):
        assert is_default_key('') is False


def test_is_default_key_no_arg_uses_env_default():
    """无参数时应使用模块级 ACOUSTID_API_KEY（默认值），返回 True"""
    # 未设置环境变量时 ACOUSTID_API_KEY == DEFAULT_API_KEY
    with patch.object(fingerprint, 'ACOUSTID_API_KEY', DEFAULT_API_KEY):
        assert is_default_key() is True


def test_is_default_key_no_arg_with_custom_env():
    """无参数但环境变量为自定义 KEY 时（模拟），应返回 False"""
    # 模拟环境变量设置了自定义 KEY（通过 patch 模块级常量）
    with patch.object(fingerprint, 'ACOUSTID_API_KEY', 'envCustomKey'):
        assert is_default_key() is False


# ============================================================
# validate_api_key
# ============================================================
def test_validate_api_key_valid():
    """有效 KEY：mock 返回 {"status": "ok"} 时应返回 True"""
    mock_resp = _mock_response({"status": "ok", "results": []})
    with patch('urllib.request.urlopen', return_value=mock_resp):
        assert validate_api_key('validKey123') is True


def test_validate_api_key_invalid():
    """无效 KEY：mock 返回 error 状态（invalid API key）时应返回 False"""
    mock_resp = _mock_response({
        "status": "error",
        "error": {"message": "invalid API key", "code": 6}
    })
    with patch('urllib.request.urlopen', return_value=mock_resp):
        assert validate_api_key('invalidKey') is False


def test_validate_api_key_network_error():
    """网络错误：mock 抛出异常时应返回 None"""
    with patch('urllib.request.urlopen', side_effect=Exception("network error")):
        assert validate_api_key('someKey') is None


def test_validate_api_key_uses_module_key_when_no_arg():
    """无参数时使用模块级 KEY 发送请求"""
    mock_resp = _mock_response({"status": "ok", "results": []})
    with patch('urllib.request.urlopen', return_value=mock_resp) as mock_urlopen:
        result = validate_api_key()
        assert result is True
        # 确认确实发起了请求
        assert mock_urlopen.call_count == 1
