"""집구함 — Streamlit 메인 앱.

3개 탭으로 구성:
1. 매물 검색 (크롤링 + 정규화 + 중복제거 + 스코어링 + 지도)
2. 중개소 검색 (V-World 중개사 검증)
3. 버팀목 대출 자격 확인 및 한도 계산
"""

from __future__ import annotations

import asyncio
from typing import Any

import folium
import streamlit as st
from streamlit_folium import st_folium

from jibgooham.aggregator import deduplicate, normalize, score_listings
from jibgooham.config import SUPPORTED_PLATFORMS
from jibgooham.crawlers import search_all
from jibgooham.models.listing import UnifiedListing
from jibgooham.models.search_params import ScoringWeights, SearchParams
from jibgooham.vworld import (
    enrich_listings_with_broker,
    enrich_listings_with_building,
    verify_broker,
)

# --- 상수 ---
DEAL_TYPES = ["월세", "전세", "매매"]
ROOM_TYPES = ["원룸", "투룸", "오피스텔", "아파트", "빌라"]
PLATFORM_LABELS: dict[str, str] = {
    "zigbang": "직방",
    "naver": "네이버",
    "daangn": "당근",
    "dabang": "다방",
}
PLATFORM_KEYS = list(PLATFORM_LABELS.keys())

# 기본 지도 중심 (서울시청)
DEFAULT_LAT = 37.5665
DEFAULT_LNG = 126.9780

# 스코어링 가중치 설정
WEIGHT_FIELDS: list[dict[str, str | float]] = [
    {"key": "station_distance", "label": "역 거리", "default": 1.5},
    {"key": "price", "label": "가격", "default": 1.5},
    {"key": "area", "label": "면적", "default": 1.0},
    {"key": "building_age", "label": "건축연도", "default": 1.0},
    {"key": "broker_trust", "label": "중개사 신뢰도", "default": 1.5},
    {"key": "image_count", "label": "이미지 수", "default": 0.3},
]

# 버팀목 대출 상수
LOAN_AGE_MIN = 19
LOAN_AGE_MAX = 34
LOAN_INCOME_MAX_SINGLE = 5000  # 만원
LOAN_DEPOSIT_MAX_METRO = 30000  # 만원 (수도권 3억)
LOAN_DEPOSIT_MAX_LOCAL = 20000  # 만원 (지방 2억)
LOAN_AREA_MAX_M2 = 85.0
LOAN_RATIO = 0.80
LOAN_LIMIT_MAX = 20000  # 만원 (최대 2억)
LOAN_RATE_TIERS: list[dict[str, Any]] = [
    {"max_income": 2000, "rate": 0.015, "label": "2천만원 이하"},
    {"max_income": 4000, "rate": 0.020, "label": "4천만원 이하"},
    {"max_income": 5000, "rate": 0.021, "label": "5천만원 이하"},
]

# 지도 핀 색상 기준
SCORE_COLOR_HIGH = 80
SCORE_COLOR_MID = 60


def _run_async(coro: Any) -> Any:
    """Streamlit 환경에서 async 함수를 동기적으로 실행."""
    return asyncio.run(coro)


# =====================================================================
# 탭 1: 매물 검색
# =====================================================================

