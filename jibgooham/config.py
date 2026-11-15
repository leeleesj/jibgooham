"""환경변수 로드 및 애플리케이션 설정 모듈."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# .env 파일 로드 (프로젝트 루트 기준)
load_dotenv()

# --- API 키 ---
VWORLD_API_KEY: str = os.getenv("VWORLD_API_KEY", "")
KAKAO_REST_API_KEY: str = os.getenv("KAKAO_REST_API_KEY", "")

# --- 캐시 설정 ---
_default_cache_dir = str(Path.home() / ".cache" / "jibgooham")
JIBGOOHAM_CACHE_DIR: str = os.getenv("JIBGOOHAM_CACHE_DIR", _default_cache_dir)

# --- 캐시 TTL (초 단위) ---
LISTING_CACHE_TTL: int = 24 * 60 * 60       # 24시간
BUILDING_CACHE_TTL: int = 7 * 24 * 60 * 60  # 7일
BROKER_CACHE_TTL: int = 7 * 24 * 60 * 60    # 7일

# --- 지원 플랫폼 ---
SUPPORTED_PLATFORMS: list[str] = ["zigbang", "naver", "daangn", "dabang"]
