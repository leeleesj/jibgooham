"""플랫폼별 원본 데이터를 UnifiedListing으로 정규화하는 모듈."""

from __future__ import annotations

import re
from datetime import datetime

import structlog

from jibgooham.models.listing import UnifiedListing

logger = structlog.get_logger(__name__)

# --- 플랫폼별 매물 상세 URL 템플릿 ---
ZIGBANG_DETAIL_URL = "https://www.zigbang.com/home/oneroom/items/{item_id}"
NAVER_DETAIL_URL = "https://new.land.naver.com/rooms?articleNo={article_id}"
DAANGN_DETAIL_URL = "https://www.daangn.com/articles/{article_id}"
DABANG_DETAIL_URL = "https://www.dabangapp.com/room/{room_id}"

# --- 거래 유형 매핑 ---
ZIGBANG_DEAL_TYPE_MAP = {
    "rent": "월세",
    "jeonse": "전세",
    "buy": "매매",
    "월세": "월세",
    "전세": "전세",
    "매매": "매매",
}
NAVER_TRADE_TYPE_MAP = {
    "B2": "월세",
    "B1": "전세",
    "A1": "매매",
    "월세": "월세",
    "전세": "전세",
    "매매": "매매",
}
DABANG_SELLING_TYPE_MAP = {
    0: "월세",
    1: "전세",
    2: "매매",
    "0": "월세",
    "1": "전세",
    "2": "매매",
}

# --- 방 유형 매핑 ---
ZIGBANG_ROOM_TYPE_MAP = {
    "01": "원룸",
    "02": "투룸",
    "05": "오피스텔",
    "원룸": "원룸",
    "투룸": "투룸",
    "오피스텔": "오피스텔",
}
NAVER_REAL_ESTATE_TYPE_MAP = {
    "OR": "원룸",
    "DDDGG": "투룸",
    "OPST": "오피스텔",
    "APT": "아파트",
    "VL": "빌라",
}


def _parse_floor(floor_str: str | int | None) -> int | None:
    """층수 문자열을 정수로 변환.

    - "반지하", "지하" → -1
    - "옥탑" → 999
    - 숫자 문자열 → int
    - None → None
    """
    if floor_str is None:
        return None
    if isinstance(floor_str, int):
        return floor_str

    s = str(floor_str).strip()
    if not s:
        return None
    if "반지하" in s or "지하" in s:
        return -1
    if "옥탑" in s:
        return 999

    # 숫자 추출 시도
    match = re.search(r"-?\d+", s)
    if match:
        return int(match.group())
    return None


def _safe_int(value: str | int | float | None, default: int = 0) -> int:
    """안전하게 정수로 변환."""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _safe_float(value: str | int | float | None, default: float = 0.0) -> float:
    """안전하게 실수로 변환."""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _parse_datetime(value: str | None) -> datetime | None:
    """날짜 문자열을 datetime으로 변환."""
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def normalize_zigbang(raw: dict) -> UnifiedListing:
    """직방 원본 데이터를 UnifiedListing으로 변환.

    직방 응답 구조 (추정):
    - item_id, sales_type, deposit, rent, address, lat, lng,
    - service_type(room_type), exclusive_area, floor, building_floor,
    - title, description, images_thumbnail, manage_cost,
    - approve_date(준공일)
    """
    item_id = str(raw["item_id"])
    deal_type = ZIGBANG_DEAL_TYPE_MAP.get(
        raw.get("sales_type", ""), raw.get("sales_type", "월세")
    )
    room_type = ZIGBANG_ROOM_TYPE_MAP.get(
        raw.get("service_type", raw.get("room_type", "")), "원룸"
    )

    # 이미지 목록 처리
    images = raw.get("images_thumbnail", raw.get("images", []))
    if isinstance(images, str):
        images = [images]

    # 준공연도 파싱
    approve_date = raw.get("approve_date", "")
    built_year = None
    if approve_date:
        match = re.search(r"\d{4}", str(approve_date))
        if match:
            built_year = int(match.group())

    return UnifiedListing(
        id=f"zigbang_{item_id}",
        platform="zigbang",
        platform_id=item_id,
        deal_type=deal_type,
        deposit=_safe_int(raw.get("deposit", 0)),
        monthly_rent=_safe_int(raw.get("rent")) if raw.get("rent") is not None else None,
        address=raw.get("address", raw.get("local1", "") + " " + raw.get("local2", "")),
        latitude=_safe_float(raw.get("lat")) or None,
        longitude=_safe_float(raw.get("lng")) or None,
        station_name=raw.get("random_location", {}).get("station_name") if isinstance(raw.get("random_location"), dict) else None,
        station_distance_m=_safe_int(raw.get("random_location", {}).get("station_distance")) if isinstance(raw.get("random_location"), dict) else None,
        area_m2=_safe_float(raw.get("exclusive_area", raw.get("전용면적_m2", 0))),
        floor=_parse_floor(raw.get("floor")),
        building_floor=_safe_int(raw.get("building_floor")) or None,
        room_type=room_type,
        title=raw.get("title", ""),
        description=raw.get("description"),
        images=images if isinstance(images, list) else [],
        url=ZIGBANG_DETAIL_URL.format(item_id=item_id),
        listed_at=_parse_datetime(raw.get("created_at", raw.get("reg_date"))),
        built_year=built_year,
    )


