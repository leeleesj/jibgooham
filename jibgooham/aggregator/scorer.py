"""매물 스코어링 모듈.

검색 조건과 가중치를 기반으로 각 매물에 0~100 점수를 부여한다.
"""

from __future__ import annotations

import structlog

from jibgooham.models.listing import UnifiedListing
from jibgooham.models.search_params import ScoringWeights, SearchParams

logger = structlog.get_logger(__name__)

# --- 건축연도 기준 (현재 연도) ---
CURRENT_YEAR = 2024

# --- 신뢰등급 점수 매핑 ---
TRUST_LEVEL_SCORE: dict[str, float] = {
    "high": 100.0,
    "medium": 70.0,
    "low": 40.0,
    "danger": 0.0,
}
DEFAULT_TRUST_SCORE = 50.0

# --- 이미지 점수 기준 개수 ---
IMAGE_FULL_SCORE_COUNT = 10

# --- 역 거리 점수 계산 기준 (m당 감점) ---
STATION_DISTANCE_DIVISOR = 10.0


def _calc_station_score(listing: UnifiedListing) -> float:
    """역 거리 점수 계산.

    거리 없으면 50, 있으면 max(0, 100 - distance_m / 10).
    """
    if listing.station_distance_m is None:
        return 50.0
    return max(0.0, 100.0 - listing.station_distance_m / STATION_DISTANCE_DIVISOR)


def _calc_price_score(listing: UnifiedListing, search_params: SearchParams) -> float:
    """가격 점수 계산.

    예산(deposit_max) 대비 보증금 비율로 산출.
    예산 내 적정가일수록 높은 점수.
    """
    if search_params.deposit_max <= 0:
        return 50.0
    ratio = listing.deposit / search_params.deposit_max
    # 예산의 0~100% 범위 안이면 높은 점수, 초과하면 0
    if ratio > 1.0:
        return 0.0
    # 예산 대비 적절한 비율 → 높은 점수 (저렴할수록 좋음)
    return max(0.0, (1.0 - ratio) * 100.0)


def _calc_area_score(listing: UnifiedListing, search_params: SearchParams) -> float:
    """면적 점수 계산.

    area_max 대비 비율 * 100 (넓을수록 높은 점수).
    """
    if search_params.area_max <= 0:
        return 50.0
    ratio = listing.area_m2 / search_params.area_max
    return min(ratio * 100.0, 100.0)


def _calc_age_score(listing: UnifiedListing) -> float:
    """건축연도 점수 계산.

    신축일수록 높은 점수. built_year가 None이면 50.
    """
    if listing.built_year is None:
        return 50.0
    age = CURRENT_YEAR - listing.built_year
    if age <= 0:
        return 100.0
    # 30년 이상이면 0점
    return max(0.0, 100.0 - (age / 30.0) * 100.0)


def _calc_broker_score(listing: UnifiedListing) -> float:
    """중개사 신뢰도 점수 계산.

    trust_level 기반 (high=100, medium=70, low=40, danger=0).
    중개사 정보 없으면 50.
    """
    if listing.broker is None:
        return DEFAULT_TRUST_SCORE
    trust_level = listing.broker.trust_level
    return TRUST_LEVEL_SCORE.get(trust_level, DEFAULT_TRUST_SCORE)


def _calc_image_score(listing: UnifiedListing) -> float:
    """이미지 점수 계산.

    min(이미지수 / 10 * 100, 100).
    """
    count = len(listing.images)
    return min(count / IMAGE_FULL_SCORE_COUNT * 100.0, 100.0)


def _score_single(
    listing: UnifiedListing,
    weights: ScoringWeights,
    search_params: SearchParams,
) -> UnifiedListing:
    """단일 매물에 점수 부여.

    각 항목 0~100 정규화 후 가중 평균으로 최종 점수 산출.
    """
    breakdown = {
        "station": _calc_station_score(listing),
        "price": _calc_price_score(listing, search_params),
        "area": _calc_area_score(listing, search_params),
        "age": _calc_age_score(listing),
        "broker": _calc_broker_score(listing),
        "image": _calc_image_score(listing),
    }

    # 가중 평균 계산
    weight_values = {
        "station": weights.station_distance,
        "price": weights.price,
        "area": weights.area,
        "age": weights.building_age,
        "broker": weights.broker_trust,
        "image": weights.image_count,
    }

    total_weight = sum(weight_values.values())
    if total_weight == 0:
        total_score = 0.0
    else:
        weighted_sum = sum(
            breakdown[key] * weight_values[key] for key in breakdown
        )
        total_score = weighted_sum / total_weight

    # 0~100 범위 클램핑
    total_score = max(0.0, min(100.0, round(total_score, 2)))

    scored = listing.model_copy()
    scored.score = total_score
    scored.score_breakdown = breakdown
    return scored


def score_listings(
    listings: list[UnifiedListing],
    weights: ScoringWeights,
    search_params: SearchParams,
) -> list[UnifiedListing]:
    """각 매물에 0~100 점수를 부여하고 점수 내림차순으로 정렬.

    Args:
        listings: 정규화 및 중복 제거된 매물 리스트
        weights: 스코어링 가중치
        search_params: 검색 조건 (예산 기준 등)

    Returns:
        점수가 부여된 매물 리스트 (점수 내림차순)
    """
    scored = [_score_single(listing, weights, search_params) for listing in listings]
    scored.sort(key=lambda x: x.score or 0.0, reverse=True)

    logger.info(
        "스코어링 완료",
        count=len(scored),
        top_score=scored[0].score if scored else None,
        bottom_score=scored[-1].score if scored else None,
    )
    return scored
