"""중복 제거 모듈 단위 테스트."""

from __future__ import annotations

import pytest

from jibgooham.aggregator.deduplicator import _haversine, _is_duplicate, deduplicate
from jibgooham.models.listing import UnifiedListing


# ---------------------------------------------------------------------------
# 헬퍼 — 최소 필드만 가진 UnifiedListing 생성
# ---------------------------------------------------------------------------

def _make_listing(
    platform: str = "zigbang",
    platform_id: str = "1",
    lat: float | None = 37.500,
    lng: float | None = 127.036,
    area_m2: float = 20.0,
    deposit: int = 1000,
    monthly_rent: int | None = 50,
    images: list[str] | None = None,
) -> UnifiedListing:
    """테스트용 UnifiedListing을 생성하는 헬퍼."""
    return UnifiedListing(
        id=f"{platform}_{platform_id}",
        platform=platform,
        platform_id=platform_id,
        deal_type="월세",
        deposit=deposit,
        monthly_rent=monthly_rent,
        address="서울시 강남구 역삼동",
        latitude=lat,
        longitude=lng,
        area_m2=area_m2,
        room_type="원룸",
        title="테스트 원룸",
        url=f"https://example.com/{platform}/{platform_id}",
        images=images or [],
    )


# ---------------------------------------------------------------------------
# _haversine 거리 계산 테스트
# ---------------------------------------------------------------------------

class TestHaversine:
    """Haversine 거리 계산 단위 테스트."""

    def test_동일_좌표의_거리는_0이다(self):
        dist = _haversine(37.5, 127.0, 37.5, 127.0)
        assert dist == pytest.approx(0.0, abs=1e-6)

    def test_약_111km_거리_계산이_정확하다(self):
        # 위도 1도 차이 ≈ 111km
        dist = _haversine(37.0, 127.0, 38.0, 127.0)
        assert 110_000 < dist < 112_000


# ---------------------------------------------------------------------------
# deduplicate 테스트
# ---------------------------------------------------------------------------

