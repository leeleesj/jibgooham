"""SQLite 기반 캐시 스토리지."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from jibgooham.config import (
    BROKER_CACHE_TTL,
    BUILDING_CACHE_TTL,
    JIBGOOHAM_CACHE_DIR,
    LISTING_CACHE_TTL,
)

# 테이블별 기본 TTL 매핑 (초 단위)
DEFAULT_TTL: dict[str, int] = {
    "listing_cache": LISTING_CACHE_TTL,
    "building_cache": BUILDING_CACHE_TTL,
    "broker_cache": BROKER_CACHE_TTL,
}

# 테이블별 기본 키 컬럼명
_KEY_COLUMNS: dict[str, str] = {
    "listing_cache": "cache_key",
    "building_cache": "address",
    "broker_cache": "broker_name",
}

_DB_FILE = "cache.db"


def _db_path() -> Path:
    """캐시 DB 파일 경로 반환."""
    return Path(JIBGOOHAM_CACHE_DIR) / _DB_FILE


def _connect() -> sqlite3.Connection:
    """SQLite 연결 생성. 캐시 디렉토리가 없으면 자동 생성."""
    db = _db_path()
    db.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(db))


def init_db() -> None:
    """캐시 테이블 초기화. 테이블이 없으면 생성한다."""
    conn = _connect()
    try:
        cursor = conn.cursor()
        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS listing_cache (
                cache_key   TEXT PRIMARY KEY,
                data        TEXT NOT NULL,
                cached_at   INTEGER NOT NULL,
                expires_at  INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS building_cache (
                address     TEXT PRIMARY KEY,
                data        TEXT NOT NULL,
                cached_at   INTEGER NOT NULL,
                expires_at  INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS broker_cache (
                broker_name TEXT PRIMARY KEY,
                data        TEXT NOT NULL,
                cached_at   INTEGER NOT NULL,
                expires_at  INTEGER NOT NULL
            );
        """)
        conn.commit()
    finally:
        conn.close()


def get(table: str, key: str) -> Any | None:
    """캐시에서 데이터를 조회한다.

    만료된 항목은 None을 반환한다.

    Args:
        table: 테이블명 (listing_cache, building_cache, broker_cache)
        key: 조회할 키 값

    Returns:
        캐시된 데이터(dict/list 등) 또는 None
    """
    key_col = _KEY_COLUMNS[table]
    conn = _connect()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT data, expires_at FROM {table} WHERE {key_col} = ?",  # noqa: S608
            (key,),
        )
        row = cursor.fetchone()
        if row is None:
            return None

        data, expires_at = row
        # 만료 확인
        if int(time.time()) > expires_at:
            return None

        return json.loads(data)
    finally:
        conn.close()


def set(  # noqa: A001
    table: str,
    key: str,
    data: Any,
    ttl_seconds: int | None = None,
) -> None:
    """캐시에 데이터를 저장한다.

    Args:
        table: 테이블명
        key: 저장할 키 값
        data: 저장할 데이터 (JSON 직렬화 가능해야 함)
        ttl_seconds: TTL(초). None이면 테이블 기본값 사용.
    """
    if ttl_seconds is None:
        ttl_seconds = DEFAULT_TTL[table]

    key_col = _KEY_COLUMNS[table]
    now = int(time.time())
    expires_at = now + ttl_seconds
    serialized = json.dumps(data, ensure_ascii=False)

    conn = _connect()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"INSERT OR REPLACE INTO {table} ({key_col}, data, cached_at, expires_at) "  # noqa: S608
            "VALUES (?, ?, ?, ?)",
            (key, serialized, now, expires_at),
        )
        conn.commit()
    finally:
        conn.close()


def clear_expired() -> int:
    """모든 테이블에서 만료된 캐시 항목을 삭제한다.

    Returns:
        삭제된 총 행 수
    """
    now = int(time.time())
    total_deleted = 0

    conn = _connect()
    try:
        cursor = conn.cursor()
        for table in _KEY_COLUMNS:
            cursor.execute(
                f"DELETE FROM {table} WHERE expires_at < ?",  # noqa: S608
                (now,),
            )
            total_deleted += cursor.rowcount
        conn.commit()
    finally:
        conn.close()

    return total_deleted