def _render_sidebar_search() -> dict[str, Any] | None:
    """사이드바에 매물 검색 조건 위젯을 렌더링한다.

    Returns:
        검색 버튼이 눌리면 검색 파라미터 dict, 아니면 None
    """
    st.sidebar.header("검색 조건")

    region = st.sidebar.text_input("지역", value="강남역")
    deal_type = st.sidebar.selectbox("거래 유형", DEAL_TYPES)
    room_type = st.sidebar.selectbox("방 유형", ROOM_TYPES)

    deposit_range = st.sidebar.slider(
        "보증금 범위 (만원)", min_value=0, max_value=50000, value=(0, 50000), step=100,
    )

    # 월세 슬라이더: 월세 선택 시에만 표시
    rent_range = (0, 200)
    if deal_type == "월세":
        rent_range = st.sidebar.slider(
            "월세 범위 (만원)", min_value=0, max_value=200, value=(0, 200), step=5,
        )

    # 플랫폼 선택
    selected_platforms = st.sidebar.multiselect(
        "플랫폼",
        options=PLATFORM_KEYS,
        default=PLATFORM_KEYS,
        format_func=lambda x: PLATFORM_LABELS[x],
    )

    st.sidebar.divider()
    st.sidebar.subheader("스코어링 가중치")

    weights: dict[str, float] = {}
    for field in WEIGHT_FIELDS:
        weights[field["key"]] = st.sidebar.slider(
            field["label"],
            min_value=0.0,
            max_value=3.0,
            value=float(field["default"]),
            step=0.5,
            key=f"weight_{field['key']}",
        )

    if st.sidebar.button("🔍 검색", use_container_width=True):
        return {
            "region": region,
            "deal_type": deal_type,
            "room_type": room_type,
            "deposit_min": deposit_range[0],
            "deposit_max": deposit_range[1],
            "rent_min": rent_range[0],
            "rent_max": rent_range[1],
            "platforms": selected_platforms if selected_platforms else PLATFORM_KEYS,
            "weights": weights,
        }
    return None


def _get_pin_color(score: float | None) -> str:
    """점수에 따른 지도 핀 색상을 반환한다."""
    if score is None:
        return "gray"
    if score >= SCORE_COLOR_HIGH:
        return "green"
    if score >= SCORE_COLOR_MID:
        return "orange"
    return "red"


def _build_listing_map(listings: list[UnifiedListing]) -> folium.Map:
    """매물 리스트로 Folium 지도를 생성한다."""
    # 위경도 있는 매물로 중심 결정
    geo_listings = [l for l in listings if l.latitude and l.longitude]

    if geo_listings:
        center_lat = sum(l.latitude for l in geo_listings) / len(geo_listings)
        center_lng = sum(l.longitude for l in geo_listings) / len(geo_listings)
    else:
        center_lat, center_lng = DEFAULT_LAT, DEFAULT_LNG

    m = folium.Map(location=[center_lat, center_lng], zoom_start=14)

    for listing in geo_listings:
        color = _get_pin_color(listing.score)
        score_text = f"{listing.score:.1f}점" if listing.score is not None else "미평가"
        popup_html = (
            f"<b>{listing.title}</b><br>"
            f"💰 보증금 {listing.deposit:,}만원"
            f"{f' / 월세 {listing.monthly_rent:,}만원' if listing.monthly_rent else ''}<br>"
            f"📐 {listing.area_m2:.1f}㎡ | {listing.room_type}<br>"
            f"⭐ {score_text}"
        )
        folium.Marker(
            location=[listing.latitude, listing.longitude],
            popup=folium.Popup(popup_html, max_width=300),
            icon=folium.Icon(color=color, icon="home", prefix="fa"),
        ).add_to(m)

    return m


