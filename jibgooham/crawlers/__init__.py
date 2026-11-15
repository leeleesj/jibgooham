"""크롤러 패키지.

4개 플랫폼 크롤러를 통합 제공하고,
search_all()로 모든 플랫폼을 병렬 검색할 수 있다.
"""

from __future__ import annotations

import asyncio

import structlog

from jibgooham.crawlers.base import BaseCrawler
from jibgooham.crawlers.daangn import DaangnCrawler
from jibgooham.crawlers.dabang import DabangCrawler
from jibgooham.crawlers.naver import NaverCrawler
from jibgooham.crawlers.zigbang import ZigbangCrawler
from jibgooham.models.search_params import SearchParams

__all__ = [
    "BaseCrawler",
    "DaangnCrawler",
    "DabangCrawler",
    "NaverCrawler",
    "ZigbangCrawler",
    "search_all",
]

logger = structlog.get_logger(__name__)

# 플랫폼 이름 → 크롤러 클래스 매핑
CRAWLER_REGISTRY: dict[str, type[BaseCrawler]] = {
    "zigbang": ZigbangCrawler,
    "naver": NaverCrawler,
    "daangn": DaangnCrawler,
    "dabang": DabangCrawler,
}


async def search_all(params: SearchParams) -> dict[str, list[dict]]:
    """모든 플랫폼을 병렬로 검색.

    params.platforms에 지정된 플랫폼만 검색하며,
    개별 플랫폼이 실패해도 다른 플랫폼 결과에 영향을 주지 않는다.

    Args:
        params: 검색 조건 (platforms 필드로 대상 플랫폼 지정)

    Returns:
        {플랫폼명: 매물 리스트} 딕셔너리.
        실패한 플랫폼은 빈 리스트로 포함된다.
    """
    results: dict[str, list[dict]] = {}

    async def _search_platform(platform: str) -> tuple[str, list[dict]]:
        """단일 플랫폼 검색 (에러 격리)."""
        crawler_cls = CRAWLER_REGISTRY.get(platform)
        if not crawler_cls:
            logger.warning("알 수 없는 플랫폼", platform=platform)
            return platform, []

        try:
            crawler = crawler_cls()
            items = await crawler.search(params)
            return platform, items
        except Exception as exc:
            logger.error(
                "플랫폼 검색 실패",
                platform=platform,
                error=str(exc),
            )
            return platform, []

    # asyncio.TaskGroup으로 병렬 실행
    async with asyncio.TaskGroup() as tg:
        tasks = {
            platform: tg.create_task(_search_platform(platform))
            for platform in params.platforms
            if platform in CRAWLER_REGISTRY
        }

    for platform, task in tasks.items():
        _platform_name, items = task.result()
        results[_platform_name] = items

    total = sum(len(v) for v in results.values())
    logger.info("전체 검색 완료", platforms=list(results.keys()), total=total)

    return results
