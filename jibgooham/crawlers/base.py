"""크롤러 추상 클래스 모듈."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod

import httpx
import structlog

from jibgooham.models.search_params import SearchParams

logger = structlog.get_logger(__name__)

# Rate limit 기본값 (초)
DEFAULT_REQUEST_INTERVAL: float = 0.5
# 429 응답 시 대기 시간 (초)
RATE_LIMIT_WAIT: int = 300


class BaseCrawler(ABC):
    """모든 플랫폼 크롤러의 기반 클래스."""

    platform: str  # "zigbang" | "naver" | "daangn" | "dabang"

    def __init__(self) -> None:
        self._last_request_time: float = 0.0
        self._log = logger.bind(platform=self.platform)

    @abstractmethod
    async def search(self, params: SearchParams) -> list[dict]:
        """매물 검색. raw dict 리스트 반환 (정규화 전).

        Args:
            params: 검색 조건

        Returns:
            플랫폼 원본 형태의 매물 딕셔너리 리스트
        """
        ...

    @abstractmethod
    async def get_detail(self, listing_id: str) -> dict:
        """매물 상세 조회.

        Args:
            listing_id: 플랫폼별 매물 ID

        Returns:
            매물 상세 정보 딕셔너리
        """
        ...

    async def _rate_limited_get(
        self,
        client: httpx.AsyncClient,
        url: str,
        **kwargs,
    ) -> httpx.Response:
        """Rate limit을 준수하며 GET 요청 수행.

        요청 간격을 DEFAULT_REQUEST_INTERVAL 이상 유지하고,
        429 응답 시 RATE_LIMIT_WAIT초 대기 후 재시도한다.

        Args:
            client: httpx 비동기 클라이언트
            url: 요청 URL
            **kwargs: httpx.get에 전달할 추가 인자

        Returns:
            HTTP 응답 객체

        Raises:
            httpx.HTTPStatusError: 재시도 후에도 실패할 경우
        """
        # 요청 간격 보장
        now = asyncio.get_event_loop().time()
        elapsed = now - self._last_request_time
        if elapsed < DEFAULT_REQUEST_INTERVAL:
            await asyncio.sleep(DEFAULT_REQUEST_INTERVAL - elapsed)

        self._log.debug("HTTP GET 요청", url=url)
        response = await client.get(url, **kwargs)
        self._last_request_time = asyncio.get_event_loop().time()

        # 429 Too Many Requests 처리
        if response.status_code == 429:
            self._log.warning(
                "Rate limit 초과, 대기 후 재시도",
                wait_seconds=RATE_LIMIT_WAIT,
            )
            await asyncio.sleep(RATE_LIMIT_WAIT)
            response = await client.get(url, **kwargs)
            self._last_request_time = asyncio.get_event_loop().time()
            response.raise_for_status()

        return response

    async def _rate_limited_post(
        self,
        client: httpx.AsyncClient,
        url: str,
        **kwargs,
    ) -> httpx.Response:
        """Rate limit을 준수하며 POST 요청 수행.

        _rate_limited_get과 동일한 로직이지만 POST 메서드 사용.

        Args:
            client: httpx 비동기 클라이언트
            url: 요청 URL
            **kwargs: httpx.post에 전달할 추가 인자

        Returns:
            HTTP 응답 객체
        """
        now = asyncio.get_event_loop().time()
        elapsed = now - self._last_request_time
        if elapsed < DEFAULT_REQUEST_INTERVAL:
            await asyncio.sleep(DEFAULT_REQUEST_INTERVAL - elapsed)

        self._log.debug("HTTP POST 요청", url=url)
        response = await client.post(url, **kwargs)
        self._last_request_time = asyncio.get_event_loop().time()

        if response.status_code == 429:
            self._log.warning(
                "Rate limit 초과, 대기 후 재시도",
                wait_seconds=RATE_LIMIT_WAIT,
            )
            await asyncio.sleep(RATE_LIMIT_WAIT)
            response = await client.post(url, **kwargs)
            self._last_request_time = asyncio.get_event_loop().time()
            response.raise_for_status()

        return response
