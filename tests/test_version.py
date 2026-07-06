# -*- coding: utf-8 -*-
"""
test_version.py
测试 version.py 中的版本号和 User-Agent 配置。
"""

from version import __version__, MB_USER_AGENT, MB_USER_AGENT_VERSION, REPO_URL


# ============================================================
# __version__
# ============================================================
def test_version_is_string():
    """__version__ 应为字符串类型"""
    assert isinstance(__version__, str)


def test_version_non_empty():
    """__version__ 不应为空字符串"""
    assert len(__version__) > 0


def test_version_format():
    """__version__ 应符合语义化版本号格式（X.Y.Z）"""
    parts = __version__.split('.')
    assert len(parts) >= 3
    for part in parts:
        assert part.isdigit(), f"版本号各段应为数字，但得到: {part}"


# ============================================================
# MB_USER_AGENT
# ============================================================
def test_mb_user_agent_contains_version():
    """MB_USER_AGENT 应包含版本号"""
    assert __version__ in MB_USER_AGENT


def test_mb_user_agent_contains_repo_url():
    """MB_USER_AGENT 应包含仓库 URL"""
    assert REPO_URL in MB_USER_AGENT


def test_mb_user_agent_version_string():
    """MB_USER_AGENT_VERSION 应包含版本号和程序名"""
    assert __version__ in MB_USER_AGENT_VERSION
    assert 'MusicOrganizer' in MB_USER_AGENT_VERSION


def test_mb_user_agent_is_string():
    """MB_USER_AGENT 应为字符串"""
    assert isinstance(MB_USER_AGENT, str)
    assert len(MB_USER_AGENT) > 0


def test_repo_url_is_valid_url():
    """REPO_URL 应为有效的 GitHub URL"""
    assert REPO_URL.startswith('https://github.com/')
