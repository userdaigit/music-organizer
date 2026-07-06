# -*- coding: utf-8 -*-
"""
pytest 全局配置
将 github-release 源码目录加入 sys.path，使各测试文件可以直接 import 模块。
"""

import sys
from pathlib import Path

# conftest.py 位于 tests/ 目录，其父目录即为 github-release/ 源码目录
SOURCE_DIR = str(Path(__file__).resolve().parent.parent)

if SOURCE_DIR not in sys.path:
    sys.path.insert(0, SOURCE_DIR)