def _render_listing_card(listing: UnifiedListing) -> None:
    """매물 카드를 st.expander로 렌더링한다."""
    score_text = f"{listing.score:.1f}점" if listing.score is not None else "미평가"
    price_text = f"보증금 {listing.deposit:,}만원"
    if listing.monthly_rent:
        price_text += f" / 월세 {listing.monthly_rent:,}만원"

    label = f"⭐ {score_text} | {listing.title} | {price_text}"

    with st.expander(label, expanded=False):
        # 이미지 표시
        if listing.images:
            st.image(listing.images[0], use_container_width=True)

        # 기본 정보
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"**💰 가격:** {price_text}")
            st.markdown(f"**📐 면적:** {listing.area_m2:.1f}㎡")
            if listing.floor is not None:
                floor_display = "반지하" if listing.floor == -1 else f"{listing.floor}층"
                if listing.building_floor:
                    floor_display += f" / {listing.building_floor}층"
                st.markdown(f"**🏢 층수:** {floor_display}")
        with col2:
            st.markdown(f"**🏠 유형:** {listing.room_type} ({listing.deal_type})")
            st.markdown(f"**📍 주소:** {listing.address}")
            if listing.amenities:
                st.markdown(f"**🔧 옵션:** {', '.join(listing.amenities)}")

        # V-World 건물 정보
        if listing.built_year or listing.building_structure or listing.land_use:
            st.markdown("---")
            st.markdown("**🏗️ V-World 건물 정보**")
            info_parts = []
            if listing.built_year:
                info_parts.append(f"준공연도: {listing.built_year}년")
            if listing.building_structure:
                info_parts.append(f"구조: {listing.building_structure}")
            if listing.land_use:
                info_parts.append(f"용도: {listing.land_use}")
            st.markdown(" | ".join(info_parts))

        # 중개소 신뢰도
        if listing.broker:
            st.markdown("---")
            trust = listing.broker.trust_level
            trust_emoji = {"high": "🟢", "medium": "🟡", "low": "🟠", "danger": "🔴"}.get(trust, "⚪")
            st.markdown(
                f"**{trust_emoji} 중개소:** {listing.broker.name} "
                f"({listing.broker.position}) — 신뢰도: {trust}"
            )

        # 플랫폼 링크
        st.link_button(
            f"📎 {PLATFORM_LABELS.get(listing.platform, listing.platform)}에서 보기",
            listing.url,
        )

        # 다른 플랫폼에도 등록된 경우
        if listing.also_on:
            also_labels = [PLATFORM_LABELS.get(p, p) for p in listing.also_on]
            st.caption(f"이 매물은 {', '.join(also_labels)}에도 등록되어 있습니다.")


def _run_search(params: dict[str, Any]) -> None:
    """매물 검색을 실행하고 session_state에 결과를 저장한다."""
    weights = ScoringWeights(**params["weights"])
    search_params = SearchParams(
        region=params["region"],
        deal_type=params["deal_type"],
        room_type=params["room_type"],
        deposit_min=params["deposit_min"],
        deposit_max=params["deposit_max"],
        rent_min=params["rent_min"],
        rent_max=params["rent_max"],
        platforms=params["platforms"],
        weights=weights,
    )

    with st.spinner("매물을 검색하고 있습니다..."):
        # 1. 크롤링
        try:
            raw_results = _run_async(search_all(search_params))
        except Exception as e:
            st.warning(f"크롤러 실행 중 오류가 발생했습니다: {e}")
            raw_results = {}

        # 2. 정규화
        all_listings: list[UnifiedListing] = []
        for platform, raw_list in raw_results.items():
            if not raw_list:
                st.warning(f"{PLATFORM_LABELS.get(platform, platform)}: 검색 결과 없음")
                continue
            normalized = normalize(platform, raw_list)
            all_listings.extend(normalized)

        total_before_dedup = len(all_listings)

        # 3. 중복 제거
        unique_listings = deduplicate(all_listings)

        # 4. V-World 건물 정보 보강
        try:
            unique_listings = _run_async(enrich_listings_with_building(unique_listings))
        except Exception as e:
            st.warning(f"건물 정보 조회 실패 (계속 진행): {e}")

        # 5. V-World 중개소 검증
        try:
            unique_listings = _run_async(enrich_listings_with_broker(unique_listings))
        except Exception as e:
            st.warning(f"중개소 검증 실패 (계속 진행): {e}")

        # 6. 스코어링
        scored = score_listings(unique_listings, weights, search_params)

    # session_state에 결과 저장
    st.session_state["search_results"] = scored
    st.session_state["search_total_before_dedup"] = total_before_dedup
    st.session_state["search_params"] = params


