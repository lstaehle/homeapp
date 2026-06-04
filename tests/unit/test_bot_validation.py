from datetime import date, time, timedelta
from unittest.mock import patch

import pytest

from app.bot import DurationResult, parse_date, parse_duration, parse_time


def test_parse_date_valid():
    assert parse_date("25.12.2026") == date(2026, 12, 25)


def test_parse_date_short_uses_current_year():
    with patch("app.bot.datetime") as mock_dt:
        mock_dt.now.return_value.year = 2026
        result = parse_date("25.12")
    assert result == date(2026, 12, 25)


def test_parse_date_invalid_format():
    with pytest.raises(ValueError):
        parse_date("2026-12-25")


def test_parse_date_out_of_range():
    with pytest.raises(ValueError):
        parse_date("32.13.2026")


def test_parse_time_valid():
    assert parse_time("14:30") == time(14, 30)


def test_parse_time_invalid():
    for invalid in ("25:00", "abc", ""):
        with pytest.raises(ValueError):
            parse_time(invalid)


def test_parse_duration_hours():
    result = parse_duration("1h")
    assert result.delta == timedelta(hours=1)
    assert result.all_day is False


def test_parse_duration_minutes():
    result = parse_duration("90min")
    assert result.delta == timedelta(minutes=90)
    assert result.all_day is False


def test_parse_duration_full_day():
    result = parse_duration("ganzer Tag")
    assert result.all_day is True


def test_parse_duration_invalid():
    with pytest.raises(ValueError):
        parse_duration("morgen")
