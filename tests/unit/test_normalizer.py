"""정규화 모듈 단위 테스트."""

from __future__ import annotations

import pytest

from jibgooham.aggregator.normalizer import (
    _parse_floor,
    normalize,
    normalize_dabang,
    normalize_daangn,
    normalize_naver,
    normalize_zigbang,
)
from jibgooham.models.listing import UnifiedListing


# ---------------------------------------------------------------------------
# 헬퍼 — 최소 필드만 가진 직방 raw dict
# ---------------------------------------------------------------------------

def _zigbang_raw(**overrides) -> dict:
    """직방 최소 raw 딕셔너리를 생성하는 헬퍼."""
    base = {
        "item_id": "123",
        "sales_type": "rent",
        "deposit": 1000,
        "rent": 50,
        "address": "서울시 강남구 역삼동",
        "lat": 37.500,
        "lng": 127.036,
        "service_type": "01",
        "exclusive_area": 20.0,
        "floor": "3",
        "building_floor": 5,
        "title": "역삼동 원룸",
        "images_thumbnail": ["http://img.example.com/1.jpg"],
    }
    base.update(overrides)
    return base


def _naver_raw(**overrides) -> dict:
    """네이버 최소 raw 딕셔너리를 생성하는 헬퍼."""
    base = {
        "articleNo": "987",
        "tradeTypeCode": "B2",
        "dealOrWarrantPrc": 500,
        "rentPrc": 80,
        "area2": 33.0,
        "floorInfo": "2/10",
        "articleName": "강남 오피스텔",
        "latitude": 37.501,
        "longitude": 127.037,
        "realEstateTypeCode": "OPST",
        "representativeImgUrl": "http://img.naver.com/1.jpg",
        "articleConfirmYmd": "2024-01-15",
    }
    base.update(overrides)
    return base


def _daangn_raw(**overrides) -> dict:
    """당근마켓 최소 raw 딕셔너리를 생성하는 헬퍼."""
    base = {
        "id": "555",
        "deal_type": "월세",
        "deposit": 300,
        "monthly_rent": 40,
        "address": "서울시 마포구",
        "lat": 37.550,
        "lng": 126.920,
        "exclusive_area": 15.0,
        "floor": "2",
        "room_type": "원룸",
        "title": "마포구 원룸",
        "images": ["http://img.daangn.com/1.jpg"],
        "created_at": "2024-03-01",
    }
    base.update(overrides)
    return base