def _render_tab_search() -> None:
    """탭 1: 매물 검색 전체를 렌더링한다."""
    # 사이드바 검색 조건
    params = _render_sidebar_search()
    if params is not None:
        _run_search(params)

    # 결과가 있으면 표시
    results: list[UnifiedListing] = st.session_state.get("search_results", [])
    if not results:
        st.info("왼쪽 사이드바에서 검색 조건을 설정한 후 [검색] 버튼을 눌러주세요.")
        return

    total_before = st.session_state.get("search_total_before_dedup", 0)

    # 통계 표시
    deposits = [l.deposit for l in results if l.deposit > 0]
    avg_deposit = sum(deposits) / len(deposits) if deposits else 0

    scores = [l.score for l in results if l.score is not None]
    avg_score = sum(scores) / len(scores) if scores else 0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("총 매물 수", f"{total_before}건")
    col2.metric("중복 제거 후", f"{len(results)}건")
    col3.metric("평균 보증금", f"{avg_deposit:,.0f}만원")
    col4.metric("평균 점수", f"{avg_score:.1f}점")

    # 지도 + 매물 카드 레이아웃
    map_col, list_col = st.columns([3, 2])

    with map_col:
        st.subheader("지도")
        listing_map = _build_listing_map(results)
        st_folium(listing_map, use_container_width=True, height=600)

    with list_col:
        st.subheader(f"매물 목록 ({len(results)}건)")
        for listing in results:
            _render_listing_card(listing)


# =====================================================================
# 탭 2: 중개소 검색
# =====================================================================

def _render_sidebar_broker() -> str | None:
    """사이드바에 중개소 검색 위젯을 렌더링한다."""
    st.sidebar.header("중개소 검색")
    broker_name = st.sidebar.text_input("중개소명 또는 지역", key="broker_search_input")
    if st.sidebar.button("🏢 검색", use_container_width=True, key="broker_search_btn"):
        return broker_name if broker_name.strip() else None
    return None


def _run_broker_search(query: str) -> None:
    """중개소 검색을 실행하고 session_state에 저장한다."""
    with st.spinner("중개소 정보를 조회하고 있습니다..."):
        try:
            result = _run_async(verify_broker(query))
        except Exception as e:
            st.warning(f"중개소 조회 중 오류 발생: {e}")
            result = None

    if result is not None:
        st.session_state["broker_results"] = [result]
    else:
        st.session_state["broker_results"] = []
        st.warning(f"'{query}'에 대한 중개소 정보를 찾을 수 없습니다.")


def _build_broker_map(brokers: list[Any]) -> folium.Map:
    """중개소 목록으로 Folium 지도를 생성한다."""
    m = folium.Map(location=[DEFAULT_LAT, DEFAULT_LNG], zoom_start=13)
    for broker in brokers:
        if broker.address:
            popup_html = (
                f"<b>{broker.name}</b><br>"
                f"직위: {broker.position}<br>"
                f"상태: {broker.status}"
            )
            # 중개소 주소는 위경도가 없으므로 마커 대신 주소 텍스트 표시
            folium.Marker(
                location=[DEFAULT_LAT, DEFAULT_LNG],
                popup=folium.Popup(popup_html, max_width=300),
                icon=folium.Icon(color="blue", icon="briefcase", prefix="fa"),
            ).add_to(m)
    return m


def _render_broker_card(broker: Any) -> None:
    """중개소 정보 카드를 렌더링한다."""
    trust = broker.trust_level
    trust_emoji = {"high": "🟢", "medium": "🟡", "low": "🟠", "danger": "🔴"}.get(trust, "⚪")

    with st.expander(f"{trust_emoji} {broker.name}", expanded=True):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"**직위:** {broker.position}")
            if broker.opened_at:
                st.markdown(f"**개업일:** {broker.opened_at}")
            st.markdown(f"**상태:** {broker.status}")
        with col2:
            if broker.registration_no:
                st.markdown(f"**등록번호:** {broker.registration_no}")
            if broker.representative:
                st.markdown(f"**대표자:** {broker.representative}")
            if broker.address:
                st.markdown(f"**주소:** {broker.address}")

        st.markdown(f"**신뢰도:** {trust_emoji} {trust}")

        # 카카오지도 링크
        if broker.address:
            kakao_url = f"https://map.kakao.com/?q={broker.address}"
            st.link_button("🗺️ 카카오지도에서 보기", kakao_url)
        elif broker.name:
            kakao_url = f"https://map.kakao.com/?q={broker.name}"
            st.link_button("🗺️ 카카오지도에서 보기", kakao_url)


