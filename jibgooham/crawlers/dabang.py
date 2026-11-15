"""다방 크롤러 모듈.

다방 비공식 API를 사용하여 매물을 검색한다.
API 엔드포인트는 추정치이므로 실제 동작 시 조정이 필요할 수 있다.
"""

from __future__ import annotations

import httpx
import structlog

from jibgooham.crawlers.base import BaseCrawler
from jibgooham.models.search_params import SearchParams

logger = structlog.get_logger(__name__)

# --- 다방 API 엔드포인트 ---
DABANG_BASE_URL = "https://www.dabangapp.com/api"
DABANG_REGION_SEARCH_URL = f"{DABANG_BASE_URL}/3/region/search"
DABANG_ROOM_LIST_URL = f"{DABANG_BASE_URL}/3/room/new-list/multi-room/info"

# --- 요청 설정 ---
DABANG_TIMEOUT = 15.0
DABANG_HEADERS = {
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.dabangapp.com/",
}

DABANG_SELLING_TYPE_MAP = {
    "월세": 0,
    "전세": 1,
    "매매": 2,
}
DABANG_ROOM_TYPE_MAP = {
    "원룸": "oneRoom",
    "투룸": "twoRoom",
    "오피스텔": "officetel",
    "아파트": "apartment",
    "빌라": "villa",
}


class DabangCrawler(BaseCrawler):
    """다방 매물 크롤러.

    다방 API를 통해 지역 검색 → 매물 목록 조회 순서로 데이터를 수집한다.
    """

    platform: str = "dabang"

    async def search(self, params: SearchParams) -> list[dict]:
        """다방에서 매물 검색.

        1. 지역명 → 지역 ID 조회
        2. 지역 ID 기반 매물 목록 조회

        Args:
            params: 검색 조건

        Returns:
            다방 원본 형태의 매물 딕셔너리 리스트
        """
        self._log.info("다방 검색 시작", region=params.region)

        async with httpx.AsyncClient(
            timeout=DABANG_TIMEOUT, headers=DABANG_HEADERS
        ) as client:
            # 1단계: 지역명 → 지역 ID 조회
            region_info = await self._search_region(client, params.region)
            if not region_info:
                self._log.warning("지역 검색 결과 없음", region=params.region)
                return []

            # 2단계: 지역 ID → 매물 목록 조회
            rooms = await self._get_room_list(client, region_info, params)

            self._log.info("다방 검색 완료", count=len(rooms))
            return rooms

    async def get_detail(self, listing_id: str) -> dict:
        """다방 매물 단건 상세 조회.

        Args:
            listing_id: 다방 매물 ID

        Returns:
            매물 상세 정보 딕셔너리
        """
        url = f"{DABANG_BASE_URL}/3/room/detail"

        async with httpx.AsyncClient(
            timeout=DABANG_TIMEOUT, headers=DABANG_HEADERS
        ) as client:
            response = await self._rate_limited_get(
                client,
                url,
                params={"id": listing_id},
            )
            if response.status_code != 200:
                self._log.error("매물 상세 조회 실패", status=response.status_code)
                return {}

            data = response.json()
            return data.get("room", data)

    async def _search_region(
        self, client: httpx.AsyncClient, region: str
    ) -> dict | None:
        """지역명으로 지역 정보 조회.

        Args:
            client: httpx 비동기 클라이언트
            region: 지역명

        Returns:
            지역 정보 딕셔너리 (id, name, code 등) 또는 None
        """
        response = await self._rate_limited_get(
            client,
            DABANG_REGION_SEARCH_URL,
            params={"keyword": region},
        )
        if response.status_code != 200:
            self._log.error("지역 검색 실패", status=response.status_code)
            return None

        data = response.json()
        # 응답 구조: {"result": [{"id": "...", "name": "...", "code": "..."}]}
        results = data.get("result", [])
        if not results:
            return None

        return results[0]

    async def _get_room_list(
        self,
        client: httpx.AsyncClient,
        region_info: dict,
        params: SearchParams,
    ) -> list[dict]:
        """지역 정보 기반 매물 목록 조회.

        Args:
            client: httpx 비동기 클라이언트
            region_info: 지역 정보 딕셔너리
            params: 검색 조건

        Returns:
            매물 딕셔너리 리스트
        """
        selling_type = DABANG_SELLING_TYPE_MAP.get(params.deal_type, 0)
        room_type = DABANG_ROOM_TYPE_MAP.get(params.room_type, "oneRoom")

        query_params = {
            "api_version": 5,
            "call_type": "web",
            "code": region_info.get("code", ""),
            "room_type": room_type,
            "selling_type": selling_type,
            "deposit_min": params.deposit_min,
            "deposit_max": params.deposit_max,
            "price_min": params.rent_min,
            "price_max": params.rent_max,
            "size_min": params.area_min,
            "size_max": params.area_max,
            "page": 1,
        }

        response = await self._rate_limited_get(
            client,
            DABANG_ROOM_LIST_URL,
            params=query_params,
        )
        if response.status_code != 200:
            self._log.error("매물 목록 조회 실패", status=response.status_code)
            return []

        data = response.json()
        # 응답 구조: {"rooms": [{...}, ...]} 또는 {"result": [{...}, ...]}
        rooms = data.get("rooms", data.get("result", []))
        return rooms[: params.limit]
