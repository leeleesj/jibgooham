"""통합 매물 모델."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from jibgooham.models.broker import BrokerInfo


class UnifiedListing(BaseModel):
    """여러 플랫폼의 매물 정보를 하나로 통합한 모델."""

    id: str  # "{platform}_{platform_id}"
    platform: str  # "zigbang" | "naver" | "daangn" | "dabang"
    platform_id: str
    also_on: list[str] = []  # 중복 통합된 플랫폼 목록

    # 거래 정보
    deal_type: str  # "월세" | "전세" | "매매"
    deposit: int  # 보증금 (만원)
    monthly_rent: int | None = None

    # 위치 정보
    address: str
    latitude: float | None = None
    longitude: float | None = None
    station_name: str | None = None
    station_distance_m: int | None = None

    # 건물 정보
    area_m2: float
    floor: int | None = None  # -1 = 반지하
    building_floor: int | None = None
    room_type: str  # "원룸" | "투룸" | "오피스텔" | "아파트" | "빌라"

    # 상세 정보
    title: str
    description: str | None = None
    images: list[str] = []
    amenities: list[str] = []
    url: str

    # 메타 정보
    listed_at: datetime | None = None
    built_year: int | None = None
    building_structure: str | None = None
    land_use: str | None = None

    # 중개사 정보
    broker: BrokerInfo | None = None

    # 점수
    score: float | None = None
    score_breakdown: dict | None = None
