"""중개사 정보 모델."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class BrokerInfo(BaseModel):
    """공인중개사 정보 및 신뢰도 평가 모델."""

    name: str
    registration_no: str | None = None
    representative: str | None = None
    position: str  # "공인중개사" | "중개보조원" | "대표" 등
    opened_at: date | None = None
    status: str  # "정상영업" | "폐업" 등
    address: str | None = None

    @property
    def trust_level(self) -> str:
        """중개사 신뢰 등급 산출.

        기준:
        - 중개보조원 → danger
        - 개업 1년 미만 → low
        - 개업 3년 미만 → medium
        - 그 외 → high
        """
        if self.position == "중개보조원":
            return "danger"
        if self.opened_at and (date.today() - self.opened_at).days < 365:
            return "low"
        if self.opened_at and (date.today() - self.opened_at).days < 365 * 3:
            return "medium"
        return "high"
