"""크롤러 모듈 단위 테스트.

실제 HTTP 요청 없이 httpx와 Playwright를 mock하여 테스트한다.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio

from jibgooham.crawlers.base import RATE_LIMIT_WAIT, BaseCrawler
from jibgooham.crawlers.dabang import DabangCrawler
from jibgooham.crawlers.naver import NaverCrawler
from jibgooham.crawlers.zigbang import ZigbangCrawler
from jibgooham.models.search_params import SearchParams


# ---------------------------------------------------------------------------
# 테스트 헬퍼
# ---------------------------------------------------------------------------


def make_params(**kwargs) -> SearchParams:
    """기본 검색 파라미터 생성 헬퍼."""
    defaults = {"region": "서울 마포구", "limit": 5}
    defaults.update(kwargs)
    return SearchParams(**defaults)


def make_response(status_code: int, body: dict | None = None) -> httpx.Response:
    """httpx.Response mock 헬퍼.

    실제 httpx.Response를 생성하되 content를 JSON 직렬화해서 채운다.
    raise_for_status() 호출을 위해 _request 속성도 설정한다.
    """
    content = json.dumps(body or {}).encode()
    response = httpx.Response(
        status_code=status_code,
        content=content,
        headers={"content-type": "application/json"},
    )
    # raise_for_status()는 내부적으로 _request 필요 — 더미 요청 객체 주입
    response.request = httpx.Request("GET", "https://example.com")
    return response


# ---------------------------------------------------------------------------
# BaseCrawler 테스트
# ---------------------------------------------------------------------------


class ConcreteTestCrawler(BaseCrawler):
    """테스트용 추상 메서드 구현체."""

    platform = "test"

    async def search(self, params: SearchParams) -> list[dict]:
        return []

    async def get_detail(self, listing_id: str) -> dict:
        return {}


class TestRateLimitedGet:
    """BaseCrawler._rate_limited_get 테스트."""

    @pytest.mark.asyncio
    async def test_정상_응답_반환(self):
        """200 응답이 오면 그대로 반환되어야 한다."""
        crawler = ConcreteTestCrawler()
        expected_response = make_response(200, {"items": [{"id": 1}]})

        # httpx.AsyncClient.get을 mock
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.return_value = expected_response

        with patch("asyncio.sleep", new_callable=AsyncMock):
            response = await crawler._rate_limited_get(mock_client, "https://example.com")

        assert response.status_code == 200
        assert response.json() == {"items": [{"id": 1}]}
        mock_client.get.assert_called_once_with("https://example.com")

    @pytest.mark.asyncio
    async def test_429_응답시_sleep_후_재시도(self):
        """429 응답 시 sleep 후 한 번 더 요청해야 한다."""
        crawler = ConcreteTestCrawler()

        # 첫 번째 호출: 429, 두 번째 호출: 200
        first_response = make_response(429)
        second_response = make_response(200, {"items": []})

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.side_effect = [first_response, second_response]

        sleep_mock = AsyncMock()
        with patch("asyncio.sleep", sleep_mock):
            response = await crawler._rate_limited_get(mock_client, "https://example.com")

        # 두 번 호출되었는지 확인
        assert mock_client.get.call_count == 2
        assert response.status_code == 200

        # RATE_LIMIT_WAIT 만큼 sleep 호출 확인 (rate-limit sleep 포함)
        sleep_calls = [call.args[0] for call in sleep_mock.call_args_list]
        assert RATE_LIMIT_WAIT in sleep_calls

    @pytest.mark.asyncio
    async def test_429_재시도후_에러_raise(self):
        """429 후 재시도에서도 4xx/5xx 응답이 오면 HTTPStatusError가 발생해야 한다."""
        crawler = ConcreteTestCrawler()

        # 첫 번째: 429, 두 번째: 500
        first_response = make_response(429)
        # 500 응답은 raise_for_status() 가 raise 해야 함
        second_response = make_response(500)

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.side_effect = [first_response, second_response]

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(httpx.HTTPStatusError):
                await crawler._rate_limited_get(mock_client, "https://example.com")

    @pytest.mark.asyncio
    async def test_비429_에러_응답시_raise_없음(self):
        """비 429 에러(예: 404)는 그냥 반환되며 raise하지 않는다."""
        crawler = ConcreteTestCrawler()
        response_404 = make_response(404)

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.return_value = response_404

        with patch("asyncio.sleep", new_callable=AsyncMock):
            response = await crawler._rate_limited_get(mock_client, "https://example.com")

        # _rate_limited_get 자체는 raise 안 함 (호출자가 status 체크)
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# ZigbangCrawler 테스트
# ---------------------------------------------------------------------------


class TestZigbangCrawlerSearch:
    """ZigbangCrawler.search() 테스트."""

    @pytest.mark.asyncio
    async def test_정상_검색_결과_반환(self):
        """모든 API 호출이 정상일 때 매물 리스트를 반환해야 한다."""
        params = make_params(region="강남역", limit=2)

        # 단계별 mock 응답 준비
        region_resp = make_response(200, {"items": [{"geohash": "wydm9"}]})
        items_resp = make_response(200, {"items": [{"item_id": 101}, {"item_id": 102}]})
        detail_resp = make_response(
            200,
            {"items": [{"item_id": 101, "deposit": 500}, {"item_id": 102, "deposit": 300}]},
        )

        crawler = ZigbangCrawler()

        # _rate_limited_get / _rate_limited_post 순서대로 patch
        with patch.object(
            crawler, "_rate_limited_get", new_callable=AsyncMock
        ) as mock_get, patch.object(
            crawler, "_rate_limited_post", new_callable=AsyncMock
        ) as mock_post:
            mock_get.side_effect = [region_resp, items_resp]
            mock_post.return_value = detail_resp

            result = await crawler.search(params)

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["item_id"] == 101

    @pytest.mark.asyncio
    async def test_지역검색_실패시_빈_리스트(self):
        """지역 검색 API가 실패하면 빈 리스트를 반환해야 한다."""
        params = make_params(region="없는지역")

        crawler = ZigbangCrawler()

        with patch.object(
            crawler, "_rate_limited_get", new_callable=AsyncMock
        ) as mock_get:
            # 지역 검색 결과 빈 items
            mock_get.return_value = make_response(200, {"items": []})

            result = await crawler.search(params)

        assert result == []

    @pytest.mark.asyncio
    async def test_api_에러시_에러_전파_안됨(self):
        """API 호출에서 예외가 발생해도 search()는 빈 리스트를 반환해야 한다.

        (에러는 search_all에서 격리되지만, 개별 크롤러는 내부에서 처리할 수도 있다.
        직방은 내부에서 별도 try/except가 없으므로 예외가 전파된다.
        search_all 레벨에서 격리된다는 점을 search_all 테스트에서 검증한다.)
        """
        # 직방 크롤러 자체는 HTTP 에러를 propagate 함을 확인
        params = make_params()
        crawler = ZigbangCrawler()

        with patch.object(
            crawler, "_rate_limited_get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.side_effect = httpx.ConnectError("연결 실패")

            with pytest.raises(httpx.ConnectError):
                await crawler.search(params)


# ---------------------------------------------------------------------------
# NaverCrawler 테스트
# ---------------------------------------------------------------------------


class TestNaverCrawlerSearch:
    """NaverCrawler.search() 테스트."""

    @pytest.mark.asyncio
    async def test_정상_검색_결과_반환(self):
        """모든 API 호출이 정상일 때 매물 리스트를 반환해야 한다."""
        params = make_params(region="서울 강남구", limit=3)

        region_resp = make_response(
            200, {"regionList": [{"cortarNo": "1168000000", "name": "강남구"}]}
        )
        articles_resp = make_response(
            200,
            {
                "articleList": [
                    {"articleId": "A1", "tradeTypeName": "월세"},
                    {"articleId": "A2", "tradeTypeName": "월세"},
                    {"articleId": "A3", "tradeTypeName": "월세"},
                ]
            },
        )

        crawler = NaverCrawler()

        with patch.object(
            crawler, "_rate_limited_get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.side_effect = [region_resp, articles_resp]

            result = await crawler.search(params)

        assert isinstance(result, list)
        assert len(result) == 3
        assert result[0]["articleId"] == "A1"

    @pytest.mark.asyncio
    async def test_지역검색_결과없으면_빈_리스트(self):
        """지역 검색 결과가 없으면 빈 리스트를 반환해야 한다."""
        params = make_params(region="없는지역")
        crawler = NaverCrawler()

        with patch.object(
            crawler, "_rate_limited_get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = make_response(200, {"regionList": []})

            result = await crawler.search(params)

        assert result == []

    @pytest.mark.asyncio
    async def test_limit_적용됨(self):
        """limit 개수만큼만 반환해야 한다."""
        params = make_params(region="강남구", limit=2)

        region_resp = make_response(
            200, {"regionList": [{"cortarNo": "1168000000"}]}
        )
        # 5개 반환하지만 limit=2 이므로 2개만 와야 함
        articles_resp = make_response(
            200,
            {
                "articleList": [
                    {"articleId": f"A{i}"} for i in range(5)
                ]
            },
        )

        crawler = NaverCrawler()

        with patch.object(
            crawler, "_rate_limited_get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.side_effect = [region_resp, articles_resp]

            result = await crawler.search(params)

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_api_에러시_빈_리스트(self):
        """매물 목록 API가 200이 아닌 경우 빈 리스트를 반환해야 한다."""
        params = make_params()
        crawler = NaverCrawler()

        region_resp = make_response(200, {"regionList": [{"cortarNo": "1168000000"}]})
        # 매물 목록 API 에러
        error_resp = make_response(403, {})

        with patch.object(
            crawler, "_rate_limited_get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.side_effect = [region_resp, error_resp]

            result = await crawler.search(params)

        assert result == []


# ---------------------------------------------------------------------------
# DabangCrawler 테스트
# ---------------------------------------------------------------------------


class TestDabangCrawlerSearch:
    """DabangCrawler.search() 테스트."""

    @pytest.mark.asyncio
    async def test_정상_검색_결과_반환(self):
        """모든 API 호출이 정상일 때 매물 리스트를 반환해야 한다."""
        params = make_params(region="서울 마포구", limit=3)

        region_resp = make_response(
            200,
            {"result": [{"id": "region_001", "name": "마포구", "code": "11440"}]},
        )
        rooms_resp = make_response(
            200,
            {
                "rooms": [
                    {"id": "R1", "name": "원룸A"},
                    {"id": "R2", "name": "원룸B"},
                    {"id": "R3", "name": "원룸C"},
                ]
            },
        )

        crawler = DabangCrawler()

        with patch.object(
            crawler, "_rate_limited_get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.side_effect = [region_resp, rooms_resp]

            result = await crawler.search(params)

        assert isinstance(result, list)
        assert len(result) == 3
        assert result[0]["id"] == "R1"

    @pytest.mark.asyncio
    async def test_지역검색_결과없으면_빈_리스트(self):
        """지역 검색 결과가 없으면 빈 리스트를 반환해야 한다."""
        params = make_params(region="없는지역")
        crawler = DabangCrawler()

        with patch.object(
            crawler, "_rate_limited_get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = make_response(200, {"result": []})

            result = await crawler.search(params)

        assert result == []

    @pytest.mark.asyncio
    async def test_api_에러시_빈_리스트(self):
        """매물 목록 API가 200이 아닌 경우 빈 리스트를 반환해야 한다."""
        params = make_params()
        crawler = DabangCrawler()

        region_resp = make_response(
            200,
            {"result": [{"id": "region_001", "code": "11440"}]},
        )
        error_resp = make_response(500, {})

        with patch.object(
            crawler, "_rate_limited_get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.side_effect = [region_resp, error_resp]

            result = await crawler.search(params)

        assert result == []


# ---------------------------------------------------------------------------
# DaangnCrawler 테스트
# ---------------------------------------------------------------------------


class TestDaangnCrawlerSearch:
    """DaangnCrawler.search() 테스트."""

    @pytest.mark.asyncio
    async def test_playwright_미설치시_빈_리스트_반환(self):
        """Playwright가 미설치된 환경에서는 빈 리스트를 반환해야 한다."""
        import jibgooham.crawlers.daangn as daangn_module

        # _PLAYWRIGHT_AVAILABLE 플래그를 False로 패치
        with patch.object(daangn_module, "_PLAYWRIGHT_AVAILABLE", False):
            # 모듈 재임포트 없이 직접 패치된 상태에서 크롤러 동작 확인
            from jibgooham.crawlers.daangn import DaangnCrawler

            crawler = DaangnCrawler()
            params = make_params()
            result = await crawler.search(params)

        assert result == []

    @pytest.mark.asyncio
    async def test_playwright_예외_발생시_빈_리스트_반환(self):
        """Playwright 실행 중 예외가 발생하면 빈 리스트를 반환해야 한다."""
        import jibgooham.crawlers.daangn as daangn_module

        # Playwright가 설치된 것으로 보이지만 실행 시 에러 발생하도록 patch
        with patch.object(daangn_module, "_PLAYWRIGHT_AVAILABLE", True):
            with patch(
                "jibgooham.crawlers.daangn.async_playwright",
                side_effect=Exception("Playwright 실행 오류"),
            ):
                from jibgooham.crawlers.daangn import DaangnCrawler

                crawler = DaangnCrawler()
                params = make_params()
                result = await crawler.search(params)

        assert result == []


# ---------------------------------------------------------------------------
# search_all() 테스트
# ---------------------------------------------------------------------------


class TestSearchAll:
    """search_all() 통합 병렬 검색 테스트."""

    @pytest.mark.asyncio
    async def test_두_플랫폼_병렬_검색_결과_dict_반환(self):
        """2개 이상 플랫폼을 검색하면 {플랫폼명: 리스트} dict를 반환해야 한다."""
        from jibgooham.crawlers import search_all

        params = make_params(platforms=["zigbang", "naver"])

        zigbang_items = [{"item_id": 1}, {"item_id": 2}]
        naver_items = [{"articleId": "A1"}]

        # 각 크롤러의 search 메서드를 mock
        with patch(
            "jibgooham.crawlers.ZigbangCrawler.search", new_callable=AsyncMock
        ) as mock_zigbang, patch(
            "jibgooham.crawlers.NaverCrawler.search", new_callable=AsyncMock
        ) as mock_naver:
            mock_zigbang.return_value = zigbang_items
            mock_naver.return_value = naver_items

            result = await search_all(params)

        assert "zigbang" in result
        assert "naver" in result
        assert result["zigbang"] == zigbang_items
        assert result["naver"] == naver_items

    @pytest.mark.asyncio
    async def test_한_플랫폼_실패시_나머지_결과_정상_반환(self):
        """한 플랫폼이 예외를 발생시켜도 나머지 플랫폼 결과는 정상 반환해야 한다."""
        from jibgooham.crawlers import search_all

        params = make_params(platforms=["zigbang", "naver"])

        naver_items = [{"articleId": "A1"}, {"articleId": "A2"}]

        with patch(
            "jibgooham.crawlers.ZigbangCrawler.search", new_callable=AsyncMock
        ) as mock_zigbang, patch(
            "jibgooham.crawlers.NaverCrawler.search", new_callable=AsyncMock
        ) as mock_naver:
            # 직방은 예외 발생
            mock_zigbang.side_effect = Exception("직방 API 장애")
            mock_naver.return_value = naver_items

            result = await search_all(params)

        # 직방은 빈 리스트, 네이버는 정상 결과
        assert result.get("zigbang", []) == []
        assert result["naver"] == naver_items

    @pytest.mark.asyncio
    async def test_알_수_없는_플랫폼은_무시됨(self):
        """CRAWLER_REGISTRY에 없는 플랫폼은 결과에 포함되지 않아야 한다."""
        from jibgooham.crawlers import search_all

        params = make_params(platforms=["unknown_platform"])

        result = await search_all(params)

        # unknown_platform은 REGISTRY에 없으므로 task 자체가 생성 안 됨
        assert result == {}

    @pytest.mark.asyncio
    async def test_빈_결과_플랫폼도_dict에_포함됨(self):
        """검색 결과가 없는 플랫폼도 빈 리스트로 dict에 포함되어야 한다."""
        from jibgooham.crawlers import search_all

        params = make_params(platforms=["dabang"])

        with patch(
            "jibgooham.crawlers.DabangCrawler.search", new_callable=AsyncMock
        ) as mock_dabang:
            mock_dabang.return_value = []

            result = await search_all(params)

        assert "dabang" in result
        assert result["dabang"] == []