class TestDeduplicate:
    """deduplicate 함수 단위 테스트."""

    def test_빈_리스트는_빈_리스트를_반환한다(self):
        result = deduplicate([])
        assert result == []

    def test_중복_없는_매물은_그대로_반환된다(self):
        """서로 멀리 떨어진 매물은 중복 없이 그대로 반환."""
        listings = [
            _make_listing(platform="zigbang", platform_id="1", lat=37.500, lng=127.036),
            # 위도 0.01도 ≈ 1.1km → 20m 임계값을 훨씬 초과
            _make_listing(platform="naver", platform_id="2", lat=37.510, lng=127.036),
        ]
        result = deduplicate(listings)
        assert len(result) == 2

    def test_같은_위치_면적_가격의_매물이_1개로_병합된다(self):
        """동일 조건의 매물 2개가 1개로 병합된다."""
        listings = [
            _make_listing(platform="zigbang", platform_id="1", lat=37.500, lng=127.036),
            _make_listing(platform="naver", platform_id="2", lat=37.500, lng=127.036),
        ]
        result = deduplicate(listings)
        assert len(result) == 1

    def test_병합시_also_on에_다른_플랫폼이_채워진다(self):
        """중복 병합 후 대표 매물의 also_on에 다른 플랫폼명이 추가된다."""
        listings = [
            _make_listing(platform="zigbang", platform_id="1", lat=37.500, lng=127.036),
            _make_listing(platform="naver", platform_id="2", lat=37.500, lng=127.036),
        ]
        result = deduplicate(listings)
        rep = result[0]
        # 대표 플랫폼과 also_on을 합치면 두 플랫폼이 모두 포함
        all_platforms = {rep.platform} | set(rep.also_on)
        assert "zigbang" in all_platforms
        assert "naver" in all_platforms

    def test_이미지_많은_매물이_대표로_선택된다(self):
        """이미지가 더 많은 매물이 대표 매물로 선택된다."""
        listings = [
            _make_listing(
                platform="zigbang",
                platform_id="1",
                lat=37.500,
                lng=127.036,
                images=["img1.jpg"],
            ),
            _make_listing(
                platform="naver",
                platform_id="2",
                lat=37.500,
                lng=127.036,
                images=["img1.jpg", "img2.jpg", "img3.jpg"],
            ),
        ]
        result = deduplicate(listings)
        assert len(result) == 1
        # 이미지 3개짜리 naver가 대표로 선택됨
        assert result[0].platform == "naver"
        assert len(result[0].images) == 3

    def test_위경도_None인_매물은_중복_비교에서_제외된다(self):
        """위경도가 None인 매물은 중복 비교 대상에 포함되지 않고 그대로 결과에 추가된다."""
        listings = [
            _make_listing(platform="zigbang", platform_id="1", lat=37.500, lng=127.036),
            _make_listing(platform="naver", platform_id="2", lat=None, lng=None),
        ]
        result = deduplicate(listings)
        # 각각 독립적으로 유지됨
        assert len(result) == 2

    def test_위경도_None인_매물끼리는_중복_판정_안됨(self):
        """위경도 None 매물 여러 개가 모두 결과에 포함된다."""
        listings = [
            _make_listing(platform="zigbang", platform_id="1", lat=None, lng=None),
            _make_listing(platform="naver", platform_id="2", lat=None, lng=None),
        ]
        result = deduplicate(listings)
        assert len(result) == 2

    def test_20m_초과_거리는_별개_매물로_유지된다(self):
        """20m를 초과하는 거리의 매물은 중복으로 판정하지 않는다."""
        # 위도 0.001도 ≈ 111m → 20m 초과
        listings = [
            _make_listing(platform="zigbang", platform_id="1", lat=37.5000, lng=127.036),
            _make_listing(platform="naver", platform_id="2", lat=37.5010, lng=127.036),
        ]
        result = deduplicate(listings)
        assert len(result) == 2

    def test_면적_오차_5퍼센트_초과시_별개_매물로_유지된다(self):
        """면적 차이가 5%를 초과하면 별개 매물로 판정한다."""
        # 20.0 vs 21.1 → 오차 5.5% → 별개
        listings = [
            _make_listing(platform="zigbang", platform_id="1", lat=37.500, lng=127.036, area_m2=20.0),
            _make_listing(platform="naver", platform_id="2", lat=37.500, lng=127.036, area_m2=21.1),
        ]
        result = deduplicate(listings)
        assert len(result) == 2

    def test_면적_오차_5퍼센트_이내는_중복으로_판정된다(self):
        """면적 차이가 5% 이내이면 중복으로 판정한다."""
        # 20.0 vs 20.5 → 오차 2.5% → 중복
        listings = [
            _make_listing(platform="zigbang", platform_id="1", lat=37.500, lng=127.036, area_m2=20.0),
            _make_listing(platform="naver", platform_id="2", lat=37.500, lng=127.036, area_m2=20.5),
        ]
        result = deduplicate(listings)
        assert len(result) == 1

    def test_보증금이_다르면_별개_매물로_유지된다(self):
        """보증금이 다르면 중복으로 판정하지 않는다."""
        listings = [
            _make_listing(platform="zigbang", platform_id="1", lat=37.500, lng=127.036, deposit=1000),
            _make_listing(platform="naver", platform_id="2", lat=37.500, lng=127.036, deposit=2000),
        ]
        result = deduplicate(listings)
        assert len(result) == 2

    def test_월세가_다르면_별개_매물로_유지된다(self):
        """월세가 다르면 중복으로 판정하지 않는다."""
        listings = [
            _make_listing(platform="zigbang", platform_id="1", lat=37.500, lng=127.036, monthly_rent=50),
            _make_listing(platform="naver", platform_id="2", lat=37.500, lng=127.036, monthly_rent=60),
        ]
        result = deduplicate(listings)
        assert len(result) == 2

    def test_단일_매물은_그대로_반환된다(self):
        """매물이 1개면 그대로 반환된다."""
        listings = [_make_listing()]
        result = deduplicate(listings)
        assert len(result) == 1

    def test_3개_중복_매물이_1개로_병합된다(self):
        """3개 플랫폼의 동일 매물이 1개로 병합된다."""
        listings = [
            _make_listing(platform="zigbang", platform_id="1", lat=37.500, lng=127.036),
            _make_listing(platform="naver", platform_id="2", lat=37.500, lng=127.036),
            _make_listing(platform="daangn", platform_id="3", lat=37.500, lng=127.036),
        ]
        result = deduplicate(listings)
        assert len(result) == 1
        all_platforms = {result[0].platform} | set(result[0].also_on)
        assert len(all_platforms) == 3
