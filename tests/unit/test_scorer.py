"""스코어링 모듈 단위 테스트."""

from __future__ import annotations

from datetime import date

import pytest

from jibgooham.aggregator.scorer import (
    CURRENT_YEAR,
    _calc_age_score,
    _calc_broker_score,
    _calc_image_score,
    _calc_station_score,
    score_listings,
)
from jibgooham.models.broker import BrokerInfo
from jibgooham.models.listing import UnifiedListing
from jibgooham.models.search_params import ScoringWeights, SearchParams


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _make_listing(
    platform: str = "zigbang",
    platform_id: str = "1",
    deposit: int = 5000,
    monthly_rent: int | None = 50,
    area_m2: float = 20.0,
    built_year: int | None = None,
    station_distance_m: int | None = None,
    images: list[str] | None = None,
    broker: BrokerInfo | None = None,
) -> UnifiedListing:
    """테스트용 UnifiedListing을 생성하는 헬퍼."""
    return UnifiedListing(
        id=f"{platform}_{platform_id}",
        platform=platform,
        platform_id=platform_id,
        deal_type="월세",
        deposit=deposit,
        monthly_rent=monthly_rent,
        address="서울시 강남구",
        latitude=37.500,
        longitude=127.036,
        area_m2=area_m2,
        room_type="원룸",
        title="테스트 원룸",
        url=f"https://example.com/{platform}/{platform_id}",
        built_year=built_year,
        station_distance_m=station_distance_m,
        images=images or [],
        broker=broker,
    )


def _default_weights() -> ScoringWeights:
    """기본 가중치를 반환하는 헬퍼."""
    return ScoringWeights()


def _default_search_params(deposit_max: int = 10_000, area_max: float = 50.0) -> SearchParams:
    """기본 검색 조건을 반환하는 헬퍼."""
    return SearchParams(
        region="서울 강남구",
        deposit_max=deposit_max,
        area_max=area_max,
    )


# ---------------------------------------------------------------------------
# 개별 점수 계산 함수 테스트
# ---------------------------------------------------------------------------

class TestCalcStationScore:
    """역 거리 점수 계산 테스트."""

    def test_역_거리_없으면_50점이다(self):
        listing = _make_listing(station_distance_m=None)
        assert _calc_station_score(listing) == pytest.approx(50.0)

    def test_역_거리_0m는_100점이다(self):
        listing = _make_listing(station_distance_m=0)
        assert _calc_station_score(listing) == pytest.approx(100.0)

    def test_역_거리_500m는_50점이다(self):
        # 100 - 500 / 10 = 50
        listing = _make_listing(station_distance_m=500)
        assert _calc_station_score(listing) == pytest.approx(50.0)

    def test_역_거리_1500m는_0점이다(self):
        # max(0, 100 - 1500/10) = max(0, -50) = 0
        listing = _make_listing(station_distance_m=1500)
        assert _calc_station_score(listing) == pytest.approx(0.0)

    def test_가까운_역이_먼_역보다_높은_점수다(self):
        close = _make_listing(station_distance_m=100)
        far = _make_listing(station_distance_m=800)
        assert _calc_station_score(close) > _calc_station_score(far)


class TestCalcAgeScore:
    """건축연도 점수 계산 테스트."""

    def test_built_year_없으면_50점이다(self):
        listing = _make_listing(built_year=None)
        assert _calc_age_score(listing) == pytest.approx(50.0)

    def test_신축_당해연도는_100점이다(self):
        listing = _make_listing(built_year=CURRENT_YEAR)
        assert _calc_age_score(listing) == pytest.approx(100.0)

    def test_30년_이상_노후는_0점이다(self):
        listing = _make_listing(built_year=CURRENT_YEAR - 30)
        assert _calc_age_score(listing) == pytest.approx(0.0)

    def test_신축이_구축보다_높은_점수다(self):
        new_listing = _make_listing(built_year=CURRENT_YEAR - 2)
        old_listing = _make_listing(built_year=CURRENT_YEAR - 20)
        assert _calc_age_score(new_listing) > _calc_age_score(old_listing)


class TestCalcBrokerScore:
    """중개사 신뢰도 점수 계산 테스트."""

    def test_중개사_없으면_50점이다(self):
        listing = _make_listing(broker=None)
        assert _calc_broker_score(listing) == pytest.approx(50.0)

    def test_trust_level_danger는_0점이다(self):
        """중개보조원(danger) 신뢰등급은 0점."""
        broker = BrokerInfo(
            name="테스트 중개사",
            position="중개보조원",  # danger 등급
            status="정상영업",
        )
        listing = _make_listing(broker=broker)
        assert _calc_broker_score(listing) == pytest.approx(0.0)

    def test_trust_level_high는_100점이다(self):
        """3년 이상 경력 공인중개사는 high(100점)."""
        # 5년 전 개업
        opened = date(date.today().year - 5, 1, 1)
        broker = BrokerInfo(
            name="베테랑 중개사",
            position="공인중개사",
            opened_at=opened,
            status="정상영업",
        )
        listing = _make_listing(broker=broker)
        assert _calc_broker_score(listing) == pytest.approx(100.0)

    def test_trust_level_medium은_70점이다(self):
        """1~3년 경력 중개사는 medium(70점)."""
        # 2년 전 개업
        opened = date(date.today().year - 2, 1, 1)
        broker = BrokerInfo(
            name="중견 중개사",
            position="공인중개사",
            opened_at=opened,
            status="정상영업",
        )
        listing = _make_listing(broker=broker)
        assert _calc_broker_score(listing) == pytest.approx(70.0)

    def test_trust_level_low는_40점이다(self):
        """1년 미만 경력 중개사는 low(40점)."""
        # 6개월 전 개업
        from datetime import timedelta
        opened = date.today() - timedelta(days=180)
        broker = BrokerInfo(
            name="신규 중개사",
            position="공인중개사",
            opened_at=opened,
            status="정상영업",
        )
        listing = _make_listing(broker=broker)
        assert _calc_broker_score(listing) == pytest.approx(40.0)


