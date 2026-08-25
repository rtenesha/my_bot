from __future__ import annotations

import pytest

from parser import parse_birthday


class TestValidFormats:
    def test_dot_full(self):
        assert parse_birthday("Мама 15.03.1990") == ("Мама", 15, 3, 1990)

    def test_dot_no_year(self):
        assert parse_birthday("Мама 15.03") == ("Мама", 15, 3, None)

    def test_slash_full(self):
        assert parse_birthday("Папа 15/03/1990") == ("Папа", 15, 3, 1990)

    def test_month_word_no_year(self):
        assert parse_birthday("Сестра 15 марта") == ("Сестра", 15, 3, None)

    def test_month_word_with_year(self):
        assert parse_birthday("Брат 15 марта 1990") == ("Брат", 15, 3, 1990)

    def test_month_word_genitive(self):
        # «15 марта» — месяц в родительном падеже, префиксный матч
        assert parse_birthday("Дед 5 декабря") == ("Дед", 5, 12, None)

    def test_leap_day_no_year(self):
        assert parse_birthday("Коля 29.02") == ("Коля", 29, 2, None)

    def test_leap_day_with_year(self):
        assert parse_birthday("Коля 29.02.2000") == ("Коля", 29, 2, 2000)

    def test_multiword_name(self):
        assert parse_birthday("Мама и папа 15.03") == ("Мама и папа", 15, 3, None)

    def test_single_digit_day_month(self):
        assert parse_birthday("Аня 5.3") == ("Аня", 5, 3, None)

    def test_extra_spaces(self):
        assert parse_birthday("  Аня   5.3.2000  ") == ("Аня", 5, 3, 2000)


class TestInvalid:
    def test_empty(self):
        assert parse_birthday("") is None

    def test_only_name(self):
        assert parse_birthday("Мама") is None

    def test_only_date(self):
        # без имени — невалидно
        assert parse_birthday("15.03.1990") is None

    def test_invalid_month(self):
        assert parse_birthday("Мама 15.13") is None

    def test_invalid_day(self):
        assert parse_birthday("Мама 32.03") is None

    def test_impossible_date_feb30(self):
        assert parse_birthday("Мама 30.02.1990") is None

    def test_leap_day_nonleap_year(self):
        assert parse_birthday("Мама 29.02.2001") is None

    def test_two_digit_year_rejected(self):
        assert parse_birthday("Мама 15.03.20") is None

    def test_year_too_early(self):
        assert parse_birthday("Мама 15.03.1899") is None

    def test_year_in_future(self):
        assert parse_birthday("Мама 15.03.2999") is None

    def test_no_separators(self):
        assert parse_birthday("Мама 1503") is None

    def test_unknown_month_word(self):
        assert parse_birthday("Мама 15 абракадабра") is None


class TestYearRange:
    def test_1900_boundary_ok(self):
        assert parse_birthday("Мама 15.03.1900") == ("Мама", 15, 3, 1900)

    def test_current_year_ok(self):
        from datetime import date
        y = date.today().year
        assert parse_birthday(f"Мама 15.03.{y}") == ("Мама", 15, 3, y)