def _dabang_raw(**overrides) -> dict:
    """다방 최소 raw 딕셔너리를 생성하는 헬퍼."""
    base = {
        "id": "777",
        "selling_type": 0,
        "deposit": 500,
        "price": 60,
        "address": "서울시 송파구",
        "lat": 37.510,
        "lng": 127.100,
        "exclusive_area": 25.0,
        "floor": "4",
        "room_type": "원룸",
        "title": "송파구 원룸",
        "images": ["http://img.dabang.com/1.jpg"],
        "approve_date": "2015-06-01",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# _parse_floor 층수 파싱 테스트
# ---------------------------------------------------------------------------

class TestParseFloor:
    """층수 파싱 단위 테스트."""

    def test_반지하는_마이너스1을_반환한다(self):
        assert _parse_floor("반지하") == -1

    def test_지하는_마이너스1을_반환한다(self):
        assert _parse_floor("지하") == -1

    def test_옥탑은_999를_반환한다(self):
        assert _parse_floor("옥탑") == 999

    def test_숫자_문자열은_int로_변환된다(self):
        assert _parse_floor("3") == 3

    def test_정수_입력은_그대로_반환된다(self):
        assert _parse_floor(5) == 5

    def test_None은_None을_반환한다(self):
        assert _parse_floor(None) is None

    def test_빈_문자열은_None을_반환한다(self):
        assert _parse_floor("") is None


# ---------------------------------------------------------------------------
# normalize_zigbang 테스트
# ---------------------------------------------------------------------------

class TestNormalizeZigbang:
    """직방 정규화 테스트."""

    def test_정상_변환시_UnifiedListing이_반환된다(self):
        raw = _zigbang_raw()
        result = normalize_zigbang(raw)

        assert isinstance(result, UnifiedListing)
        assert result.id == "zigbang_123"
        assert result.platform == "zigbang"
        assert result.platform_id == "123"

    def test_거래_유형이_월세로_변환된다(self):
        raw = _zigbang_raw(sales_type="rent")
        result = normalize_zigbang(raw)
        assert result.deal_type == "월세"

    def test_거래_유형이_전세로_변환된다(self):
        raw = _zigbang_raw(sales_type="jeonse")
        result = normalize_zigbang(raw)
        assert result.deal_type == "전세"

    def test_방_유형이_원룸으로_변환된다(self):
        raw = _zigbang_raw(service_type="01")
        result = normalize_zigbang(raw)
        assert result.room_type == "원룸"

    def test_방_유형이_오피스텔로_변환된다(self):
        raw = _zigbang_raw(service_type="05")
        result = normalize_zigbang(raw)
        assert result.room_type == "오피스텔"

    def test_보증금과_월세가_올바르게_파싱된다(self):
        raw = _zigbang_raw(deposit=1000, rent=50)
        result = normalize_zigbang(raw)
        assert result.deposit == 1000
        assert result.monthly_rent == 50

    def test_위경도가_올바르게_파싱된다(self):
        raw = _zigbang_raw(lat=37.5, lng=127.0)
        result = normalize_zigbang(raw)
        assert result.latitude == pytest.approx(37.5)
        assert result.longitude == pytest.approx(127.0)

    def test_이미지_목록이_리스트로_변환된다(self):
        raw = _zigbang_raw(images_thumbnail=["img1.jpg", "img2.jpg"])
        result = normalize_zigbang(raw)
        assert len(result.images) == 2

    def test_준공연도가_파싱된다(self):
        raw = _zigbang_raw(approve_date="2010-05-01")
        result = normalize_zigbang(raw)
        assert result.built_year == 2010

    def test_URL에_item_id가_포함된다(self):
        raw = _zigbang_raw(item_id="999")
        result = normalize_zigbang(raw)
        assert "999" in result.url

    def test_층수가_올바르게_파싱된다(self):
        raw = _zigbang_raw(floor="3")
        result = normalize_zigbang(raw)
        assert result.floor == 3

    def test_반지하_층수가_마이너스1로_파싱된다(self):
        raw = _zigbang_raw(floor="반지하")
        result = normalize_zigbang(raw)
        assert result.floor == -1


# ---------------------------------------------------------------------------
# normalize_naver 테스트
# ---------------------------------------------------------------------------

class TestNormalizeNaver:
    """네이버 부동산 정규화 테스트."""

    def test_정상_변환시_UnifiedListing이_반환된다(self):
        raw = _naver_raw()
        result = normalize_naver(raw)

        assert isinstance(result, UnifiedListing)
        assert result.id == "naver_987"
        assert result.platform == "naver"

    def test_거래_유형_코드_B2가_월세로_변환된다(self):
        raw = _naver_raw(tradeTypeCode="B2")
        result = normalize_naver(raw)
        assert result.deal_type == "월세"

    def test_거래_유형_코드_B1이_전세로_변환된다(self):
        raw = _naver_raw(tradeTypeCode="B1")
        result = normalize_naver(raw)
        assert result.deal_type == "전세"

    def test_거래_유형_코드_A1이_매매로_변환된다(self):
        raw = _naver_raw(tradeTypeCode="A1")
        result = normalize_naver(raw)
        assert result.deal_type == "매매"

    def test_floorInfo_슬래시_형식이_파싱된다(self):
        # "3/5" → floor=3, building_floor=5
        raw = _naver_raw(floorInfo="3/5")
        result = normalize_naver(raw)
        assert result.floor == 3
        assert result.building_floor == 5

    def test_realEstateTypeCode_OPST가_오피스텔로_변환된다(self):
        raw = _naver_raw(realEstateTypeCode="OPST")
        result = normalize_naver(raw)
        assert result.room_type == "오피스텔"

    def test_realEstateTypeCode_OR이_원룸으로_변환된다(self):
        raw = _naver_raw(realEstateTypeCode="OR")
        result = normalize_naver(raw)
        assert result.room_type == "원룸"

    def test_보증금이_올바르게_파싱된다(self):
        raw = _naver_raw(dealOrWarrantPrc=5000)
        result = normalize_naver(raw)
        assert result.deposit == 5000

    def test_대표이미지가_리스트로_변환된다(self):
        raw = _naver_raw(representativeImgUrl="http://img.example.com/main.jpg")
        result = normalize_naver(raw)
        assert "http://img.example.com/main.jpg" in result.images

    def test_준공연도가_buildYear에서_파싱된다(self):
        raw = _naver_raw(buildYear="2018")
        result = normalize_naver(raw)
        assert result.built_year == 2018

    def test_URL에_articleNo가_포함된다(self):
        raw = _naver_raw(articleNo="12345")
        result = normalize_naver(raw)
        assert "12345" in result.url


# ---------------------------------------------------------------------------
# normalize_daangn 테스트
# ---------------------------------------------------------------------------

class TestNormalizeDaangn:
    """당근마켓 정규화 테스트."""

    def test_정상_변환시_UnifiedListing이_반환된다(self):
        raw = _daangn_raw()
        result = normalize_daangn(raw)

        assert isinstance(result, UnifiedListing)
        assert result.id == "daangn_555"
        assert result.platform == "daangn"

    def test_거래_유형이_그대로_전달된다(self):
        raw = _daangn_raw(deal_type="전세")
        result = normalize_daangn(raw)
        assert result.deal_type == "전세"

    def test_보증금과_월세가_올바르게_파싱된다(self):
        raw = _daangn_raw(deposit=200, monthly_rent=35)
        result = normalize_daangn(raw)
        assert result.deposit == 200
        assert result.monthly_rent == 35

    def test_위경도가_올바르게_파싱된다(self):
        raw = _daangn_raw(lat=37.55, lng=126.92)
        result = normalize_daangn(raw)
        assert result.latitude == pytest.approx(37.55)
        assert result.longitude == pytest.approx(126.92)

    def test_URL에_article_id가_포함된다(self):
        raw = _daangn_raw(id="999")
        result = normalize_daangn(raw)
        assert "999" in result.url

    def test_이미지가_리스트로_변환된다(self):
        raw = _daangn_raw(images=["img1.jpg", "img2.jpg", "img3.jpg"])
        result = normalize_daangn(raw)
        assert len(result.images) == 3

    def test_옥탑_층수가_999로_파싱된다(self):
        raw = _daangn_raw(floor="옥탑")
        result = normalize_daangn(raw)
        assert result.floor == 999


# ---------------------------------------------------------------------------
# normalize_dabang 테스트
# ---------------------------------------------------------------------------

class TestNormalizeDabang:
    """다방 정규화 테스트."""

    def test_정상_변환시_UnifiedListing이_반환된다(self):
        raw = _dabang_raw()
        result = normalize_dabang(raw)

        assert isinstance(result, UnifiedListing)
        assert result.id == "dabang_777"
        assert result.platform == "dabang"

    def test_selling_type_0이_월세로_변환된다(self):
        raw = _dabang_raw(selling_type=0)
        result = normalize_dabang(raw)
        assert result.deal_type == "월세"

    def test_selling_type_1이_전세로_변환된다(self):
        raw = _dabang_raw(selling_type=1)
        result = normalize_dabang(raw)
        assert result.deal_type == "전세"

    def test_selling_type_2가_매매로_변환된다(self):
        raw = _dabang_raw(selling_type=2)
        result = normalize_dabang(raw)
        assert result.deal_type == "매매"

    def test_준공연도가_approve_date에서_파싱된다(self):
        raw = _dabang_raw(approve_date="2015-06-01")
        result = normalize_dabang(raw)
        assert result.built_year == 2015

    def test_URL에_room_id가_포함된다(self):
        raw = _dabang_raw(id="888")
        result = normalize_dabang(raw)
        assert "888" in result.url

    def test_가격이_price_필드에서_파싱된다(self):
        raw = _dabang_raw(price=70)
        result = normalize_dabang(raw)
        assert result.monthly_rent == 70


# ---------------------------------------------------------------------------
# normalize (디스패처) 테스트
# ---------------------------------------------------------------------------

class TestNormalize:
    """normalize 디스패처 함수 테스트."""

    def test_정상_데이터는_UnifiedListing_리스트를_반환한다(self):
        raw_list = [_zigbang_raw(), _zigbang_raw(item_id="456")]
        results = normalize("zigbang", raw_list)
        assert len(results) == 2
        assert all(isinstance(r, UnifiedListing) for r in results)

    def test_잘못된_데이터는_건너뛰고_나머지를_반환한다(self):
        # item_id가 없으면 KeyError 발생 → 건너뜀
        good_raw = _zigbang_raw(item_id="100")
        bad_raw = {"invalid": "data"}  # item_id 없음 → KeyError
        results = normalize("zigbang", [good_raw, bad_raw])
        # 올바른 데이터 1개만 반환
        assert len(results) == 1
        assert results[0].platform_id == "100"

    def test_미지원_플랫폼은_빈_리스트를_반환한다(self):
        results = normalize("unknown_platform", [{"some": "data"}])
        assert results == []

    def test_빈_리스트_입력은_빈_리스트를_반환한다(self):
        results = normalize("zigbang", [])
        assert results == []

    def test_naver_플랫폼_디스패치가_올바르게_동작한다(self):
        raw_list = [_naver_raw()]
        results = normalize("naver", raw_list)
        assert len(results) == 1
        assert results[0].platform == "naver"

    def test_daangn_플랫폼_디스패치가_올바르게_동작한다(self):
        raw_list = [_daangn_raw()]
        results = normalize("daangn", raw_list)
        assert len(results) == 1
        assert results[0].platform == "daangn"

    def test_dabang_플랫폼_디스패치가_올바르게_동작한다(self):
        raw_list = [_dabang_raw()]
        results = normalize("dabang", raw_list)
        assert len(results) == 1
        assert results[0].platform == "dabang"
