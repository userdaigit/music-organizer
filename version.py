# -*- coding: utf-8 -*-
"""
版本号集中管理模块
所有文件统一从此处导入版本号，避免散落多处导致替换遗漏。
"""

__version__ = "1.2.0"

# MusicBrainz User-Agent 中使用的版本标识
MB_USER_AGENT_VERSION = f"MusicOrganizer/{__version__}"

# 仓库地址
REPO_URL = "https://github.com/userdaigit/music-organizer"

# 完整 User-Agent（含联系方式，MusicBrainz 要求）
MB_USER_AGENT = f"{MB_USER_AGENT_VERSION} ({REPO_URL})"
