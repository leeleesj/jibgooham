"""직방 크롤러 모듈.

직방 비공식 API를 사용하여 원룸/오피스텔 매물을 검색한다.
API 엔드포인트는 추정치이므로 실제 동작 시 조정이 필요할 수 있다.
"""

from __future__ import annotations

import httpx
import structlog

from jibgooham.crawlers.base import BaseCrawler
from jibgooham.models.search_params import SearchParams

logger = structlog.get_logger(__name__)

# --- 직방 API 엔드포인트 ---
ZIGBANG_BASE_URL = "https://apis.zigbang.com"
ZIGBANG_SEARCH_URL = f"{ZIGBANG_BASE_URL}/v2/search"
ZIGBANG_ITEMS_ONEROOM_URL = f"{ZIGBANG_BASE_URL}/v2/items/oneroom"
ZIGBANG_ITEMS_LIST_URL = f"{ZIGBANG_BASE_URL}/v2/items/list"

# --- 직방 요청 설정 ---
ZIGBANG_TIMEOUT = 15.0
ZIGBANG_DEAL_TYPE_MAP = {
    "월세": "rent",
    "전세": "jeonse",
    "매매": "buy",
}
ZIGBANG_ROOM_TYPE_MAP = {
    "원룸": "01",
    "투룸": "02",
    "오피스텔": "05",
}


class ZigbangCrawler(BaseCrawler):
    """직방 매물 크롤러.

    직방 API를 통해 지역 검색 → 매물 목록 → 매물 상세 순서로 데이터를 수집한다.
    """

    platform: str = "zigbang"

    async def search(self, params: SearchParams) -> list[dict]:
        """직방에서 매물 검색.

        1. 지역명으로 geohash 조회
        2. geohash 기반 매물 ID 목록 조회
        3. 매물 ID로 상세 정보 일괄 조회

        Args:
            params: 검색 조건

        Returns:
            직방 원본 형태의 매물 딕셔너리 리스트
        """
        self._log.info("직방 검색 시작", region=params.region)

        async with httpx.AsyncClient(timeout=ZIGBANG_TIMEOUT) as client:
            # 1단계: 지역명 → geohash 조회
            geohash = await self._search_region(client, params.region)
            if not geohash:
                self._log.warning("지역 검색 결과 없음", region=params.region)
                return []

            # 2단계: geohash → 매물 ID 목록
            item_ids = await self._get_item_ids(client, geohash, params)
            if not item_ids:
                self._log.info("매물 없음", region=params.region)
                return []

            # 3단계: 매물 ID → 상세 정보 일괄 조회
            # limit 적용
            item_ids = item_ids[: params.limit]
            items = await self._get_items_detail(client, item_ids)

            self._log.info("직방 검색 완료", count=len(items))
            return items

    async def get_detail(self, listing_id: str) -> dict:
        """직방 매물 단건 상세 조회.

        Args:
            listing_id: 직방 매물 ID

        Returns:
            매물 상세 정보 딕셔너리
        """
        async with httpx.AsyncClient(timeout=ZIGBANG_TIMEOUT) as client:
            items = await self._get_items_detail(client, [int(listing_id)])
            if items:
                return items[0]
            return {}

    async def _search_region(
        self, client: httpx.AsyncClient, region: str
    ) -> str | None:
        """지역명을 geohash로 변환.

        Args:
            client: httpx 비동기 클라이언트
            region: 지역명 (예: "강남역", "서울 마포구")

        Returns:
            geohash 문자열 또는 None
        """
        response = await self._rate_limited_get(
            client,
            ZIGBANG_SEARCH_URL,
            params={"leaseYn": "N", "q": region},
        )
        if response.status_code != 200:
            self._log.error("지역 검색 실패", status=response.status_code)
            return None

        data = response.json()
        # 응답 구조: {"items": [{"lat": ..., "lng": ..., "geohash": ...}]}
        items = data.get("items", [])
        if not items:
            return None

        return items[0].get("geohash")

    async def _get_item_ids(
        self,
        client: httpx.AsyncClient,
        geohash: str,
        params: SearchParams,
    ) -> list[int]:
        """geohash 기반으로 매물 ID 목록 조회.

        Args:
            client: httpx 비동기 클라이언트
            geohash: 지역 geohash
            params: 검색 조건 (보증금, 월세 범위 등)

        Returns:
            매물 ID 리스트
        """
        deal_type = ZIGBANG_DEAL_TYPE_MAP.get(params.deal_type, "rent")
        room_type = ZIGBANG_ROOM_TYPE_MAP.get(params.room_type, "01")

        query_params = {
            "geohash": geohash,
            "depositMin": params.deposit_min,
            "depositMax": params.deposit_max,
            "rentMin": params.rent_min,
            "rentMax": params.rent_max,
            "salesType": deal_type,
            "roomType": room_type,
        }

        response = await self._rate_limited_get(
            client,
            ZIGBANG_ITEMS_ONEROOM_URL,
            params=query_params,
        )
        if response.status_code != 200:
            self._log.error("매물 목록 조회 실패", status=response.status_code)
            return []

        data = response.json()
        # 응답 구조: {"items": [{"item_id": 12345, ...}]}
        return [item["item_id"] for item in data.get("items", []) if "item_id" in item]

    async def _get_items_detail(
        self,
        client: httpx.AsyncClient,
        item_ids: list[int],
    ) -> list[dict]:
        """매물 ID 목록으로 상세 정보 일괄 조회.

        직방은 POST body에 item_ids를 넣어 일괄 조회하는 방식을 사용한다.

        Args:
            client: httpx 비동기 클라이언트
            item_ids: 매물 ID 리스트

        Returns:
            매물 상세 정보 딕셔너리 리스트
        """
        if not item_ids:
            return []

        response = await self._rate_limited_post(
            client,
            ZIGBANG_ITEMS_LIST_URL,
            json={"item_ids": item_ids},
        )
        if response.status_code != 200:
            self._log.error("매물 상세 조회 실패", status=response.status_code)
            return []

        data = response.json()
        return data.get("items", [])
