# -*- coding: utf-8 -*-
"""
test_kugou_scraper.py
测试 kugou_scraper.py 的 KugouScraper 类。

所有 HTTP 请求均通过 unittest.mock.patch 进行 mock，不实际联网。
为避免速率限制导致的真实 sleep，同时 mock 掉 kugou_scraper.time.sleep。
"""

import json
from unittest.mock import patch, MagicMock

from kugou_scraper import KugouScraper


def _mock_response(data):
    """构造 mock HTTP 响应对象，read() 返回 JSON 字节流。"""
    mock = MagicMock()
    mock.read.return_value = json.dumps(data).encode('utf-8')
    return mock


# 正常的酷狗搜索响应（status=1，含 info 列表）
KUGOU_SUCCESS_RESPONSE = {
    "status": 1,
    "data": {
        "info": [
            {
                "songname": "简单爱",
                "singername": "周杰伦",
                "albumname": "范特西",
                "duration": 269,
            },
            {
                "songname": "晴天",
                "singername": "周杰伦",
                "albumname": "叶惠美",
                "duration": 240,
            },
        ]
    },
}

# 空结果响应（status=1 但 info 为空列表）
KUGOU_EMPTY_RESPONSE = {
    "status": 1,
    "data": {"info": []},
}


# ============================================================
# search
# ============================================================
def test_search_success():
    """mock 返回正常搜索结果，验证解析正确"""
    scraper = KugouScraper()
    mock_resp = _mock_response(KUGOU_SUCCESS_RESPONSE)
    with patch('urllib.request.urlopen', return_value=mock_resp), \
         patch('kugou_scraper.time.sleep'):
        results = scraper.search("简单爱 周杰伦")

    assert len(results) == 2
    first = results[0]
    assert first['title'] == "简单爱"
    assert first['artist'] == "周杰伦"
    assert first['album'] == "范特西"
    assert first['duration'] == 269
    assert first['release_date'] == ''


def test_search_no_results():
    """mock 返回空结果，应返回空列表"""
    scraper = KugouScraper()
    mock_resp = _mock_response(KUGOU_EMPTY_RESPONSE)
    with patch('urllib.request.urlopen', return_value=mock_resp), \
         patch('kugou_scraper.time.sleep'):
        results = scraper.search("不存在的歌曲")

    assert results == []


def test_search_network_error():
    """mock 抛出异常，应返回空列表且 _available=False"""
    scraper = KugouScraper()
    with patch('urllib.request.urlopen', side_effect=Exception("network error")), \
         patch('kugou_scraper.time.sleep'):
        results = scraper.search("测试歌曲")

    assert results == []
    assert scraper._available is False


def test_search_cache():
    """同一关键词第二次搜索不发起请求（验证缓存）"""
    scraper = KugouScraper()
    mock_resp = _mock_response(KUGOU_SUCCESS_RESPONSE)
    with patch('urllib.request.urlopen', return_value=mock_resp) as mock_urlopen, \
         patch('kugou_scraper.time.sleep'):
        # 第一次搜索：发起请求
        results1 = scraper.search("简单爱 周杰伦")
        assert len(results1) == 2
        assert mock_urlopen.call_count == 1

        # 第二次搜索同一关键词：应命中缓存，不发起请求
        results2 = scraper.search("简单爱 周杰伦")
        assert results2 == results1
        assert mock_urlopen.call_count == 1  # 仍然是 1，未增加


def test_search_cache_case_insensitive():
    """缓存键忽略大小写和首尾空白，命中同一缓存"""
    scraper = KugouScraper()
    mock_resp = _mock_response(KUGOU_SUCCESS_RESPONSE)
    with patch('urllib.request.urlopen', return_value=mock_resp) as mock_urlopen, \
         patch('kugou_scraper.time.sleep'):
        scraper.search("简单爱 周杰伦")
        # 不同大小写/首尾空白应命中同一缓存键
        scraper.search("  简单爱 周杰伦  ")
        assert mock_urlopen.call_count == 1


