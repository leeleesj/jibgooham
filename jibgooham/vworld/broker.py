"""V-World API를 통한 중개사 검증 모듈."""

from __future__ import annotations

import asyncio
import re
from datetime import date
from typing import Any

import httpx
import structlog

from jibgooham.config import BROKER_CACHE_TTL, VWORLD_API_KEY
from jibgooham.models.broker import BrokerInfo
from jibgooham.models.listing import UnifiedListing
from jibgooham.storage import cache

logger = structlog.get_logger(__name__)

# V-World 부동산 중개업 조회 엔드포인트
_BROKER_SEARCH_URL = "https://www.vworld.kr/dtld/broker/dtld_list_s001.do"


async def verify_broker(
    broker_name: str,
    region: str | None = None,
) -> BrokerInfo | None:
    """중개소명으로 V-World 부동산 중개업 정보를 조회한다.

    Args:
        broker_name: 중개소 상호명
        region: 지역 필터 (현재 미사용, 향후 확장용)

    Returns:
        BrokerInfo 인스턴스 또는 None
    """
    if not broker_name:
        return None

    # 캐시 확인
    cached = cache.get("broker_cache", broker_name)
    if cached is not None:
        logger.debug("broker_cache_hit", broker_name=broker_name)
        return BrokerInfo(**cached)

    # V-World 중개소 조회 API 호출
    form_data = {
        "reqSearchNm": broker_name,
        "siDoCd": "",
        "siGunGuCd": "",
        "pageNo": "1",
        "pageSize": "10",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                _BROKER_SEARCH_URL,
                data=form_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            body = resp.text
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("vworld_broker_api_error", broker_name=broker_name, error=str(exc))
        return None

    # 응답 파싱 시도: JSON 우선, HTML 파싱 폴백
    result = _parse_broker_json(body, broker_name) or _parse_broker_html(body, broker_name)
    if result is None:
        logger.debug("vworld_broker_not_found", broker_name=broker_name)
        return None

    # 캐시 저장
    cache.set("broker_cache", broker_name, result.model_dump(mode="json"), ttl_seconds=BROKER_CACHE_TTL)
    logger.info("vworld_broker_verified", broker_name=broker_name, status=result.status)
    return result


def _parse_broker_json(body: str, broker_name: str) -> BrokerInfo | None:
    """응답이 JSON인 경우 파싱을 시도한다."""
    import json

    try:
        data = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return None

    # JSON 리스트 형태 응답
    items: list[dict[str, Any]] = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        # 다양한 JSON 구조 대응
        items = (
            data.get("list", [])
            or data.get("data", [])
            or data.get("result", [])
            or data.get("items", [])
        )
        if not items and any(k in data for k in ("regNm", "brkrNm")):
            items = [data]

    if not items:
        return None

    # 상호명과 가장 일치하는 항목 찾기
    item = _find_best_match(items, broker_name)
    if item is None:
        return None

    return _item_to_broker_info(item)


def _find_best_match(items: list[dict[str, Any]], broker_name: str) -> dict[str, Any] | None:
    """항목 목록에서 상호명과 가장 일치하는 항목을 반환한다."""
    # 정확히 일치하는 항목 우선
    for item in items:
        name = item.get("regNm", "") or item.get("brkrNm", "")
        if name == broker_name:
            return item

    # 부분 일치
    for item in items:
        name = item.get("regNm", "") or item.get("brkrNm", "")
        if broker_name in name or name in broker_name:
            return item

    # 결과가 있으면 첫 번째 반환
    return items[0] if items else None


def _item_to_broker_info(item: dict[str, Any]) -> BrokerInfo:
    """JSON 항목을 BrokerInfo 모델로 변환한다."""
    # 등록일 파싱
    opened_at: date | None = None
    reg_dt = item.get("regDt", "") or item.get("openDt", "")
    if reg_dt:
        opened_at = _parse_date(reg_dt)

    return BrokerInfo(
        name=item.get("regNm", "") or item.get("brkrNm", ""),
        registration_no=item.get("regNo") or item.get("registNo"),
        representative=item.get("rprsNm") or item.get("reprNm"),
        position=item.get("brkrPosNm", "") or item.get("posNm", "") or "공인중개사",
        opened_at=opened_at,
        status=item.get("useSttsCdNm", "") or item.get("sttusNm", "") or "정상영업",
        address=item.get("addr") or item.get("address"),
    )


def _parse_broker_html(body: str, broker_name: str) -> BrokerInfo | None:
    """응답이 HTML인 경우 테이블에서 중개소 정보를 파싱한다."""
    if "<table" not in body and "<tr" not in body:
        return None

    try:
        # 테이블 행 추출
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.DOTALL)
        if not rows:
            return None

        for row in rows:
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
            if not cells:
                continue

            # 셀 텍스트 정리
            cleaned = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]

            # 상호명이 포함된 행 찾기
            if not any(broker_name in cell for cell in cleaned):
                continue

            # 일반적인 테이블 구조: 번호, 상호, 대표자, 소재지, 등록번호, 직위, 상태, 등록일
            return _html_cells_to_broker_info(cleaned, broker_name)

    except (re.error, IndexError):
        logger.warning("broker_html_parse_error", broker_name=broker_name)

    return None


