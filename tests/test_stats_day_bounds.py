"""stats API 内部纯函数测试"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from app.api.stats import _TZ, _day_bounds


def test_day_bounds_returns_local_midnight() -> None:
    start, end = _day_bounds(date(2026, 5, 19))
    assert start == datetime(2026, 5, 19, 0, 0, tzinfo=_TZ)
    assert end == datetime(2026, 5, 20, 0, 0, tzinfo=_TZ)


def test_day_bounds_span_exactly_24h() -> None:
    start, end = _day_bounds(date(2026, 5, 19))
    assert (end - start) == timedelta(hours=24)


def test_day_bounds_timezone_is_china_standard_time() -> None:
    start, _ = _day_bounds(date(2026, 5, 19))
    assert start.tzinfo == _TZ
    # UTC+8
    assert start.utcoffset() == timedelta(hours=8)


def test_day_bounds_crossing_dst_irrelevant_for_china() -> None:
    # 中国不实行夏令时，跨月跨年都应是固定 24 小时
    start, end = _day_bounds(date(2026, 12, 31))
    assert end - start == timedelta(hours=24)
    assert end.date() == date(2027, 1, 1)
