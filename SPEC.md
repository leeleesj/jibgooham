# jibgooham 기술 명세서

## 1. 프로젝트 개요

| 항목 | 내용 |
|------|------|
| 프로젝트명 | jibgooham (집구함) |
| 목적 | 직방·네이버·당근·다방 매물 통합 조회 + V-World 건물/중개소 검증 + 청년버팀목 대출 계산 |
| 사용 대상 | 개인 (자취방 구하는 1인) |
| 실행 환경 | 로컬 Streamlit 앱 |
| Python | 3.12+ |
| 패키지 관리 | uv |

---

## 2. 기술 스택

| 레이어 | 기술 | 용도 |
|--------|------|------|
| UI | Streamlit 1.40+ | 대시보드 |
| 지도 | streamlit-folium + Folium | 매물/중개소 지도 시각화 |
| HTTP 크롤링 | httpx[asyncio] | 직방·네이버 비공식 API |
| 브라우저 크롤링 | Playwright (async) | 당근·다방 JS 렌더링 |
| 데이터 검증 | Pydantic v2 | 모델 정규화 |
| 캐시 | SQLite (stdlib) | 매물 24h TTL 캐시 |
| 외부 API | V-World REST API | 건물 정보, 중개소 조회 |
| 좌표 변환 | 카카오 로컬 API | 지역명 → 위경도 |
| 로깅 | structlog | JSON 구조화 로그 |
| 환경변수 | python-dotenv | API 키 관리 |

---

## 3. 디렉토리 구조

```
jibgooham/
├── pyproject.toml
├── .env.example
├── .gitignore
├── README.md
├── SPEC.md
│
├── jibgooham/
│   ├── app.py                  # Streamlit 진입점
│   ├── config.py               # 환경변수, 상수
│   │
│   ├── models/
│   │   ├── listing.py          # UnifiedListing
│   │   ├── search_params.py    # SearchParams, ScoringWeights
│   │   └── broker.py           # BrokerInfo
│   │
│   ├── crawlers/
│   │   ├── base.py             # BaseCrawler ABC
│   │   ├── zigbang.py          # 직방 (httpx)
│   │   ├── naver.py            # 네이버 부동산 (httpx)
│   │   ├── daangn.py           # 당근 (Playwright)
│   │   └── dabang.py           # 다방 (httpx)
│   │
│   ├── aggregator/
│   │   ├── normalizer.py       # 플랫폼별 → UnifiedListing 변환
│   │   ├── deduplicator.py     # 중복 제거
│   │   └── scorer.py           # 스코어링 엔진
│   │
│   ├── storage/
│   │   └── cache.py            # SQLite 캐시 (get/set/TTL)
│   │
│   └── vworld/
│       ├── building.py         # 건물 정보 조회
│       └── broker.py           # 중개소 검증
│
└── tests/
    ├── unit/
    │   ├── test_normalizer.py
    │   ├── test_deduplicator.py
    │   └── test_scorer.py
    └── integration/
        └── test_crawlers.py
```

---

## 4. 데이터 모델

### 4.1 UnifiedListing

```python
class UnifiedListing(BaseModel):
    # 식별
    id: str                         # "{platform}_{platform_id}"
    platform: str                   # "zigbang" | "naver" | "daangn" | "dabang"
    platform_id: str
    also_on: list[str] = []         # 중복 통합된 플랫폼 목록

    # 거래
    deal_type: str                  # "월세" | "전세" | "매매"
    deposit: int                    # 보증금 (만원)
    monthly_rent: int | None        # 월세 (만원), 전세/매매는 None

    # 위치
    address: str
    latitude: float | None
    longitude: float | None
    station_name: str | None        # 가장 가까운 역
    station_distance_m: int | None  # 역까지 거리 (미터)

    # 매물 정보
    area_m2: float                  # 전용면적
    floor: int | None               # 층수 (-1 = 반지하)
    building_floor: int | None      # 건물 전체 층수
    room_type: str                  # "원룸" | "투룸" | "오피스텔" | "아파트" | "빌라"
    title: str
    description: str | None
    images: list[str] = []          # 이미지 URL 목록
    amenities: list[str] = []       # 옵션 (에어컨, 주차 등)
    url: str                        # 원본 플랫폼 URL
    listed_at: datetime | None

    # V-World 건물 정보 (조회 후 채워짐)
    built_year: int | None
    building_structure: str | None  # "철근콘크리트" | "철골조" | "벽돌조" 등
    land_use: str | None            # 용도지역

    # 중개소 정보 (조회 후 채워짐)
    broker: BrokerInfo | None

    # 스코어 (계산 후 채워짐)
    score: float | None = None
    score_breakdown: dict | None = None
```

### 4.2 SearchParams

