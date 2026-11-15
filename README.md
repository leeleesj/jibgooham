# 🏠 jibgooham (집구함)

자취방 구할 때 쓰는 통합 부동산 검색 도구

직방·네이버 부동산·당근·다방 매물을 한 곳에서 조회하고, V-World 데이터로 건물 정보와 중개소를 검증합니다.

## 주요 기능

- **멀티 플랫폼 통합** — 직방·네이버·당근·다방 동시 검색, 중복 매물 자동 제거
- **AI 스코어링** — 역 거리·가격·건물 연식·중개소 신뢰도 기반 매물 순위
- **V-World 건물 검증** — 준공연도·건물구조·용도지역 자동 조회
- **중개소 신뢰도 검증** — V-World 기반 공인중개사/보조원 구분, 개업일 확인
- **청년버팀목 대출 계산기** — 자격 조건 확인 및 대출 한도 계산
- **지도 시각화** — Folium 기반 매물/중개소 지도

## 설치

```bash
# 의존성 설치
uv sync

# Playwright 브라우저 설치
uv run playwright install chromium

# 환경변수 설정
cp .env.example .env
# .env 파일에 API 키 입력
```

## 실행

```bash
uv run streamlit run jibgooham/app.py
```

## 기술 스택

- **UI** — Streamlit + streamlit-folium
- **크롤링** — httpx (직방·네이버), Playwright (당근·다방)
- **데이터** — Pydantic v2, SQLite 캐시
- **외부 API** — V-World (건물·중개소), 카카오 로컬 (좌표 변환)

## 라이선스

MIT
