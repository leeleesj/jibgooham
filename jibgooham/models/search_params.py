"""검색 파라미터 및 스코어링 가중치 모델."""

from __future__ import annotations

from pydantic import BaseModel

from jibgooham.config import SUPPORTED_PLATFORMS


class ScoringWeights(BaseModel):
    """매물 점수 산출 시 각 항목의 가중치."""

    station_distance: float = 1.5
    price: float = 1.5
    area: float = 1.0
    building_age: float = 1.0
    broker_trust: float = 1.5
    image_count: float = 0.3


class SearchParams(BaseModel):
    """매물 검색 조건."""

    region: str
    deal_type: str = "월세"
    room_type: str = "원룸"

    # 보증금 범위 (만원)
    deposit_min: int = 0
    deposit_max: int = 100_000

    # 월세 범위 (만원)
    rent_min: int = 0
    rent_max: int = 200

    # 면적 범위 (m²)
    area_min: float = 0
    area_max: float = 200

    # 검색 대상 플랫폼
    platforms: list[str] = SUPPORTED_PLATFORMS

    # 결과 개수 제한
    limit: int = 30

    # 스코어링 가중치
    weights: ScoringWeights = ScoringWeights()
