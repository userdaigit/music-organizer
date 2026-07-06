# -*- coding: utf-8 -*-
"""
进度条模块
=============================================
提供 pip 风格的终端进度条，支持百分比显示。
不计算 ETA（预计剩余时间），因为文件大小、网络速度差异大，估算不准确。
"""

import sys
import time


class ProgressBar:
    """
    pip 风格进度条。

    示例输出:
      [扫描文件]   45% |============>               | 450/1000

    用法:
        bar = ProgressBar("扫描文件", total=1000)
        for i in range(1000):
            bar.update(i + 1)
        bar.finish()
    """

    # 进度条总宽度（字符数）
    BAR_WIDTH = 30

    def __init__(self, description, total, unit=""):
        """
        初始化进度条。

        Args:
            description: 步骤描述，如 "扫描文件"
            total:       总项目数
            unit:        单位描述，如 "首"、"个"（可选）
        """
        self.desc = description
        self.total = max(total, 1)  # 防止除零
        self.unit = unit
        self.current = 0
        self.start_time = time.time()
        self._last_print_len = 0  # 上次输出的字符数，用于清除残留

    def update(self, current):
        """更新进度并刷新显示"""
        self.current = min(current, self.total)
        self._render()

    def _render(self):
        """渲染进度条到终端"""
        percent = self.current / self.total
        filled = int(self.BAR_WIDTH * percent)
        bar_str = "=" * filled + ">" + " " * (self.BAR_WIDTH - filled - 1)
        if self.BAR_WIDTH == filled:
            bar_str = "=" * self.BAR_WIDTH  # 100% 时不显示箭头

        percent_str = f"{percent * 100:5.1f}%"
        count_str = f"{self.current}/{self.total}"
        if self.unit:
            count_str += self.unit

        line = f"\r[{self.desc}] {percent_str} |{bar_str}| {count_str}"

        # 清除上次输出残留（防止短行覆盖长行时尾巴残留）
        if self._last_print_len > len(line):
            line += " " * (self._last_print_len - len(line))

        sys.stdout.write(line)
        sys.stdout.flush()
        self._last_print_len = len(line)

    def finish(self):
        """完成进度条，换行"""
        self.current = self.total
        self._render()
        elapsed = time.time() - self.start_time
        sys.stdout.write(f"  完成 ({elapsed:.1f}s)\n")
        sys.stdout.flush()

    def set_description(self, desc):
        """更新描述文字"""
        self.desc = desc


def progress_iter(description, iterable, total=None, unit=""):
    """
    带进度条的迭代器包装。

    用法:
        for item in progress_iter("提取元数据", file_list, unit="首"):
            process(item)

    Args:
        description: 步骤描述
        iterable:    可迭代对象
        total:       总数（不知道时传 None，尝试从 len 获取）
        unit:        单位
    """
    if total is None:
        try:
            total = len(iterable)
        except TypeError:
            total = None

    if total is None or total == 0:
        # 无法获知总数，逐个输出不显示百分比
        count = 0
        for item in iterable:
            count += 1
            sys.stdout.write(f"\r[{description}] {count} 项...")
            sys.stdout.flush()
            yield item
        sys.stdout.write(f"\r[{description}] 完成 ({count} 项)\n")
        sys.stdout.flush()
    else:
        bar = ProgressBar(description, total, unit)
        for i, item in enumerate(iterable):
            yield item
            bar.update(i + 1)
        bar.finish()