def normalize_naver(raw: dict) -> UnifiedListing:
    """네이버 부동산 원본 데이터를 UnifiedListing으로 변환.

    네이버 응답 구조 (추정):
    - articleNo, tradeTypeName/tradeTypeCode, dealOrWarrantPrc, rentPrc,
    - area2(전용면적), floorInfo, articleName, direction,
    - latitude, longitude, realEstateTypeName, representativeImgUrl,
    - cpName(중개사), articleConfirmYmd(등록일)
    """
    article_id = str(raw.get("articleNo", raw.get("atclNo", "")))
    trade_type_code = raw.get("tradeTypeCode", raw.get("tradeTypeName", ""))
    deal_type = NAVER_TRADE_TYPE_MAP.get(trade_type_code, raw.get("tradeTypeName", "월세"))

    # 가격 정보: 네이버는 만원 단위
    deposit = _safe_int(raw.get("dealOrWarrantPrc", raw.get("prc", 0)))
    monthly_rent = _safe_int(raw.get("rentPrc")) if raw.get("rentPrc") is not None else None

    # 층 파싱: floorInfo는 "3/5" 형식일 수 있음
    floor_info = raw.get("floorInfo", raw.get("floor", ""))
    floor_val = None
    building_floor_val = None
    if isinstance(floor_info, str) and "/" in floor_info:
        parts = floor_info.split("/")
        floor_val = _parse_floor(parts[0].strip())
        building_floor_val = _parse_floor(parts[1].strip()) if len(parts) > 1 else None
    else:
        floor_val = _parse_floor(floor_info)

    # 방 유형
    real_estate_type = raw.get("realEstateTypeCode", raw.get("realEstateTypeName", ""))
    room_type = NAVER_REAL_ESTATE_TYPE_MAP.get(real_estate_type, raw.get("realEstateTypeName", "원룸"))

    # 이미지
    images = []
    rep_img = raw.get("representativeImgUrl", raw.get("representativeImgThumb"))
    if rep_img:
        images = [rep_img]
    if raw.get("images"):
        images = raw["images"] if isinstance(raw["images"], list) else [raw["images"]]

    # 준공연도
    built_year = None
    build_year_raw = raw.get("buildYear", raw.get("approveDate", ""))
    if build_year_raw:
        match = re.search(r"\d{4}", str(build_year_raw))
        if match:
            built_year = int(match.group())

    return UnifiedListing(
        id=f"naver_{article_id}",
        platform="naver",
        platform_id=article_id,
        deal_type=deal_type,
        deposit=deposit,
        monthly_rent=monthly_rent,
        address=raw.get("exposureAddress", raw.get("address", "")),
        latitude=_safe_float(raw.get("latitude", raw.get("lat"))) or None,
        longitude=_safe_float(raw.get("longitude", raw.get("lng"))) or None,
        station_name=raw.get("nearSubway", raw.get("stationName")),
        station_distance_m=_safe_int(raw.get("subwayDistance")) or None,
        area_m2=_safe_float(raw.get("area2", raw.get("exclusiveArea", 0))),
        floor=floor_val,
        building_floor=building_floor_val,
        room_type=room_type,
        title=raw.get("articleName", raw.get("atclNm", "")),
        description=raw.get("articleFeatureDesc", raw.get("description")),
        images=images,
        url=NAVER_DETAIL_URL.format(article_id=article_id),
        listed_at=_parse_datetime(raw.get("articleConfirmYmd", raw.get("confirmedAt"))),
        built_year=built_year,
    )


