"""당근 부동산 크롤러 모듈.

당근마켓 부동산은 SPA로 구현되어 있어 Playwright로 페이지를 렌더링하고,
네트워크 요청을 인터셉트하여 JSON API 응답을 캡처하는 방식을 사용한다.

Playwright가 설치되어 있지 않으면 graceful degradation으로 빈 결과를 반환한다.
"""

from __future__ import annotations

import asyncio

import structlog

from jibgooham.crawlers.base import BaseCrawler
from jibgooham.models.search_params import SearchParams

logger = structlog.get_logger(__name__)

# --- 당근 부동산 URL ---
DAANGN_BASE_URL = "https://www.daangn.com"
DAANGN_REALTY_URL = f"{DAANGN_BASE_URL}/realty"
# 당근 API 응답에서 매물 데이터가 포함된 URL 패턴
DAANGN_API_PATTERN = "api.daangn.com"
DAANGN_REALTY_API_PATTERN = "/realty"

# --- 요청 설정 ---
DAANGN_PAGE_TIMEOUT_MS = 30_000
DAANGN_NAVIGATION_TIMEOUT_MS = 15_000

# Playwright 사용 가능 여부 플래그
_PLAYWRIGHT_AVAILABLE = True
try:
    from playwright.async_api import async_playwright
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False
    logger.warning("Playwright 미설치. 당근 부동산 크롤링 비활성화.")


class DaangnCrawler(BaseCrawler):
    """당근마켓 부동산 크롤러.

    Playwright headless Chromium으로 페이지에 접속하고,
    네트워크 요청을 인터셉트하여 매물 데이터 JSON을 캡처한다.
    Playwright가 설치되지 않은 환경에서는 빈 결과를 반환한다.
    """

    platform: str = "daangn"

    async def search(self, params: SearchParams) -> list[dict]:
        """당근 부동산에서 매물 검색.

        Playwright로 검색 페이지를 렌더링하고 API 응답을 인터셉트한다.

        Args:
            params: 검색 조건

        Returns:
            당근 원본 형태의 매물 딕셔너리 리스트
        """
        if not _PLAYWRIGHT_AVAILABLE:
            self._log.warning("Playwright 미설치로 검색 건너뜀")
            return []

        self._log.info("당근 부동산 검색 시작", region=params.region)

        captured_items: list[dict] = []

        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                )
                page = await context.new_page()
                page.set_default_timeout(DAANGN_PAGE_TIMEOUT_MS)

                # 네트워크 응답 인터셉트
                async def _handle_response(response):
                    """API 응답에서 매물 데이터 캡처."""
                    url = response.url
                    if (
                        DAANGN_API_PATTERN in url
                        and DAANGN_REALTY_API_PATTERN in url
                        and response.status == 200
                    ):
                        try:
                            data = await response.json()
                            # 응답 구조에 따라 매물 리스트 추출
                            items = _extract_items(data)
                            captured_items.extend(items)
                        except Exception:
                            # JSON 파싱 실패 무시
                            pass

                page.on("response", _handle_response)

                # 검색 페이지 접속
                search_url = f"{DAANGN_REALTY_URL}?query={params.region}"
                await page.goto(
                    search_url,
                    wait_until="networkidle",
                    timeout=DAANGN_NAVIGATION_TIMEOUT_MS,
                )

                # 동적 로딩 대기
                await asyncio.sleep(2)

                await browser.close()

        except Exception as exc:
            self._log.error("당근 부동산 크롤링 실패", error=str(exc))
            return []

        self._log.info("당근 부동산 검색 완료", count=len(captured_items))
        return captured_items[: params.limit]

    async def get_detail(self, listing_id: str) -> dict:
        """당근 부동산 매물 단건 상세 조회.

        개별 매물 페이지에 접속하여 데이터를 캡처한다.

        Args:
            listing_id: 당근 매물 ID

        Returns:
            매물 상세 정보 딕셔너리
        """
        if not _PLAYWRIGHT_AVAILABLE:
            self._log.warning("Playwright 미설치로 상세 조회 건너뜀")
            return {}

        captured_detail: dict = {}

        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                context = await browser.new_context()
                page = await context.new_page()
                page.set_default_timeout(DAANGN_PAGE_TIMEOUT_MS)

                async def _handle_response(response):
                    nonlocal captured_detail
                    url = response.url
                    if (
                        DAANGN_API_PATTERN in url
                        and listing_id in url
                        and response.status == 200
                    ):
                        try:
                            captured_detail = await response.json()
                        except Exception:
                            pass

                page.on("response", _handle_response)

                detail_url = f"{DAANGN_REALTY_URL}/{listing_id}"
                await page.goto(
                    detail_url,
                    wait_until="networkidle",
                    timeout=DAANGN_NAVIGATION_TIMEOUT_MS,
                )
                await asyncio.sleep(1)
                await browser.close()

        except Exception as exc:
            self._log.error("당근 부동산 상세 조회 실패", error=str(exc))
            return {}

        return captured_detail


def _extract_items(data: dict) -> list[dict]:
    """API 응답에서 매물 리스트 추출.

    당근 API 응답 구조가 변경될 수 있으므로
    여러 가능한 키를 탐색한다.

    Args:
        data: API 응답 딕셔너리

    Returns:
        매물 딕셔너리 리스트
    """
    # 가능한 응답 키 패턴 탐색
    candidate_keys = ["articles", "items", "data", "results", "listings"]
    for key in candidate_keys:
        if key in data and isinstance(data[key], list):
            return data[key]

    # 중첩 구조: {"data": {"articles": [...]}}
    if "data" in data and isinstance(data["data"], dict):
        for key in candidate_keys:
            if key in data["data"] and isinstance(data["data"][key], list):
                return data["data"][key]

    return []
