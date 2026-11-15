"""V-World 모듈 단위 테스트 (building.py, broker.py)."""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from jibgooham.models.broker import BrokerInfo
from jibgooham.models.listing import UnifiedListing


# ---------------------------------------------------------------------------
# 헬퍼: tmp_path 기반 캐시 격리
# ---------------------------------------------------------------------------


def _patch_cache(tmp_path: Path):
    """캐시 모듈의 DB 경로를 tmp_path로 대체하는 헬퍼.

    building.py / broker.py 가 `from jibgooham.storage import cache` 로
    이미 임포트한 모듈 객체를 패치해야 하므로 두 모듈 모두 패치한다.
    """
    import jibgooham.storage.cache as cache_mod

    db_file = tmp_path / "cache.db"

    def _patched_connect():
        db_file.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(str(db_file))

    cache_mod._connect = _patched_connect
    cache_mod._db_path = lambda: db_file
    cache_mod.init_db()
    return cache_mod


# ---------------------------------------------------------------------------
# 헬퍼: 테스트용 매물(UnifiedListing) 생성
# ---------------------------------------------------------------------------


def _make_listing(**kwargs) -> UnifiedListing:
    """기본값이 채워진 UnifiedListing 픽스처."""
    defaults = dict(
        id="test_001",
        platform="zigbang",
        platform_id="001",
        deal_type="월세",
        deposit=1000,
        monthly_rent=50,
        address="서울 마포구 서교동 123",
        area_m2=33.0,
        room_type="원룸",
        title="테스트 매물",
        url="https://example.com/001",
    )
    defaults.update(kwargs)
    return UnifiedListing(**defaults)


# ---------------------------------------------------------------------------
# V-World 건물 정보 API 응답 픽스처
# ---------------------------------------------------------------------------


def _vworld_building_ok(
    use_apr_day: str = "20100315",
    arch_gb_cd_nm: str = "철근콘크리트",
    jimok_nm: str = "대",
) -> dict[str, Any]:
    """정상 V-World 건축물대장 응답 dict."""
    return {
        "response": {
            "status": "OK",
            "result": {
                "featureCollection": {
                    "features": [
                        {
                            "properties": {
                                "useAprDay": use_apr_day,
                                "archGbCdNm": arch_gb_cd_nm,
                                "jimokNm": jimok_nm,
                            }
                        }
                    ]
                }
            },
        }
    }


def _make_mock_httpx_response(json_data: dict, status_code: int = 200) -> MagicMock:
    """httpx.Response 를 흉내내는 Mock 객체 생성."""
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = status_code
    mock_resp.json.return_value = json_data
    # 2xx 이면 raise_for_status 는 아무것도 하지 않는다
    if status_code >= 400:
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"HTTP {status_code}",
            request=MagicMock(),
            response=mock_resp,
        )
    else:
        mock_resp.raise_for_status.return_value = None
    return mock_resp


# ===========================================================================
# building.py 테스트
# ===========================================================================