def _html_cells_to_broker_info(cells: list[str], broker_name: str) -> BrokerInfo | None:
    """HTML 테이블 셀 목록에서 BrokerInfo를 생성한다."""
    if len(cells) < 4:
        return None

    # 셀 개수에 따라 매핑 (일반적인 순서 기반)
    # 번호(0) | 상호(1) | 대표자(2) | 소재지(3) | 등록번호(4) | 직위(5) | 상태(6) | 등록일(7)
    name = broker_name
    representative = cells[2] if len(cells) > 2 else None
    address = cells[3] if len(cells) > 3 else None
    registration_no = cells[4] if len(cells) > 4 else None
    position = cells[5] if len(cells) > 5 else "공인중개사"
    status = cells[6] if len(cells) > 6 else "정상영업"
    opened_at_str = cells[7] if len(cells) > 7 else ""

    opened_at = _parse_date(opened_at_str) if opened_at_str else None

    return BrokerInfo(
        name=name,
        registration_no=registration_no,
        representative=representative,
        position=position or "공인중개사",
        opened_at=opened_at,
        status=status or "정상영업",
        address=address,
    )


def _parse_date(date_str: str) -> date | None:
    """다양한 날짜 형식을 date 객체로 파싱한다."""
    date_str = date_str.strip()
    if not date_str:
        return None

    # 숫자만 추출하여 시도
    digits = re.sub(r"\D", "", date_str)

    # YYYYMMDD (8자리)
    if len(digits) == 8:
        try:
            return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
        except ValueError:
            pass

    # YYYY-MM-DD 또는 YYYY.MM.DD 또는 YYYY/MM/DD
    match = re.match(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})", date_str)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            pass

    return None


async def enrich_listings_with_broker(
    listings: list[UnifiedListing],
) -> list[UnifiedListing]:
    """매물 목록의 중개소 정보를 V-World로 검증하여 broker 필드를 채운다.

    이미 broker가 설정된 매물의 상호명으로 V-World에서 검증 결과를 조회한다.
    API 실패 시에도 기존 매물 데이터는 유지된다.

    Args:
        listings: 중개소 정보를 검증할 매물 목록

    Returns:
        중개소 정보가 업데이트된 매물 목록 (원본과 동일 객체)
    """
    # 중개소명 수집 (broker가 있고 name이 있는 매물)
    broker_names: set[str] = set()
    for listing in listings:
        if listing.broker and listing.broker.name:
            broker_names.add(listing.broker.name)

    if not broker_names:
        logger.debug("no_brokers_to_verify", msg="검증할 중개소 없음")
        return listings

    # 병렬 조회
    tasks = {name: verify_broker(name) for name in broker_names}
    gathered = await asyncio.gather(
        *tasks.values(),
        return_exceptions=True,
    )
    results: dict[str, BrokerInfo | None] = {}
    for name, result in zip(tasks.keys(), gathered):
        if isinstance(result, Exception):
            logger.warning("broker_enrich_error", broker_name=name, error=str(result))
            results[name] = None
        else:
            results[name] = result

    # 매물에 검증된 중개소 정보 적용
    enriched_count = 0
    for listing in listings:
        if not listing.broker or not listing.broker.name:
            continue

        verified = results.get(listing.broker.name)
        if verified is not None:
            listing.broker = verified
            enriched_count += 1

    logger.info("broker_enrich_done", total=len(broker_names), enriched=enriched_count)
    return listings