```python
class ScoringWeights(BaseModel):
    station_distance: float = 1.5   # 역 거리 (가까울수록 높음)
    price: float = 1.5              # 가격 (쌀수록 높음)
    area: float = 1.0               # 면적 (넓을수록 높음)
    building_age: float = 1.0       # 건물 연식 (신축일수록 높음)
    broker_trust: float = 1.5       # 중개소 신뢰도
    image_count: float = 0.3        # 사진 많을수록

class SearchParams(BaseModel):
    region: str                     # "강남역" | "역삼동" 등
    deal_type: str = "월세"
    room_type: str = "원룸"
    deposit_min: int = 0
    deposit_max: int = 100_000
    rent_min: int = 0
    rent_max: int = 200
    area_min: float = 0
    area_max: float = 200
    platforms: list[str] = ["zigbang", "naver", "daangn", "dabang"]
    limit: int = 30
    weights: ScoringWeights = ScoringWeights()
```

### 4.3 BrokerInfo

```python
class BrokerInfo(BaseModel):
    name: str
    registration_no: str | None
    representative: str | None
    position: str                   # "공인중개사" | "중개보조원" | "대표" 등
    opened_at: date | None
    status: str                     # "정상영업" | "폐업" 등
    address: str | None

    @property
    def trust_level(self) -> str:
        # "high" | "medium" | "low" | "danger"
        if self.position == "중개보조원":
            return "danger"
        if self.opened_at and (date.today() - self.opened_at).days < 365:
            return "low"
        if self.opened_at and (date.today() - self.opened_at).days < 365 * 3:
            return "medium"
        return "high"
```

---

## 5. 크롤러 명세

### 공통 원칙
- 로그인 없이 접근 가능한 데이터만 수집
- 요청 간격 최소 0.5초 준수
- 429 응답 시 5분 대기 후 재시도
- 실패 시 해당 플랫폼 결과 제외 (전체 실패 아님)

### 5.1 직방 (httpx)

| 항목 | 내용 |
|------|------|
| 방식 | 비공식 JSON API 직접 호출 |
| 지역 검색 | `GET https://apis.zigbang.com/v2/items?...` |
| 매물 상세 | `GET https://apis.zigbang.com/v2/item/{id}` |
| 이미지 | 응답 내 `images` 필드 |
| Rate limit | 분당 60회 |

### 5.2 네이버 부동산 (httpx)

| 항목 | 내용 |
|------|------|
| 방식 | 비공식 JSON API 직접 호출 |
| 지역 검색 | `GET https://new.land.naver.com/api/articles?...` |
| 헤더 필요 | `Referer: https://new.land.naver.com` |
| Rate limit | 분당 30회 |

### 5.3 당근 (Playwright)

| 항목 | 내용 |
|------|------|
| 방식 | Headless Chromium → 네트워크 인터셉트 |
| 이유 | JS 렌더링 필요, 쿠키 세션 |
| Rate limit | 분당 20회 |

### 5.4 다방 (httpx)

| 항목 | 내용 |
|------|------|
| 방식 | 비공식 JSON API |
| 지역 검색 | `GET https://www.dabangapp.com/api/3/room/...` |
| Rate limit | 분당 40회 |

---

## 6. 집계 명세

### 6.1 정규화 (normalizer.py)
- 플랫폼별 필드명/단위 → `UnifiedListing` 변환
- 금액 단위 통일: 만원
- 층수 파싱: "반지하" → -1, "옥탑" → 999
- 거래 유형 통일: "보증금/월세" → deposit/monthly_rent 분리

### 6.2 중복 제거 (deduplicator.py)
중복 판별 기준 (AND 조건):
1. 위경도 반경 20m 이내
2. 전용면적 허용오차 5% 이내
3. 보증금 동일 + 월세 동일

중복 그룹 처리:
- 이미지 가장 많은 매물을 대표로 선택
- 나머지 플랫폼 URL을 `also_on`에 병합

### 6.3 스코어링 (scorer.py)
각 항목 0~100점 정규화 후 가중 평균:

```
score = (
  station_score * w.station_distance +
  price_score   * w.price +
  area_score    * w.area +
  age_score     * w.building_age +
  broker_score  * w.broker_trust +
  image_score   * w.image_count
) / sum(weights)
```

broker_score:
- `high` → 100점
- `medium` → 70점
- `low` → 40점
- `danger` → 0점

---

## 7. V-World API 명세

### 7.1 건물 정보 (building.py)

```
GET https://api.vworld.kr/req/data
  ?service=data
  &request=GetFeature
  &data=LT_C_GEBUILDG          # 일반건물 레이어
  &key={VWORLD_API_KEY}
  &geometry=false
  &attribute=true
  &filter=addr_cd='{address_code}'
```

응답에서 추출:
- `archGbCdNm` → 건물구조
- `useAprDayN` → 사용승인일 (준공연도)
- `bldNm` → 건물명

### 7.2 중개소 검증 (broker.py)