class TestCalcImageScore:
    """이미지 점수 계산 테스트."""

    def test_이미지_없으면_0점이다(self):
        listing = _make_listing(images=[])
        assert _calc_image_score(listing) == pytest.approx(0.0)

    def test_이미지_10개는_100점이다(self):
        images = [f"img{i}.jpg" for i in range(10)]
        listing = _make_listing(images=images)
        assert _calc_image_score(listing) == pytest.approx(100.0)

    def test_이미지_10개_초과도_100점_상한이다(self):
        images = [f"img{i}.jpg" for i in range(15)]
        listing = _make_listing(images=images)
        assert _calc_image_score(listing) == pytest.approx(100.0)

    def test_이미지_5개는_50점이다(self):
        images = [f"img{i}.jpg" for i in range(5)]
        listing = _make_listing(images=images)
        assert _calc_image_score(listing) == pytest.approx(50.0)

    def test_이미지_많을수록_높은_점수다(self):
        few_images = _make_listing(images=["img1.jpg", "img2.jpg"])
        many_images = _make_listing(images=[f"img{i}.jpg" for i in range(8)])
        assert _calc_image_score(many_images) > _calc_image_score(few_images)


# ---------------------------------------------------------------------------
# score_listings 통합 테스트
# ---------------------------------------------------------------------------

class TestScoreListings:
    """score_listings 함수 통합 테스트."""

    def test_빈_리스트는_빈_리스트를_반환한다(self):
        result = score_listings([], _default_weights(), _default_search_params())
        assert result == []

    def test_각_매물에_score가_부여된다(self):
        listings = [
            _make_listing(platform_id="1"),
            _make_listing(platform_id="2"),
        ]
        result = score_listings(listings, _default_weights(), _default_search_params())
        assert all(r.score is not None for r in result)
        assert all(0.0 <= r.score <= 100.0 for r in result)

    def test_score_breakdown_dict이_존재한다(self):
        listings = [_make_listing()]
        result = score_listings(listings, _default_weights(), _default_search_params())
        breakdown = result[0].score_breakdown
        assert isinstance(breakdown, dict)
        assert "station" in breakdown
        assert "price" in breakdown
        assert "area" in breakdown
        assert "age" in breakdown
        assert "broker" in breakdown
        assert "image" in breakdown

    def test_점수가_내림차순으로_정렬된다(self):
        """점수 내림차순 정렬 확인."""
        # 역 근접 매물 vs 먼 매물
        listings = [
            _make_listing(platform_id="far", station_distance_m=1000),
            _make_listing(platform_id="close", station_distance_m=50),
        ]
        result = score_listings(listings, _default_weights(), _default_search_params())
        scores = [r.score for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_역_가까운_매물이_높은_점수다(self):
        """역 거리가 가까울수록 높은 최종 점수."""
        close = _make_listing(platform_id="close", station_distance_m=100)
        far = _make_listing(platform_id="far", station_distance_m=900)
        result = score_listings([close, far], _default_weights(), _default_search_params())
        # 첫 번째가 가장 높은 점수
        assert result[0].platform_id == "close"

    def test_신축_매물이_구축보다_높은_점수다(self):
        """준공연도가 최근일수록 높은 점수."""
        new_listing = _make_listing(platform_id="new", built_year=CURRENT_YEAR - 1)
        old_listing = _make_listing(platform_id="old", built_year=CURRENT_YEAR - 25)
        result = score_listings([new_listing, old_listing], _default_weights(), _default_search_params())
        assert result[0].platform_id == "new"

    def test_broker_danger는_낮은_점수를_받는다(self):
        """중개보조원(danger) 매물의 broker_score는 0이다."""
        danger_broker = BrokerInfo(
            name="위험 중개사",
            position="중개보조원",
            status="정상영업",
        )
        listing = _make_listing(broker=danger_broker)
        result = score_listings([listing], _default_weights(), _default_search_params())
        assert result[0].score_breakdown["broker"] == pytest.approx(0.0)

    def test_이미지_많은_매물이_높은_image_score를_받는다(self):
        """이미지가 많을수록 image_score가 높다."""
        few = _make_listing(platform_id="few", images=["img1.jpg"])
        many = _make_listing(platform_id="many", images=[f"img{i}.jpg" for i in range(10)])
        result_few = score_listings([few], _default_weights(), _default_search_params())
        result_many = score_listings([many], _default_weights(), _default_search_params())
        assert result_many[0].score_breakdown["image"] > result_few[0].score_breakdown["image"]

    def test_단일_매물도_정상_처리된다(self):
        listing = _make_listing()
        result = score_listings([listing], _default_weights(), _default_search_params())
        assert len(result) == 1
        assert result[0].score is not None

    def test_예산_초과_매물은_price_score가_0이다(self):
        """보증금이 deposit_max를 초과하면 price_score = 0."""
        # deposit=15000, deposit_max=10000 → 예산 초과
        listing = _make_listing(deposit=15_000)
        params = _default_search_params(deposit_max=10_000)
        result = score_listings([listing], _default_weights(), params)
        assert result[0].score_breakdown["price"] == pytest.approx(0.0)
