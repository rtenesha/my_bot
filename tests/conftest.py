from __future__ import annotations

import pytest

import db


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    """Локальный файл БД (через stdlib sqlite3), monkeypatch в db.TURSO_DATABASE_URL.

    Каждый тест — свежий файл; init_db() создаёт схему тем же кодом, что и в проде.
    """
    path = tmp_path / "test.db"
    monkeypatch.setattr(db, "TURSO_DATABASE_URL", str(path))
    return str(path)


@pytest.fixture
def db_ready(db_path):
    """Инициализированная БД с применённой схемой."""
    db.init_db()
    return db_path