class TestGetBuildingInfo:
    """get_building_info() 함수 단위 테스트."""

    @pytest.mark.asyncio
    async def test_정상_응답_dict_반환(self, tmp_path):
        """API 정상 응답 시 built_year, building_structure, land_use 가 채워진 dict 반환."""
        _patch_cache(tmp_path)

        mock_resp = _make_mock_httpx_response(_vworld_building_ok())

        # AsyncClient.get 을 AsyncMock으로 패치
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with (
            patch("jibgooham.vworld.building.VWORLD_API_KEY", "test-key"),
            patch("httpx.AsyncClient", return_value=mock_client),
        ):
            from jibgooham.vworld import building
            result = await building.get_building_info("서울 마포구 서교동 123")

        assert result is not None
        assert result["built_year"] == 2010
        assert result["building_structure"] == "철근콘크리트"
        assert result["land_use"] == "대"

    @pytest.mark.asyncio
    async def test_api_키_없으면_None_반환(self, tmp_path):
        """VWORLD_API_KEY 가 비어있으면 HTTP 호출 없이 None 반환."""
        _patch_cache(tmp_path)

        with patch("jibgooham.vworld.building.VWORLD_API_KEY", ""):
            from jibgooham.vworld import building
            result = await building.get_building_info("서울 마포구 서교동 1")

        assert result is None

    @pytest.mark.asyncio
    async def test_api_에러_시_None_반환(self, tmp_path):
        """HTTP 오류 발생 시 None 반환하고 예외를 전파하지 않는다."""
        _patch_cache(tmp_path)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(
            side_effect=httpx.HTTPError("connection error")
        )

        with (
            patch("jibgooham.vworld.building.VWORLD_API_KEY", "test-key"),
            patch("httpx.AsyncClient", return_value=mock_client),
        ):
            from jibgooham.vworld import building
            result = await building.get_building_info("서울 마포구 오류동 1")

        assert result is None

    @pytest.mark.asyncio
    async def test_캐시_히트_시_api_호출_안함(self, tmp_path):
        """캐시에 데이터가 있으면 HTTP 요청을 보내지 않는다."""
        cache_mod = _patch_cache(tmp_path)

        # 캐시에 미리 건물 정보 저장
        cached_data = {
            "built_year": 2005,
            "building_structure": "벽돌",
            "land_use": "주거",
        }
        cache_mod.set("building_cache", "서울 종로구 1", cached_data, ttl_seconds=3600)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock()  # 호출되면 안 됨

        with (
            patch("jibgooham.vworld.building.VWORLD_API_KEY", "test-key"),
            patch("httpx.AsyncClient", return_value=mock_client),
        ):
            from jibgooham.vworld import building
            result = await building.get_building_info("서울 종로구 1")

        assert result == cached_data
        # 캐시 히트이므로 API 호출 없어야 한다
        mock_client.get.assert_not_called()


class TestEnrichListingsWithBuilding:
    """enrich_listings_with_building() 함수 단위 테스트."""

    @pytest.mark.asyncio
    async def test_매물_목록에_건물_정보_추가됨(self, tmp_path):
        """매물 주소로 건물 정보를 조회하여 built_year 등 필드가 채워진다."""
        _patch_cache(tmp_path)

        listing = _make_listing(address="서울 용산구 한강로 1")

        mock_resp = _make_mock_httpx_response(
            _vworld_building_ok(use_apr_day="19980601", arch_gb_cd_nm="철골조", jimok_nm="상업지역")
        )

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with (
            patch("jibgooham.vworld.building.VWORLD_API_KEY", "test-key"),
            patch("httpx.AsyncClient", return_value=mock_client),
        ):
            from jibgooham.vworld import building
            enriched = await building.enrich_listings_with_building([listing])

        assert len(enriched) == 1
        assert enriched[0].built_year == 1998
        assert enriched[0].building_structure == "철골조"
        assert enriched[0].land_use == "상업지역"

    @pytest.mark.asyncio
    async def test_api_키_없으면_원본_목록_그대로_반환(self, tmp_path):
        """VWORLD_API_KEY 미설정 시 매물을 그대로 반환하며 enrichment 를 건너뛴다."""
        _patch_cache(tmp_path)

        listing = _make_listing()

        with patch("jibgooham.vworld.building.VWORLD_API_KEY", ""):
            from jibgooham.vworld import building
            result = await building.enrich_listings_with_building([listing])

        assert result == [listing]
        assert listing.built_year is None  # 변경 없음

    @pytest.mark.asyncio
    async def test_기존_built_year는_덮어쓰지_않음(self, tmp_path):
        """매물에 이미 built_year 가 있으면 V-World 값으로 덮어쓰지 않는다."""
        _patch_cache(tmp_path)

        listing = _make_listing(built_year=2000)  # 기존 값

        mock_resp = _make_mock_httpx_response(
            _vworld_building_ok(use_apr_day="20150101")
        )

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with (
            patch("jibgooham.vworld.building.VWORLD_API_KEY", "test-key"),
            patch("httpx.AsyncClient", return_value=mock_client),
        ):
            from jibgooham.vworld import building
            await building.enrich_listings_with_building([listing])

        # 기존 2000 값이 유지되어야 한다
        assert listing.built_year == 2000


