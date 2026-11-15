"""중복 매물 제거 모듈.

위경도, 전용면적, 가격 기준으로 중복 매물을 판별하고 병합한다.
"""

from __future__ import annotations

import math

import structlog

from jibgooham.models.listing import UnifiedListing

logger = structlog.get_logger(__name__)

# --- 중복 판별 임계값 ---
DISTANCE_THRESHOLD_M = 20.0  # 위경도 반경 20m
AREA_TOLERANCE_RATIO = 0.05  # 전용면적 허용오차 5%

# --- 지구 반경 (미터) ---
EARTH_RADIUS_M = 6_371_000.0


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """두 위경도 좌표 사이의 거리를 미터 단위로 계산 (Haversine 공식).

    Args:
        lat1: 지점1 위도 (도)
        lon1: 지점1 경도 (도)
        lat2: 지점2 위도 (도)
        lon2: 지점2 경도 (도)

    Returns:
        두 지점 사이 거리 (미터)
    """
    lat1_r, lat2_r = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_M * c


def _is_duplicate(a: UnifiedListing, b: UnifiedListing) -> bool:
    """두 매물이 중복인지 판별.

    세 조건을 모두 만족해야 중복으로 판정:
    1. 위경도 반경 20m 이내
    2. 전용면적 허용오차 5% 이내
    3. 보증금 동일 + 월세 동일
    """
    # 위경도가 없으면 비교 불가
    if a.latitude is None or a.longitude is None:
        return False
    if b.latitude is None or b.longitude is None:
        return False

    # 조건 1: 거리
    distance = _haversine(a.latitude, a.longitude, b.latitude, b.longitude)
    if distance > DISTANCE_THRESHOLD_M:
        return False

    # 조건 2: 전용면적 오차 5% 이내
    avg_area = (a.area_m2 + b.area_m2) / 2
    if avg_area > 0 and abs(a.area_m2 - b.area_m2) / avg_area > AREA_TOLERANCE_RATIO:
        return False

    # 조건 3: 보증금, 월세 동일
    if a.deposit != b.deposit:
        return False
    rent_a = a.monthly_rent or 0
    rent_b = b.monthly_rent or 0
    if rent_a != rent_b:
        return False

    return True


def _pick_representative(group: list[UnifiedListing]) -> UnifiedListing:
    """중복 그룹에서 대표 매물을 선택.

    이미지가 가장 많은 매물을 대표로 선택하고,
    나머지 매물의 플랫폼을 also_on에 추가한다.
    """
    # 이미지 수 내림차순 정렬
    sorted_group = sorted(group, key=lambda x: len(x.images), reverse=True)
    representative = sorted_group[0].model_copy()

    # 나머지 플랫폼을 also_on에 추가
    also_on: list[str] = list(representative.also_on)
    for listing in sorted_group[1:]:
        if listing.platform not in also_on and listing.platform != representative.platform:
            also_on.append(listing.platform)
    representative.also_on = also_on

    return representative


def deduplicate(listings: list[UnifiedListing]) -> list[UnifiedListing]:
    """중복 매물을 병합하여 고유 매물 리스트를 반환.

    위경도가 None인 매물은 중복 비교 대상에서 제외하고 그대로 결과에 포함한다.

    Args:
        listings: 정규화된 매물 리스트

    Returns:
        중복 제거된 매물 리스트
    """
    if not listings:
        return []

    # 위경도 없는 매물은 별도 처리
    geo_listings: list[UnifiedListing] = []
    no_geo_listings: list[UnifiedListing] = []
    for listing in listings:
        if listing.latitude is not None and listing.longitude is not None:
            geo_listings.append(listing)
        else:
            no_geo_listings.append(listing)

    # Union-Find 방식으로 중복 그룹 구성
    n = len(geo_listings)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    for i in range(n):
        for j in range(i + 1, n):
            if _is_duplicate(geo_listings[i], geo_listings[j]):
                union(i, j)

    # 그룹별로 묶기
    groups: dict[int, list[UnifiedListing]] = {}
    for i in range(n):
        root = find(i)
        groups.setdefault(root, []).append(geo_listings[i])

    # 각 그룹에서 대표 선택
    results: list[UnifiedListing] = []
    merged_count = 0
    for group in groups.values():
        representative = _pick_representative(group)
        results.append(representative)
        if len(group) > 1:
            merged_count += 1

    # 위경도 없는 매물 추가
    results.extend(no_geo_listings)

    logger.info(
        "중복 제거 완료",
        input_count=len(listings),
        output_count=len(results),
        merged_groups=merged_count,
        no_geo=len(no_geo_listings),
    )
    return results
