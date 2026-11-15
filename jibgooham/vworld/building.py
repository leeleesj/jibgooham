"""V-World API를 통한 건물 정보 조회 모듈."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import structlog

from jibgooham.config import BUILDING_CACHE_TTL, VWORLD_API_KEY
from jibgooham.models.listing import UnifiedListing
from jibgooham.storage import cache

logger = structlog.get_logger(__name__)

# V-World 건축물대장 API 엔드포인트
_VWORLD_DATA_URL = "https://api.vworld.kr/req/data"


async def get_building_info(address: str) -> dict[str, Any] | None:
    """주소로 V-World 건축물대장에서 건물 정보를 조회한다.

    Args:
        address: 조회할 건물 주소

    Returns:
        건물 정보 dict (built_year, building_structure, land_use) 또는 None
    """
    # API 키가 없으면 조용히 None 반환
    if not VWORLD_API_KEY:
        logger.debug("vworld_api_key_missing", msg="VWORLD_API_KEY가 설정되지 않음")
        return None

    # 캐시 확인
    cached = cache.get("building_cache", address)
    if cached is not None:
        logger.debug("building_cache_hit", address=address)
        return cached

    # V-World API 호출
    params = {
        "service": "data",
        "request": "GetFeature",
        "data": "LT_C_AISRESC",
        "key": VWORLD_API_KEY,
        "geometry": "false",
        "attribute": "true",
        "crs": "EPSG:4326",
        "attrFilter": f"addr:like:{address}",
        "size": "1",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(_VWORLD_DATA_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("vworld_building_api_error", address=address, error=str(exc))
        return None

    # 응답 파싱
    result = _parse_building_response(data)
    if result is None:
        logger.debug("vworld_building_not_found", address=address)
        return None

    # 캐시 저장
    cache.set("building_cache", address, result, ttl_seconds=BUILDING_CACHE_TTL)
    logger.info("vworld_building_fetched", address=address, built_year=result.get("built_year"))
    return result


def _parse_building_response(data: dict[str, Any]) -> dict[str, Any] | None:
    """V-World 건축물대장 응답에서 건물 정보를 추출한다."""
    try:
        response = data.get("response", {})
        status = response.get("status", "")
        if status != "OK":
            return None

        features = response.get("result", {}).get("featureCollection", {}).get("features", [])
        if not features:
            return None

        props = features[0].get("properties", {})

        # 사용승인일에서 연도 추출
        use_apr_day = props.get("useAprDay", "")
        built_year: int | None = None
        if use_apr_day and len(use_apr_day) >= 4:
            try:
                built_year = int(use_apr_day[:4])
            except ValueError:
                pass

        # 건물구조: archGbCdNm 우선, 없으면 strctCdNm
        building_structure = props.get("archGbCdNm") or props.get("strctCdNm") or None

        # 용도: jimokNm 우선, 없으면 etcPurps
        land_use = props.get("jimokNm") or props.get("etcPurps") or None

        return {
            "built_year": built_year,
            "building_structure": building_structure,
            "land_use": land_use,
        }
    except (KeyError, IndexError, TypeError):
        return None


async def enrich_listings_with_building(
    listings: list[UnifiedListing],
) -> list[UnifiedListing]:
    """매물 목록에 V-World 건물 정보를 추가한다.

    built_year, building_structure, land_use 필드를 채운다.
    API 실패 시에도 기존 매물 데이터는 유지된다.

    Args:
        listings: 건물 정보를 추가할 매물 목록

    Returns:
        건물 정보가 추가된 매물 목록 (원본과 동일 객체)
    """
    if not VWORLD_API_KEY:
        logger.debug("vworld_api_key_missing", msg="건물 정보 enrichment 생략")
        return listings

    # 중복 주소 제거하여 효율적으로 조회
    unique_addresses = {listing.address for listing in listings}
    tasks = {addr: get_building_info(addr) for addr in unique_addresses}

    # 모든 주소에 대해 병렬 조회
    results: dict[str, dict[str, Any] | None] = {}
    gathered = await asyncio.gather(
        *tasks.values(),
        return_exceptions=True,
    )
    for addr, result in zip(tasks.keys(), gathered):
        if isinstance(result, Exception):
            logger.warning("building_enrich_error", address=addr, error=str(result))
            results[addr] = None
        else:
            results[addr] = result

    # 매물에 건물 정보 적용
    for listing in listings:
        info = results.get(listing.address)
        if info is None:
            continue

        if info.get("built_year") is not None and listing.built_year is None:
            listing.built_year = info["built_year"]
        if info.get("building_structure") and listing.building_structure is None:
            listing.building_structure = info["building_structure"]
        if info.get("land_use") and listing.land_use is None:
            listing.land_use = info["land_use"]

    logger.info("building_enrich_done", total=len(listings), enriched=sum(1 for a in unique_addresses if results.get(a)))
    return listings
