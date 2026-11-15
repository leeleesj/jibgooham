"""네이버 부동산 크롤러 모듈.

네이버 부동산 비공식 API를 사용하여 매물을 검색한다.
Referer 헤더가 필수이며, API 구조가 변경될 수 있다.
"""

from __future__ import annotations

import httpx
import structlog

from jibgooham.crawlers.base import BaseCrawler
from jibgooham.models.search_params import SearchParams

logger = structlog.get_logger(__name__)

# --- 네이버 부동산 API 엔드포인트 ---
NAVER_LAND_BASE_URL = "https://new.land.naver.com"
NAVER_REGION_SEARCH_URL = f"{NAVER_LAND_BASE_URL}/api/regions/v1/search"
NAVER_ARTICLES_URL = f"{NAVER_LAND_BASE_URL}/api/articles"
NAVER_ARTICLE_DETAIL_URL = f"{NAVER_LAND_BASE_URL}/api/articles"

# --- 네이버 부동산 필수 헤더 ---
NAVER_HEADERS = {
    "Accept": "application/json",
    "Referer": NAVER_LAND_BASE_URL,
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

# --- 요청 설정 ---
NAVER_TIMEOUT = 15.0
NAVER_REAL_ESTATE_TYPE_MAP = {
    "원룸": "OR",
    "투룸": "DDDGG",
    "오피스텔": "OPST",
    "아파트": "APT",
    "빌라": "VL",
}
NAVER_TRADE_TYPE_MAP = {
    "월세": "B2",
    "전세": "B1",
    "매매": "A1",
}


class NaverCrawler(BaseCrawler):
    """네이버 부동산 매물 크롤러.

    네이버 부동산 API를 통해 지역코드 조회 → 매물 목록 조회 순서로 데이터를 수집한다.
    Referer 헤더가 없으면 403 응답이 반환된다.
    """

    platform: str = "naver"

    async def search(self, params: SearchParams) -> list[dict]:
        """네이버 부동산에서 매물 검색.

        1. 지역명 → 법정동 코드(cortarNo) 조회
        2. cortarNo 기반 매물 목록 조회

        Args:
            params: 검색 조건

        Returns:
            네이버 부동산 원본 형태의 매물 딕셔너리 리스트
        """
        self._log.info("네이버 부동산 검색 시작", region=params.region)

        async with httpx.AsyncClient(
            timeout=NAVER_TIMEOUT, headers=NAVER_HEADERS
        ) as client:
            # 1단계: 지역명 → cortarNo 조회
            cortar_no = await self._search_region(client, params.region)
            if not cortar_no:
                self._log.warning("지역 검색 결과 없음", region=params.region)
                return []

            # 2단계: cortarNo → 매물 목록 조회
            articles = await self._get_articles(client, cortar_no, params)

            self._log.info("네이버 부동산 검색 완료", count=len(articles))
            return articles

    async def get_detail(self, listing_id: str) -> dict:
        """네이버 부동산 매물 단건 상세 조회.

        Args:
            listing_id: 네이버 부동산 매물 ID (articleId)

        Returns:
            매물 상세 정보 딕셔너리
        """
        url = f"{NAVER_ARTICLE_DETAIL_URL}/{listing_id}"

        async with httpx.AsyncClient(
            timeout=NAVER_TIMEOUT, headers=NAVER_HEADERS
        ) as client:
            response = await self._rate_limited_get(client, url)
            if response.status_code != 200:
                self._log.error("매물 상세 조회 실패", status=response.status_code)
                return {}
            return response.json()

    async def _search_region(
        self, client: httpx.AsyncClient, region: str
    ) -> str | None:
        """지역명을 법정동 코드(cortarNo)로 변환.

        Args:
            client: httpx 비동기 클라이언트
            region: 지역명 (예: "강남역", "서울 마포구")

        Returns:
            cortarNo 문자열 또는 None
        """
        response = await self._rate_limited_get(
            client,
            NAVER_REGION_SEARCH_URL,
            params={"keyword": region},
        )
        if response.status_code != 200:
            self._log.error("지역 검색 실패", status=response.status_code)
            return None

        data = response.json()
        # 응답 구조: {"regionList": [{"cortarNo": "1168000000", ...}]}
        regions = data.get("regionList", [])
        if not regions:
            return None

        return regions[0].get("cortarNo")

    async def _get_articles(
        self,
        client: httpx.AsyncClient,
        cortar_no: str,
        params: SearchParams,
    ) -> list[dict]:
        """법정동 코드 기반 매물 목록 조회.

        Args:
            client: httpx 비동기 클라이언트
            cortar_no: 법정동 코드
            params: 검색 조건

        Returns:
            매물 딕셔너리 리스트
        """
        real_estate_type = NAVER_REAL_ESTATE_TYPE_MAP.get(params.room_type, "OR")
        trade_type = NAVER_TRADE_TYPE_MAP.get(params.deal_type, "B2")

        query_params = {
            "cortarNo": cortar_no,
            "realEstateType": real_estate_type,
            "tradeType": trade_type,
            "priceMin": params.deposit_min,
            "priceMax": params.deposit_max,
            "rentPriceMin": params.rent_min,
            "rentPriceMax": params.rent_max,
            "areaMin": params.area_min,
            "areaMax": params.area_max,
            "page": 1,
            "sameAddressGroup": "true",
        }

        response = await self._rate_limited_get(
            client,
            NAVER_ARTICLES_URL,
            params=query_params,
        )
        if response.status_code != 200:
            self._log.error("매물 목록 조회 실패", status=response.status_code)
            return []

        data = response.json()
        # 응답 구조: {"articleList": [{...}, ...]}
        articles = data.get("articleList", [])
        return articles[: params.limit]
