# -*- coding: utf-8 -*-
"""
test_progress.py
测试 progress.py 中的 ProgressBar 类和 progress_iter 函数。
"""

from progress import ProgressBar, progress_iter


# ============================================================
# ProgressBar 初始化
# ============================================================
def test_progressbar_init_basic():
    """ProgressBar 初始化应正确设置属性"""
    bar = ProgressBar("扫描文件", 100)
    assert bar.desc == "扫描文件"
    assert bar.total == 100
    assert bar.current == 0
    assert bar.unit == ""


def test_progressbar_init_with_unit():
    """带单位的 ProgressBar 初始化"""
    bar = ProgressBar("提取元数据", 50, unit="首")
    assert bar.desc == "提取元数据"
    assert bar.total == 50
    assert bar.unit == "首"


def test_progressbar_init_zero_total():
    """total=0 时不应报错，内部使用 max(total, 1) 防止除零"""
    bar = ProgressBar("测试", 0)
    assert bar.total == 1  # max(0, 1) = 1


def test_progressbar_init_negative_total():
    """负数 total 时也应安全处理"""
    bar = ProgressBar("测试", -5)
    assert bar.total == 1  # max(-5, 1) = 1


# ============================================================
# ProgressBar update
# ============================================================
def test_progressbar_update():
    """update 应正确更新 current 值"""
    bar = ProgressBar("测试", 100, unit="首")
    bar.update(50)
    assert bar.current == 50


def test_progressbar_update_zero():
    """update(0) 应正常工作"""
    bar = ProgressBar("测试", 100)
    bar.update(0)
    assert bar.current == 0


def test_progressbar_update_exceeds_total():
    """update 超过 total 时应被限制在 total"""
    bar = ProgressBar("测试", 10)
    bar.update(20)
    assert bar.current == 10  # min(20, 10) = 10


def test_progressbar_update_full():
    """update 到 total 应正常"""
    bar = ProgressBar("测试", 100)
    bar.update(100)
    assert bar.current == 100


# ============================================================
# ProgressBar finish
# ============================================================
def test_progressbar_finish(capsys):
    """finish 应输出完成信息并换行"""
    bar = ProgressBar("测试", 10)
    bar.update(5)
    bar.finish()
    captured = capsys.readouterr()
    assert "完成" in captured.out
    assert captured.out.endswith("\n")


def test_progressbar_finish_sets_current_to_total(capsys):
    """finish 应将 current 设为 total"""
    bar = ProgressBar("测试", 100)
    bar.update(30)
    bar.finish()
    assert bar.current == 100


# ============================================================
# ProgressBar set_description
# ============================================================
def test_progressbar_set_description():
    """set_description 应更新描述文字"""
    bar = ProgressBar("旧描述", 100)
    bar.set_description("新描述")
    assert bar.desc == "新描述"


# ============================================================
# ProgressBar 渲染不报错
# ============================================================
def test_progressbar_render_no_error(capsys):
    """完整 update + finish 流程不应抛出异常"""
    bar = ProgressBar("扫描", 5, unit="个")
    for i in range(1, 6):
        bar.update(i)
    bar.finish()
    captured = capsys.readouterr()
    assert "扫描" in captured.out


def test_progressbar_zero_total_update_finish(capsys):
    """total=0 时 update 和 finish 也不应报错"""
    bar = ProgressBar("空任务", 0)
    bar.update(1)
    bar.finish()
    captured = capsys.readouterr()
    assert "完成" in captured.out


# ============================================================
# progress_iter
# ============================================================
def test_progress_iter_basic():
    """progress_iter 应正确迭代所有元素"""
    items = list(range(5))
    result = list(progress_iter("迭代测试", items))
    assert result == items


def test_progress_iter_preserves_items():
    """progress_iter 应保留原始元素值"""
    items = ["apple", "banana", "cherry"]
    result = list(progress_iter("水果迭代", items))
    assert result == ["apple", "banana", "cherry"]


def test_progress_iter_empty(capsys):
    """空迭代器不应报错"""
    result = list(progress_iter("空迭代", []))
    assert result == []


def test_progress_iter_with_total(capsys):
    """显式指定 total 时应正常工作"""
    items = list(range(3))
    result = list(progress_iter("显式总数", items, total=3, unit="项"))
    assert result == items
    captured = capsys.readouterr()
    assert "显式总数" in captured.out


def test_progress_iter_zero_total(capsys):
    """total=0 时不报错，走无百分比分支"""
    items = list(range(3))
    result = list(progress_iter("零总数", items, total=0))
    assert result == items


def test_progress_iter_with_unit(capsys):
    """带单位的迭代应正常完成"""
    items = list(range(3))
    result = list(progress_iter("带单位", items, unit="首"))
    assert result == items