def _render_tab_broker() -> None:
    """탭 2: 중개소 검색 전체를 렌더링한다."""
    query = _render_sidebar_broker()
    if query is not None:
        _run_broker_search(query)

    brokers = st.session_state.get("broker_results", [])
    if not brokers:
        st.info("사이드바에서 중개소명 또는 지역을 입력하고 [검색] 버튼을 눌러주세요.")
        return

    # 지도
    st.subheader("중개소 위치")
    broker_map = _build_broker_map(brokers)
    st_folium(broker_map, use_container_width=True, height=400)

    # 카드 목록
    st.subheader(f"검색 결과 ({len(brokers)}건)")
    for broker in brokers:
        _render_broker_card(broker)


# =====================================================================
# 탭 3: 버팀목 대출
# =====================================================================

def _render_sidebar_loan() -> dict[str, Any] | None:
    """사이드바에 버팀목 대출 자격 확인 위젯을 렌더링한다."""
    st.sidebar.header("버팀목 대출 자격 확인")

    age = st.sidebar.number_input("나이 (만 나이)", min_value=0, max_value=100, value=25, key="loan_age")
    income = st.sidebar.number_input("연소득 (만원)", min_value=0, max_value=100000, value=3000, step=100, key="loan_income")
    is_homeless = st.sidebar.checkbox("무주택 여부", value=True, key="loan_homeless")
    is_married = st.sidebar.checkbox("혼인 여부", value=False, key="loan_married")
    region_type = st.sidebar.selectbox("지역", ["수도권", "지방"], key="loan_region")
    deposit = st.sidebar.number_input("희망 보증금 (만원)", min_value=0, max_value=100000, value=10000, step=100, key="loan_deposit")
    area = st.sidebar.number_input("전용면적 (㎡)", min_value=0.0, max_value=300.0, value=33.0, step=1.0, key="loan_area")

    if st.sidebar.button("🏦 자격 확인", use_container_width=True, key="loan_btn"):
        return {
            "age": age,
            "income": income,
            "is_homeless": is_homeless,
            "is_married": is_married,
            "region_type": region_type,
            "deposit": deposit,
            "area": area,
        }
    return None