```
POST https://www.vworld.kr/dtld/broker/dtld_list_s001.do
  Body: { regNm: "중개소명", siDoCd: "11", siGunGuCd: "680" }
```

응답에서 추출:
- `regDt` → 등록일 (개업일)
- `brkrPosCd` → 직위 코드
- `brkrPosNm` → 직위명 (공인중개사/중개보조원)
- `useSttsCd` → 상태 (정상/폐업)

---

## 8. Streamlit UI 명세

### 탭 구성
1. **🔍 매물 검색** — 메인 기능
2. **🏢 중개소 검색** — V-World 중개소 단독 조회
3. **🏦 버팀목 대출** — 자격 확인 + 한도 계산

### 탭 1: 매물 검색

```
레이아웃:
├── 사이드바 (230px)
│   ├── 검색 조건 (지역, 거래, 방유형, 가격범위, 플랫폼)
│   ├── AI 스코어링 가중치 슬라이더
│   ├── [검색] 버튼
│   └── 채팅창 (조건 자연어 조정)
├── 지도 패널 (flex: 1)
│   └── Folium 지도 (매물 핀: 점수별 색상)
└── 매물 리스트 (340px)
    ├── 정렬 선택
    └── 매물 카드 목록
        ├── 사진 (메인 + 썸네일)
        ├── 가격/점수
        ├── 위치/옵션 칩
        ├── V-World 건물 정보
        ├── 중개소 신뢰도
        └── 플랫폼 링크 버튼
```

### 탭 2: 중개소 검색

```
레이아웃:
├── 사이드바
│   ├── 지역 입력
│   ├── 반경 선택
│   ├── 직위 필터 (공인중개사만 등)
│   └── 최소 개업 기간 필터
├── 지도 (중개소 마커)
└── 중개소 카드 목록
    ├── 이름/주소
    ├── V-World 검증 정보 (직위, 개업일, 상태)
    └── [카카오지도에서 보기] 버튼
```

### 탭 3: 버팀목 대출

```
레이아웃:
├── 입력 패널 (280px)
│   ├── 개인 정보 (나이, 연소득, 무주택, 혼인)
│   ├── 매물 조건 (지역, 보증금, 면적)
│   └── [자격 확인] 버튼
└── 결과 패널
    ├── 자격 조건 체크 카드
    ├── 대출 한도 계산 결과
    └── 조건 적합 매물 목록
```

---

## 9. 캐시 명세 (SQLite)

```sql
CREATE TABLE listing_cache (
    cache_key   TEXT PRIMARY KEY,   -- "{platform}_{region}_{deal_type}_{room_type}"
    data        TEXT NOT NULL,       -- JSON
    cached_at   INTEGER NOT NULL,    -- Unix timestamp
    expires_at  INTEGER NOT NULL     -- cached_at + 86400 (24h)
);

CREATE TABLE building_cache (
    address     TEXT PRIMARY KEY,
    data        TEXT NOT NULL,
    cached_at   INTEGER NOT NULL,
    expires_at  INTEGER NOT NULL     -- cached_at + 604800 (7일)
);

CREATE TABLE broker_cache (
    broker_name TEXT PRIMARY KEY,
    data        TEXT NOT NULL,
    cached_at   INTEGER NOT NULL,
    expires_at  INTEGER NOT NULL     -- cached_at + 604800 (7일)
);
```

---

## 10. 필요한 API 키

| API | 발급처 | 무료 여부 |
|-----|--------|-----------|
| V-World API | vworld.kr | 무료 |
| 카카오 로컬 API | developers.kakao.com | 무료 (월 300,000건) |

---

## 11. 구현 순서 (Phase)

### Phase 1 — 기반 (Day 1~3)
- [ ] `config.py` — 환경변수 로드
- [ ] `models/listing.py` — UnifiedListing
- [ ] `models/search_params.py` — SearchParams, ScoringWeights
- [ ] `models/broker.py` — BrokerInfo
- [ ] `storage/cache.py` — SQLite 캐시

### Phase 2 — 크롤러 (Day 4~7)
- [ ] `crawlers/base.py` — BaseCrawler ABC
- [ ] `crawlers/zigbang.py`
- [ ] `crawlers/naver.py`
- [ ] `crawlers/daangn.py`
- [ ] `crawlers/dabang.py`

### Phase 3 — 집계 (Day 8~10)
- [ ] `aggregator/normalizer.py`
- [ ] `aggregator/deduplicator.py`
- [ ] `aggregator/scorer.py`
- [ ] 단위 테스트

### Phase 4 — V-World (Day 11~12)
- [ ] `vworld/building.py`
- [ ] `vworld/broker.py`

### Phase 5 — Streamlit UI (Day 13~15)
- [ ] `app.py` 뼈대 (탭 구조)
- [ ] 매물 검색 탭
- [ ] 중개소 검색 탭
- [ ] 버팀목 대출 탭