# ===========================================================================
# broker.py 테스트
# ===========================================================================


def _broker_json_response(
    name: str = "행복부동산",
    reg_no: str = "서울-강남-12345",
    rprs_nm: str = "홍길동",
    pos_nm: str = "공인중개사",
    status: str = "정상영업",
    reg_dt: str = "20100101",
    addr: str = "서울 강남구 테헤란로 1",
) -> str:
    """V-World 중개소 조회 JSON 응답 문자열."""
    items = [
        {
            "regNm": name,
            "regNo": reg_no,
            "rprsNm": rprs_nm,
            "brkrPosNm": pos_nm,
            "useSttsCdNm": status,
            "regDt": reg_dt,
            "addr": addr,
        }
    ]
    return json.dumps({"list": items}, ensure_ascii=False)


def _make_broker_mock_response(body: str, status_code: int = 200) -> MagicMock:
    """httpx POST 응답 Mock (text 속성 포함)."""
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = status_code
    mock_resp.text = body
    if status_code >= 400:
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"HTTP {status_code}",
            request=MagicMock(),
            response=mock_resp,
        )
    else:
        mock_resp.raise_for_status.return_value = None
    return mock_resp


class TestVerifyBroker:
    """verify_broker() 함수 단위 테스트."""

    @pytest.mark.asyncio
    async def test_정상_응답_BrokerInfo_반환(self, tmp_path):
        """API 정상 응답 시 BrokerInfo 객체가 반환된다."""
        _patch_cache(tmp_path)

        mock_resp = _make_broker_mock_response(_broker_json_response())

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            from jibgooham.vworld import broker
            result = await broker.verify_broker("행복부동산")

        assert result is not None
        assert isinstance(result, BrokerInfo)
        assert result.name == "행복부동산"
        assert result.registration_no == "서울-강남-12345"
        assert result.representative == "홍길동"
        assert result.status == "정상영업"

    @pytest.mark.asyncio
    async def test_api_에러_시_None_반환(self, tmp_path):
        """HTTP 오류 발생 시 None 반환하고 예외를 전파하지 않는다."""
        _patch_cache(tmp_path)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(
            side_effect=httpx.HTTPError("connection refused")
        )

        with patch("httpx.AsyncClient", return_value=mock_client):
            from jibgooham.vworld import broker
            result = await broker.verify_broker("오류부동산")

        assert result is None

    @pytest.mark.asyncio
    async def test_캐시_히트_시_api_호출_안함(self, tmp_path):
        """캐시에 데이터가 있으면 HTTP 요청을 보내지 않는다."""
        cache_mod = _patch_cache(tmp_path)

        # 캐시에 BrokerInfo 직렬화 데이터 미리 저장
        cached_broker = BrokerInfo(
            name="캐시부동산",
            position="공인중개사",
            status="정상영업",
        )
        cache_mod.set(
            "broker_cache",
            "캐시부동산",
            cached_broker.model_dump(mode="json"),
            ttl_seconds=3600,
        )

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock()  # 호출되면 안 됨

        with patch("httpx.AsyncClient", return_value=mock_client):
            from jibgooham.vworld import broker
            result = await broker.verify_broker("캐시부동산")

        assert result is not None
        assert result.name == "캐시부동산"
        mock_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_빈_이름_None_반환(self, tmp_path):
        """broker_name 이 빈 문자열이면 즉시 None 반환."""
        _patch_cache(tmp_path)

        from jibgooham.vworld import broker
        result = await broker.verify_broker("")

        assert result is None

    @pytest.mark.asyncio
    async def test_결과_없는_응답_None_반환(self, tmp_path):
        """API 응답에 항목이 없으면 None 반환."""
        _patch_cache(tmp_path)

        empty_body = json.dumps({"list": []})
        mock_resp = _make_broker_mock_response(empty_body)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            from jibgooham.vworld import broker
            result = await broker.verify_broker("없는부동산")

        assert result is None