def _check_loan_eligibility(params: dict[str, Any]) -> dict[str, Any]:
    """버팀목 대출 자격 조건을 확인하고 한도를 계산한다."""
    age = params["age"]
    income = params["income"]
    is_homeless = params["is_homeless"]
    region_type = params["region_type"]
    deposit = params["deposit"]
    area = params["area"]

    deposit_limit = LOAN_DEPOSIT_MAX_METRO if region_type == "수도권" else LOAN_DEPOSIT_MAX_LOCAL

    # 각 조건 체크
    checks = {
        "나이": {
            "pass": LOAN_AGE_MIN <= age <= LOAN_AGE_MAX,
            "detail": f"만 {LOAN_AGE_MIN}~{LOAN_AGE_MAX}세 (현재: 만 {age}세)",
        },
        "연소득": {
            "pass": income <= LOAN_INCOME_MAX_SINGLE,
            "detail": f"단독세대주 {LOAN_INCOME_MAX_SINGLE:,}만원 이하 (현재: {income:,}만원)",
        },
        "무주택 세대주": {
            "pass": is_homeless,
            "detail": "무주택 세대주 여부",
        },
        "보증금": {
            "pass": deposit <= deposit_limit,
            "detail": f"{region_type} {deposit_limit:,}만원 이하 (현재: {deposit:,}만원)",
        },
        "면적": {
            "pass": area <= LOAN_AREA_MAX_M2,
            "detail": f"{LOAN_AREA_MAX_M2}㎡ 이하 (현재: {area:.1f}㎡)",
        },
    }

    all_pass = all(c["pass"] for c in checks.values())

    # 대출 한도 계산
    loan_amount = min(int(deposit * LOAN_RATIO), LOAN_LIMIT_MAX)

    # 금리 결정
    rate = LOAN_RATE_TIERS[-1]["rate"]  # 기본값: 최고 구간
    rate_label = LOAN_RATE_TIERS[-1]["label"]
    for tier in LOAN_RATE_TIERS:
        if income <= tier["max_income"]:
            rate = tier["rate"]
            rate_label = tier["label"]
            break

    # 월 이자 계산
    monthly_interest = loan_amount * rate / 12

    # 내 부담금
    my_cost = deposit - loan_amount

    return {
        "checks": checks,
        "all_pass": all_pass,
        "loan_amount": loan_amount,
        "rate": rate,
        "rate_label": rate_label,
        "monthly_interest": monthly_interest,
        "my_cost": my_cost,
        "deposit": deposit,
    }


def _render_tab_loan() -> None:
    """탭 3: 버팀목 대출 자격 확인을 렌더링한다."""
    params = _render_sidebar_loan()
    if params is not None:
        result = _check_loan_eligibility(params)
        st.session_state["loan_result"] = result

    result = st.session_state.get("loan_result")
    if result is None:
        st.info("사이드바에서 정보를 입력한 후 [자격 확인] 버튼을 눌러주세요.")
        return

    # 자격 조건 체크 결과
    st.subheader("자격 조건 체크")
    for name, check in result["checks"].items():
        icon = "✅" if check["pass"] else "❌"
        st.markdown(f"{icon} **{name}**: {check['detail']}")

    st.divider()

    if result["all_pass"]:
        st.success("모든 자격 조건을 충족합니다!")
    else:
        failed = [name for name, c in result["checks"].items() if not c["pass"]]
        st.error(f"불충족 항목: {', '.join(failed)}")

    # 대출 한도 계산 결과 (조건 불충족이어도 참고용으로 표시)
    st.subheader("대출 한도 계산 (참고)")

    col1, col2, col3 = st.columns(3)
    col1.metric("대출 가능 금액", f"{result['loan_amount']:,}만원")
    col2.metric("적용 금리", f"{result['rate'] * 100:.1f}% ({result['rate_label']})")
    col3.metric("월 이자", f"{result['monthly_interest']:,.0f}만원")

    st.divider()

    col_a, col_b = st.columns(2)
    col_a.metric("보증금", f"{result['deposit']:,}만원")
    col_b.metric("내 부담금", f"{result['my_cost']:,}만원")

    st.caption(
        f"* 대출 한도: 보증금의 {int(LOAN_RATIO * 100)}% (최대 {LOAN_LIMIT_MAX:,}만원)\n"
        f"* 월 이자 = 대출금 x 금리 / 12"
    )


# =====================================================================
# 메인 앱
# =====================================================================

def main() -> None:
    """Streamlit 앱 진입점."""
    st.set_page_config(
        page_title="집구함",
        page_icon="🏠",
        layout="wide",
    )

    st.title("🏠 집구함 — 통합 부동산 검색")

    tab_search, tab_broker, tab_loan = st.tabs([
        "🔍 매물 검색",
        "🏢 중개소 검색",
        "🏦 버팀목 대출",
    ])

    with tab_search:
        _render_tab_search()

    with tab_broker:
        _render_tab_broker()

    with tab_loan:
        _render_tab_loan()


if __name__ == "__main__":
    main()
