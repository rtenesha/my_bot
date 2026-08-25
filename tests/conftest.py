from __future__ import annotations

import pytest

import db


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    """Файл БД (изолированный на тест), monkeypatch-им в db.DB_PATH.

    Каждый тест получает свежий путь; init_db() вызывается в самом тесте
    (или в фикстуре ниже), чтобы схема создавалась через тот же код, что и в проде.
    """
    path = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_PATH", str(path))
    return str(path)


@pytest.fixture
async def db_ready(db_path):
    """Инициализированная БД с применённой схемой."""
    await db.init_db()
    return db_path