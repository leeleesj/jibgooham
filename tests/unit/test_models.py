"""Pydantic 모델 단위 테스트."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from pydantic import ValidationError

from jibgooham.models.broker import BrokerInfo
from jibgooham.models.listing import UnifiedListing
from jibgooham.models.search_params import SearchParams, ScoringWeights


# ---------------------------------------------------------------------------
# UnifiedListing 테스트
# ---------------------------------------------------------------------------


class TestUnifiedListingRequired:
    """UnifiedListing 필수 필드만으로 생성하는 케이스."""

    def test_필수_필드만으로_생성_성공(self):
        """필수 필드만 전달했을 때 인스턴스가 정상 생성되어야 한다."""
        listing = UnifiedListing(
            id="zigbang_123",
            platform="zigbang",
            platform_id="123",
            deal_type="월세",
            deposit=500,
            address="서울특별시 마포구 합정동 1-1",
            area_m2=33.0,
            room_type="원룸",
            title="합정역 도보 5분 원룸",
            url="https://zigbang.com/room/123",
        )
        assert listing.id == "zigbang_123"
        assert listing.platform == "zigbang"
        assert listing.deposit == 500
        # 선택 필드 기본값 확인
        assert listing.also_on == []
        assert listing.images == []
        assert listing.amenities == []
        assert listing.monthly_rent is None
        assert listing.broker is None
        assert listing.score is None

    def test_기본값_리스트_필드는_빈_리스트(self):
        """also_on, images, amenities 는 기본값이 빈 리스트여야 한다."""
        listing = UnifiedListing(
            id="naver_1",
            platform="naver",
            platform_id="1",
            deal_type="전세",
            deposit=10000,
            address="서울 강남구",
            area_m2=50.0,
            room_type="오피스텔",
            title="강남 오피스텔",
            url="https://naver.com/1",
        )
        assert isinstance(listing.also_on, list)
        assert isinstance(listing.images, list)
        assert isinstance(listing.amenities, list)


class TestUnifiedListingFull:
    """UnifiedListing 전체 필드 생성 케이스."""

    def test_전체_필드로_생성_성공(self):
        """모든 필드를 전달했을 때 인스턴스가 정상 생성되어야 한다."""
        broker = BrokerInfo(
            name="행복부동산",
            position="공인중개사",
            status="정상영업",
            opened_at=date(2018, 3, 1),
        )
        listing = UnifiedListing(
            id="zigbang_999",
            platform="zigbang",
            platform_id="999",
            also_on=["naver"],
            deal_type="월세",
            deposit=1000,
            monthly_rent=70,
            address="서울특별시 마포구",
            latitude=37.5,
            longitude=126.9,
            station_name="합정역",
            station_distance_m=300,
            area_m2=26.4,
            floor=3,
            building_floor=10,
            room_type="원룸",
            title="합정 신축 원룸",
            description="채광 좋음",
            images=["https://img.com/1.jpg"],
            amenities=["에어컨", "냉장고"],
            url="https://zigbang.com/room/999",
            listed_at=datetime(2024, 1, 15, 12, 0, 0),
            built_year=2020,
            building_structure="철근콘크리트",
            land_use="제2종 일반주거지역",
            broker=broker,
            score=85.5,
            score_breakdown={"price": 90.0, "area": 80.0},
        )
        assert listing.also_on == ["naver"]
        assert listing.monthly_rent == 70
        assert listing.station_name == "합정역"
        assert listing.broker.name == "행복부동산"
        assert listing.score == 85.5
        assert listing.score_breakdown["price"] == 90.0


class TestUnifiedListingValidation:
    """UnifiedListing 유효성 검증 실패 케이스."""

    def test_필수_필드_누락시_ValidationError(self):
        """필수 필드(id)가 없으면 ValidationError가 발생해야 한다."""
        with pytest.raises(ValidationError):
            UnifiedListing(
                # id 누락
                platform="zigbang",
                platform_id="123",
                deal_type="월세",
                deposit=500,
                address="서울",
                area_m2=33.0,
                room_type="원룸",
                title="테스트",
                url="https://example.com",
            )

    def test_잘못된_타입_deposit_문자열(self):
        """deposit에 숫자로 변환 불가능한 문자열을 넣으면 ValidationError가 발생해야 한다."""
        with pytest.raises(ValidationError):
            UnifiedListing(
                id="zigbang_1",
                platform="zigbang",
                platform_id="1",
                deal_type="월세",
                deposit="만원",  # 숫자가 아닌 문자열
                address="서울",
                area_m2=33.0,
                room_type="원룸",
                title="테스트",
                url="https://example.com",
            )

    def test_area_m2_필수_필드_누락시_ValidationError(self):
        """area_m2 누락 시 ValidationError가 발생해야 한다."""
        with pytest.raises(ValidationError):
            UnifiedListing(
                id="zigbang_2",
                platform="zigbang",
                platform_id="2",
                deal_type="월세",
                deposit=500,
                address="서울",
                # area_m2 누락
                room_type="원룸",
                title="테스트",
                url="https://example.com",
            )


# ---------------------------------------------------------------------------
# SearchParams 테스트
# ---------------------------------------------------------------------------


class TestSearchParamsDefaults:
    """SearchParams 기본값 확인."""

    def test_기본값_deal_type(self):
        """deal_type 기본값은 '월세'이어야 한다."""
        params = SearchParams(region="서울 마포구")
        assert params.deal_type == "월세"

    def test_기본값_room_type(self):
        """room_type 기본값은 '원룸'이어야 한다."""
        params = SearchParams(region="서울 마포구")
        assert params.room_type == "원룸"

    def test_기본값_deposit_범위(self):
        """보증금 범위 기본값이 0~100,000 이어야 한다."""
        params = SearchParams(region="서울 마포구")
        assert params.deposit_min == 0
        assert params.deposit_max == 100_000

    def test_기본값_rent_범위(self):
        """월세 범위 기본값이 0~200 이어야 한다."""
        params = SearchParams(region="서울 마포구")
        assert params.rent_min == 0
        assert params.rent_max == 200

    def test_기본값_area_범위(self):
        """면적 범위 기본값이 0~200 이어야 한다."""
        params = SearchParams(region="서울 마포구")
        assert params.area_min == 0
        assert params.area_max == 200

    def test_기본값_limit(self):
        """limit 기본값은 30이어야 한다."""
        params = SearchParams(region="서울 마포구")
        assert params.limit == 30

    def test_기본값_platforms_지원_플랫폼_포함(self):
        """platforms 기본값에 4개 플랫폼이 모두 포함되어야 한다."""
        params = SearchParams(region="서울 마포구")
        assert "zigbang" in params.platforms
        assert "naver" in params.platforms
        assert "daangn" in params.platforms
        assert "dabang" in params.platforms

    def test_기본값_weights_인스턴스(self):
        """weights 기본값은 ScoringWeights 인스턴스이어야 한다."""
        params = SearchParams(region="서울 마포구")
        assert isinstance(params.weights, ScoringWeights)


# ---------------------------------------------------------------------------
# ScoringWeights 테스트
# ---------------------------------------------------------------------------


class TestScoringWeightsDefaults:
    """ScoringWeights 기본값 확인."""

    def test_station_distance_기본값(self):
        """station_distance 기본값은 1.5이어야 한다."""
        weights = ScoringWeights()
        assert weights.station_distance == 1.5

    def test_price_기본값(self):
        """price 기본값은 1.5이어야 한다."""
        weights = ScoringWeights()
        assert weights.price == 1.5

    def test_area_기본값(self):
        """area 기본값은 1.0이어야 한다."""
        weights = ScoringWeights()
        assert weights.area == 1.0

    def test_building_age_기본값(self):
        """building_age 기본값은 1.0이어야 한다."""
        weights = ScoringWeights()
        assert weights.building_age == 1.0

    def test_broker_trust_기본값(self):
        """broker_trust 기본값은 1.5이어야 한다."""
        weights = ScoringWeights()
        assert weights.broker_trust == 1.5

    def test_image_count_기본값(self):
        """image_count 기본값은 0.3이어야 한다."""
        weights = ScoringWeights()
        assert weights.image_count == 0.3


# ---------------------------------------------------------------------------
# BrokerInfo trust_level 테스트
# ---------------------------------------------------------------------------


class TestBrokerTrustLevel:
    """BrokerInfo.trust_level 프로퍼티 테스트."""

    def _make_broker(self, position: str, opened_at: date | None) -> BrokerInfo:
        """테스트용 BrokerInfo 헬퍼."""
        return BrokerInfo(
            name="테스트 중개소",
            position=position,
            status="정상영업",
            opened_at=opened_at,
        )

    def test_중개보조원은_danger(self):
        """position이 '중개보조원'이면 trust_level은 'danger'이어야 한다."""
        broker = self._make_broker("중개보조원", date(2015, 1, 1))
        assert broker.trust_level == "danger"

    def test_중개보조원_opened_at_없어도_danger(self):
        """'중개보조원'은 opened_at 무관하게 'danger'이어야 한다."""
        broker = self._make_broker("중개보조원", None)
        assert broker.trust_level == "danger"

    def test_개업_1년_미만은_low(self):
        """개업일로부터 1년이 안 된 경우 trust_level은 'low'이어야 한다."""
        # 오늘 기준 6개월 전 개업
        six_months_ago = date.today().replace(year=date.today().year if date.today().month > 6
                                              else date.today().year - 1)
        # 간단히: 오늘로부터 100일 전
        from datetime import timedelta
        recent = date.today() - timedelta(days=100)
        broker = self._make_broker("공인중개사", recent)
        assert broker.trust_level == "low"

    def test_개업_1년_이상_3년_미만은_medium(self):
        """개업 1~3년 사이이면 trust_level은 'medium'이어야 한다."""
        from datetime import timedelta
        two_years_ago = date.today() - timedelta(days=365 * 2)
        broker = self._make_broker("공인중개사", two_years_ago)
        assert broker.trust_level == "medium"

    def test_개업_3년_초과는_high(self):
        """개업 3년 초과이면 trust_level은 'high'이어야 한다."""
        from datetime import timedelta
        four_years_ago = date.today() - timedelta(days=365 * 4)
        broker = self._make_broker("공인중개사", four_years_ago)
        assert broker.trust_level == "high"

    def test_opened_at이_None이면_high(self):
        """opened_at이 None이면 trust_level은 'high'이어야 한다."""
        broker = self._make_broker("공인중개사", None)
        assert broker.trust_level == "high"

    def test_대표_직함도_opened_at_기준으로_판단(self):
        """'대표' 직함도 opened_at 기준으로 신뢰 등급이 결정되어야 한다."""
        from datetime import timedelta
        old_date = date.today() - timedelta(days=365 * 5)
        broker = self._make_broker("대표", old_date)
        assert broker.trust_level == "high"