def normalize_daangn(raw: dict) -> UnifiedListing:
    """당근마켓 원본 데이터를 UnifiedListing으로 변환.

    당근마켓 부동산 응답 구조 (추정):
    - id, title, content, images, region_name,
    - deposit, monthly_rent, deal_type,
    - exclusive_area, floor, address, lat, lng
    """
    article_id = str(raw.get("id", raw.get("article_id", "")))
    deal_type = raw.get("deal_type", raw.get("sales_type", "월세"))

    images = raw.get("images", raw.get("image_urls", []))
    if isinstance(images, str):
        images = [images]

    return UnifiedListing(
        id=f"daangn_{article_id}",
        platform="daangn",
        platform_id=article_id,
        deal_type=deal_type,
        deposit=_safe_int(raw.get("deposit", 0)),
        monthly_rent=_safe_int(raw.get("monthly_rent")) if raw.get("monthly_rent") is not None else None,
        address=raw.get("address", raw.get("region_name", "")),
        latitude=_safe_float(raw.get("lat", raw.get("latitude"))) or None,
        longitude=_safe_float(raw.get("lng", raw.get("longitude"))) or None,
        area_m2=_safe_float(raw.get("exclusive_area", raw.get("area_m2", 0))),
        floor=_parse_floor(raw.get("floor")),
        building_floor=_safe_int(raw.get("building_floor")) or None,
        room_type=raw.get("room_type", "원룸"),
        title=raw.get("title", ""),
        description=raw.get("content", raw.get("description")),
        images=images if isinstance(images, list) else [],
        url=DAANGN_DETAIL_URL.format(article_id=article_id),
        listed_at=_parse_datetime(raw.get("created_at", raw.get("published_at"))),
        built_year=_safe_int(raw.get("built_year")) or None,
    )


def normalize_dabang(raw: dict) -> UnifiedListing:
    """다방 원본 데이터를 UnifiedListing으로 변환.

    다방 응답 구조 (추정):
    - id/seq, selling_type, deposit, price(월세),
    - exclusive_area, floor, address, lat, lng,
    - title, memo, image_thumbnail, room_type,
    - approve_date(준공일)
    """
    room_id = str(raw.get("id", raw.get("seq", "")))
    selling_type = raw.get("selling_type", 0)
    deal_type = DABANG_SELLING_TYPE_MAP.get(selling_type, "월세")

    # 이미지
    images = raw.get("images", raw.get("image_thumbnail", []))
    if isinstance(images, str):
        images = [images]

    # 준공연도
    built_year = None
    approve_date = raw.get("approve_date", raw.get("use_approve_date", ""))
    if approve_date:
        match = re.search(r"\d{4}", str(approve_date))
        if match:
            built_year = int(match.group())

    return UnifiedListing(
        id=f"dabang_{room_id}",
        platform="dabang",
        platform_id=room_id,
        deal_type=deal_type,
        deposit=_safe_int(raw.get("deposit", raw.get("보증금", 0))),
        monthly_rent=_safe_int(raw.get("price", raw.get("monthly_rent"))) if raw.get("price", raw.get("monthly_rent")) is not None else None,
        address=raw.get("address", raw.get("local1", "") + " " + raw.get("local2", "")),
        latitude=_safe_float(raw.get("lat", raw.get("latitude"))) or None,
        longitude=_safe_float(raw.get("lng", raw.get("longitude"))) or None,
        area_m2=_safe_float(raw.get("exclusive_area", raw.get("전용면적_m2", 0))),
        floor=_parse_floor(raw.get("floor")),
        building_floor=_safe_int(raw.get("building_floor")) or None,
        room_type=raw.get("room_type_str", raw.get("room_type", "원룸")),
        title=raw.get("title", raw.get("room_title", "")),
        description=raw.get("memo", raw.get("description")),
        images=images if isinstance(images, list) else [],
        url=DABANG_DETAIL_URL.format(room_id=room_id),
        listed_at=_parse_datetime(raw.get("created_at", raw.get("reg_date"))),
        built_year=built_year,
    )


# --- 플랫폼별 정규화 함수 매핑 ---
_NORMALIZER_MAP: dict[str, callable] = {
    "zigbang": normalize_zigbang,
    "naver": normalize_naver,
    "daangn": normalize_daangn,
    "dabang": normalize_dabang,
}


def normalize(platform: str, raw_list: list[dict]) -> list[UnifiedListing]:
    """플랫폼별 정규화 함수를 디스패치하여 원본 데이터를 UnifiedListing으로 변환.

    파싱 실패한 항목은 건너뛰고 로그를 남긴다.

    Args:
        platform: 플랫폼 이름 ("zigbang", "naver", "daangn", "dabang")
        raw_list: 원본 매물 딕셔너리 리스트

    Returns:
        정규화된 UnifiedListing 리스트
    """
    normalizer = _NORMALIZER_MAP.get(platform)
    if not normalizer:
        logger.error("지원하지 않는 플랫폼", platform=platform)
        return []

    results: list[UnifiedListing] = []
    for i, raw in enumerate(raw_list):
        try:
            listing = normalizer(raw)
            results.append(listing)
        except Exception:
            logger.exception(
                "매물 정규화 실패 — 건너뜀",
                platform=platform,
                index=i,
                raw_keys=list(raw.keys()) if isinstance(raw, dict) else None,
            )
    logger.info(
        "정규화 완료",
        platform=platform,
        total=len(raw_list),
        success=len(results),
        skipped=len(raw_list) - len(results),
    )
    return results