class TestEnrichListingsWithBroker:
    """enrich_listings_with_broker() 함수 단위 테스트."""

    @pytest.mark.asyncio
    async def test_매물_broker_필드_채워짐(self, tmp_path):
        """매물의 broker.name 으로 V-World 조회 후 broker 필드가 업데이트된다."""
        _patch_cache(tmp_path)

        # 기본 BrokerInfo (name 만 있는 상태)
        initial_broker = BrokerInfo(name="행복부동산", position="공인중개사", status="정상영업")
        listing = _make_listing(broker=initial_broker)

        mock_resp = _make_broker_mock_response(
            _broker_json_response(
                name="행복부동산",
                reg_no="서울-마포-99999",
                rprs_nm="김영희",
            )
        )

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            from jibgooham.vworld import broker
            enriched = await broker.enrich_listings_with_broker([listing])

        assert len(enriched) == 1
        assert enriched[0].broker is not None
        assert enriched[0].broker.registration_no == "서울-마포-99999"
        assert enriched[0].broker.representative == "김영희"

    @pytest.mark.asyncio
    async def test_broker_없는_매물은_스킵(self, tmp_path):
        """broker 가 None 인 매물은 조회하지 않고 그대로 반환한다."""
        _patch_cache(tmp_path)

        listing = _make_listing(broker=None)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock()

        with patch("httpx.AsyncClient", return_value=mock_client):
            from jibgooham.vworld import broker
            result = await broker.enrich_listings_with_broker([listing])

        assert result[0].broker is None
        mock_client.post.assert_not_called()


# ===========================================================================
# BrokerInfo.trust_level 연동 테스트
# ===========================================================================


class TestBrokerInfoTrustLevel:
    """BrokerInfo.trust_level 프로퍼티 테스트."""

    def test_중개보조원_danger(self):
        """position이 '중개보조원'이면 trust_level은 'danger'."""
        broker = BrokerInfo(name="테스트", position="중개보조원", status="정상영업")
        assert broker.trust_level == "danger"

    def test_개업_1년_미만_low(self):
        """개업일이 1년 미만이면 trust_level은 'low'."""
        from datetime import timedelta

        recent = date.today() - timedelta(days=100)
        broker = BrokerInfo(
            name="신규부동산",
            position="공인중개사",
            status="정상영업",
            opened_at=recent,
        )
        assert broker.trust_level == "low"

    def test_개업_1년_이상_3년_미만_medium(self):
        """개업일이 1년 이상 3년 미만이면 trust_level은 'medium'."""
        from datetime import timedelta

        two_years_ago = date.today() - timedelta(days=365 * 2)
        broker = BrokerInfo(
            name="중견부동산",
            position="공인중개사",
            status="정상영업",
            opened_at=two_years_ago,
        )
        assert broker.trust_level == "medium"

    def test_개업_3년_이상_high(self):
        """개업일이 3년 이상이면 trust_level은 'high'."""
        from datetime import timedelta

        old = date.today() - timedelta(days=365 * 5)
        broker = BrokerInfo(
            name="노포부동산",
            position="공인중개사",
            status="정상영업",
            opened_at=old,
        )
        assert broker.trust_level == "high"

    def test_opened_at_없으면_high(self):
        """opened_at 이 None이면 조건이 모두 false → trust_level은 'high'."""
        broker = BrokerInfo(name="테스트", position="공인중개사", status="정상영업")
        assert broker.trust_level == "high"

    @pytest.mark.asyncio
    async def test_verify_broker_결과의_trust_level(self, tmp_path):
        """verify_broker() 가 반환한 BrokerInfo 의 trust_level 이 올바르게 계산된다."""
        _patch_cache(tmp_path)

        # 10년 전 개업 → high
        mock_resp = _make_broker_mock_response(
            _broker_json_response(reg_dt="20100101")
        )

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            from jibgooham.vworld import broker as broker_mod
            result = await broker_mod.verify_broker("행복부동산_trust")

        assert result is not None
        assert result.trust_level == "high"