# ============================================================
# enrich_metadata
# ============================================================
def test_enrich_metadata_success():
    """有 title+artist，mock 返回结果，验证补全 album"""
    scraper = KugouScraper()
    mock_resp = _mock_response(KUGOU_SUCCESS_RESPONSE)
    meta = {
        'title': '简单爱',
        'artist': '周杰伦',
        # album 缺失
    }
    with patch('urllib.request.urlopen', return_value=mock_resp), \
         patch('kugou_scraper.time.sleep'):
        enriched, changed = scraper.enrich_metadata(meta)

    assert changed is True
    assert enriched['album'] == "范特西"
    assert enriched['title'] == "简单爱"
    assert enriched['artist'] == "周杰伦"


def test_enrich_metadata_no_results():
    """mock 返回空，changed 应为 False"""
    scraper = KugouScraper()
    mock_resp = _mock_response(KUGOU_EMPTY_RESPONSE)
    meta = {
        'title': '简单爱',
        'artist': '周杰伦',
    }
    with patch('urllib.request.urlopen', return_value=mock_resp), \
         patch('kugou_scraper.time.sleep'):
        enriched, changed = scraper.enrich_metadata(meta)

    assert changed is False
    assert enriched == meta


def test_enrich_metadata_skip_unknown():
    """title='未知歌曲' 时不搜索，直接返回"""
    scraper = KugouScraper()
    mock_resp = _mock_response(KUGOU_SUCCESS_RESPONSE)
    meta = {
        'title': '未知歌曲',
        'artist': '未知歌手',
    }
    with patch('urllib.request.urlopen', return_value=mock_resp) as mock_urlopen, \
         patch('kugou_scraper.time.sleep'):
        enriched, changed = scraper.enrich_metadata(meta)

    assert changed is False
    assert enriched == meta
    # 不应发起任何请求
    assert mock_urlopen.call_count == 0


def test_enrich_metadata_empty_title():
    """title 为空时不搜索，直接返回"""
    scraper = KugouScraper()
    mock_resp = _mock_response(KUGOU_SUCCESS_RESPONSE)
    meta = {
        'title': '',
        'artist': '周杰伦',
    }
    with patch('urllib.request.urlopen', return_value=mock_resp) as mock_urlopen, \
         patch('kugou_scraper.time.sleep'):
        enriched, changed = scraper.enrich_metadata(meta)

    assert changed is False
    assert enriched == meta
    assert mock_urlopen.call_count == 0


def test_enrich_metadata_completes_artist():
    """artist 为 '未知歌手' 时应补全歌手"""
    scraper = KugouScraper()
    mock_resp = _mock_response(KUGOU_SUCCESS_RESPONSE)
    meta = {
        'title': '简单爱',
        'artist': '未知歌手',
        'album': '',
    }
    with patch('urllib.request.urlopen', return_value=mock_resp), \
         patch('kugou_scraper.time.sleep'):
        enriched, changed = scraper.enrich_metadata(meta)

    assert changed is True
    assert enriched['artist'] == "周杰伦"
    assert enriched['album'] == "范特西"


# ============================================================
# is_available
# ============================================================
def test_is_available_true():
    """mock 测试请求成功，应返回 True"""
    scraper = KugouScraper()
    mock_resp = _mock_response(KUGOU_SUCCESS_RESPONSE)
    with patch('urllib.request.urlopen', return_value=mock_resp), \
         patch('kugou_scraper.time.sleep'):
        assert scraper.is_available() is True


def test_is_available_false():
    """mock 测试请求失败，应返回 False"""
    scraper = KugouScraper()
    with patch('urllib.request.urlopen', side_effect=Exception("network error")), \
         patch('kugou_scraper.time.sleep'):
        assert scraper.is_available() is False


def test_is_available_uses_cached_status():
    """已检查过 _available 后不再重复请求"""
    scraper = KugouScraper()
    scraper._available = True
    mock_resp = _mock_response(KUGOU_SUCCESS_RESPONSE)
    with patch('urllib.request.urlopen', return_value=mock_resp) as mock_urlopen:
        # _available 已为 True，不应再发请求
        assert scraper.is_available() is True
        assert mock_urlopen.call_count == 0
