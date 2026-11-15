"""SQLite 캐시 단위 테스트."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from unittest.mock import patch

import pytest

# 캐시 모듈은 import 시점에 JIBGOOHAM_CACHE_DIR를 읽으므로
# tmp_path 기반 경로를 주입하기 위해 patch를 사용한다.


def _make_cache_module(tmp_path: Path):
    """tmp_path를 캐시 디렉토리로 사용하도록 캐시 모듈을 패치하여 반환하는 헬퍼."""
    import importlib

    import jibgooham.storage.cache as cache_mod

    # _db_path()가 tmp_path를 가리키도록 패치
    db_file = tmp_path / "cache.db"

    def _patched_db_path():
        return db_file

    cache_mod._db_path = _patched_db_path
    # _connect()도 패치된 _db_path를 사용하도록 재정의
    def _patched_connect():
        db_file.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(str(db_file))

    cache_mod._connect = _patched_connect
    return cache_mod


# ---------------------------------------------------------------------------
# init_db 테스트
# ---------------------------------------------------------------------------


class TestInitDb:
    """init_db() 테이블 생성 테스트."""

    def test_init_db_세_테이블_생성(self, tmp_path):
        """init_db() 호출 후 세 개 테이블이 모두 존재해야 한다."""
        cache = _make_cache_module(tmp_path)
        cache.init_db()

        db_file = tmp_path / "cache.db"
        assert db_file.exists(), "DB 파일이 생성되어야 한다"

        conn = sqlite3.connect(str(db_file))
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()

        assert "listing_cache" in tables
        assert "building_cache" in tables
        assert "broker_cache" in tables

    def test_init_db_두_번_호출해도_오류_없음(self, tmp_path):
        """init_db()를 두 번 호출해도 오류가 발생하지 않아야 한다 (IF NOT EXISTS)."""
        cache = _make_cache_module(tmp_path)
        cache.init_db()
        cache.init_db()  # 두 번째 호출 — 예외 없어야 함


# ---------------------------------------------------------------------------
# set / get 라운드트립 테스트
# ---------------------------------------------------------------------------


class TestSetGet:
    """set() + get() 기본 동작 테스트."""

    def test_set_get_라운드트립(self, tmp_path):
        """set() 후 get()으로 동일한 데이터를 반환해야 한다."""
        cache = _make_cache_module(tmp_path)
        cache.init_db()

        data = {"price": 500, "address": "서울 마포구"}
        cache.set("listing_cache", "test_key_1", data, ttl_seconds=60)

        result = cache.get("listing_cache", "test_key_1")
        assert result == data

    def test_다양한_타입_저장(self, tmp_path):
        """리스트, 중첩 dict 등 JSON 직렬화 가능한 타입을 저장할 수 있어야 한다."""
        cache = _make_cache_module(tmp_path)
        cache.init_db()

        list_data = [1, 2, 3, {"key": "value"}]
        cache.set("listing_cache", "list_key", list_data, ttl_seconds=60)

        result = cache.get("listing_cache", "list_key")
        assert result == list_data

    def test_building_cache_키_컬럼_address(self, tmp_path):
        """building_cache 테이블은 'address' 컬럼을 키로 사용해야 한다."""
        cache = _make_cache_module(tmp_path)
        cache.init_db()

        data = {"floors": 10, "built_year": 2010}
        cache.set("building_cache", "서울 강남구 테헤란로 1", data, ttl_seconds=60)

        result = cache.get("building_cache", "서울 강남구 테헤란로 1")
        assert result == data

    def test_broker_cache_키_컬럼_broker_name(self, tmp_path):
        """broker_cache 테이블은 'broker_name' 컬럼을 키로 사용해야 한다."""
        cache = _make_cache_module(tmp_path)
        cache.init_db()

        data = {"registration_no": "12345", "status": "정상영업"}
        cache.set("broker_cache", "행복부동산", data, ttl_seconds=60)

        result = cache.get("broker_cache", "행복부동산")
        assert result == data


# ---------------------------------------------------------------------------
# TTL 만료 테스트
# ---------------------------------------------------------------------------


class TestTtlExpiry:
    """TTL 만료 후 get() → None 테스트."""

    def test_ttl_만료_후_get은_None(self, tmp_path):
        """TTL이 지난 항목은 get()에서 None을 반환해야 한다."""
        cache = _make_cache_module(tmp_path)
        cache.init_db()

        cache.set("listing_cache", "expire_key", {"val": 1}, ttl_seconds=1)

        # 만료 시간을 조작하기 위해 time.time()을 2초 앞으로 패치
        with patch("jibgooham.storage.cache.time") as mock_time:
            mock_time.time.return_value = time.time() + 2
            result = cache.get("listing_cache", "expire_key")

        assert result is None, "만료된 캐시는 None이어야 한다"

    def test_ttl_내_get은_데이터_반환(self, tmp_path):
        """TTL이 아직 남아있으면 get()이 데이터를 반환해야 한다."""
        cache = _make_cache_module(tmp_path)
        cache.init_db()

        data = {"valid": True}
        cache.set("listing_cache", "valid_key", data, ttl_seconds=3600)

        result = cache.get("listing_cache", "valid_key")
        assert result == data


# ---------------------------------------------------------------------------
# clear_expired 테스트
# ---------------------------------------------------------------------------


class TestClearExpired:
    """clear_expired() 테스트."""

    def test_clear_expired_만료_항목_삭제(self, tmp_path):
        """만료된 항목은 clear_expired() 후 DB에서 사라져야 한다."""
        cache = _make_cache_module(tmp_path)
        cache.init_db()

        # 이미 만료된 항목 직접 삽입 (expires_at을 과거로 설정)
        db_file = tmp_path / "cache.db"
        past_time = int(time.time()) - 100  # 100초 전에 만료
        conn = sqlite3.connect(str(db_file))
        conn.execute(
            "INSERT INTO listing_cache (cache_key, data, cached_at, expires_at) VALUES (?, ?, ?, ?)",
            ("expired_key", '{"x": 1}', past_time - 60, past_time),
        )
        conn.commit()
        conn.close()

        deleted = cache.clear_expired()
        assert deleted >= 1, "최소 1개 항목이 삭제되어야 한다"

        # DB에서도 삭제되었는지 확인
        conn = sqlite3.connect(str(db_file))
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM listing_cache WHERE cache_key = ?", ("expired_key",))
        row = cursor.fetchone()
        conn.close()
        assert row is None, "만료된 항목은 DB에서 삭제되어야 한다"

    def test_clear_expired_유효_항목_보존(self, tmp_path):
        """아직 유효한 항목은 clear_expired() 후에도 남아있어야 한다."""
        cache = _make_cache_module(tmp_path)
        cache.init_db()

        cache.set("listing_cache", "alive_key", {"alive": True}, ttl_seconds=3600)
        cache.clear_expired()

        result = cache.get("listing_cache", "alive_key")
        assert result == {"alive": True}, "유효한 캐시 항목은 삭제되면 안 된다"

    def test_clear_expired_반환값은_삭제된_행_수(self, tmp_path):
        """clear_expired() 반환값은 삭제된 총 행 수이어야 한다."""
        cache = _make_cache_module(tmp_path)
        cache.init_db()

        # 만료 항목 없을 때 — 0 반환
        deleted = cache.clear_expired()
        assert deleted == 0


# ---------------------------------------------------------------------------
# 존재하지 않는 키 테스트
# ---------------------------------------------------------------------------


class TestGetMissingKey:
    """존재하지 않는 키 get() 테스트."""

    def test_없는_키_get은_None(self, tmp_path):
        """DB에 없는 키로 get()을 호출하면 None을 반환해야 한다."""
        cache = _make_cache_module(tmp_path)
        cache.init_db()

        result = cache.get("listing_cache", "nonexistent_key")
        assert result is None


# ---------------------------------------------------------------------------
# 덮어쓰기 테스트
# ---------------------------------------------------------------------------


class TestOverwrite:
    """같은 키 set() 두 번 → 덮어쓰기 테스트."""

    def test_동일_키_두_번_set_마지막_값_반환(self, tmp_path):
        """같은 키에 set()을 두 번 하면 나중에 쓴 값이 반환되어야 한다."""
        cache = _make_cache_module(tmp_path)
        cache.init_db()

        cache.set("listing_cache", "dup_key", {"version": 1}, ttl_seconds=60)
        cache.set("listing_cache", "dup_key", {"version": 2}, ttl_seconds=60)

        result = cache.get("listing_cache", "dup_key")
        assert result == {"version": 2}, "마지막으로 set한 값이 반환되어야 한다"

    def test_동일_키_두_번_set_행_수_1개(self, tmp_path):
        """같은 키로 두 번 set()해도 DB 행 수는 1이어야 한다 (INSERT OR REPLACE)."""
        cache = _make_cache_module(tmp_path)
        cache.init_db()

        cache.set("listing_cache", "single_key", {"a": 1}, ttl_seconds=60)
        cache.set("listing_cache", "single_key", {"a": 2}, ttl_seconds=60)

        db_file = tmp_path / "cache.db"
        conn = sqlite3.connect(str(db_file))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM listing_cache WHERE cache_key = ?", ("single_key",))
        count = cursor.fetchone()[0]
        conn.close()

        assert count == 1, "같은 키는 1개의 행만 존재해야 한다"
