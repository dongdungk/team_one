# ShadowAPI 쇼핑몰 모의해킹 총정리 보고서

> **대상 시스템:** `http://192.168.0.141:8000` (보안 프로젝트 시연용 가상 쇼핑몰 — 모든 회원·상품 데이터는 가상)
> **진단 범위:** 해당 호스트 1대로 한정 (허가된 내부 랩 환경)
> **진단 방식:** ① PentAGI(AI 자동 펜테스트) → ② Kali Linux 수동 진단
> **작성일:** 2026-10-27

---

## 0. 요약 (Executive Summary)

| 구분 | 결과 |
|---|---|
| **핵심 취약점** | 구버전 Shadow API `GET /api/v1/users/{id}` 무인증 노출 |
| **취약점 유형** | IDOR / BOLA (OWASP API1) + 자산 관리 미흡 (OWASP API9) |
| **피해 규모** | 전체 고객 **약 1만 명**의 개인정보(PII) 무인증 유출 가능 |
| **심각도** | **Critical** (기밀성) |
| **v2 현역 API** | 모든 공격 방어 성공 (인증·검증 견고) |
| **근본 원인** | 코드는 안전하나, **구버전 API 미폐기(자산 관리 실패)** |

> **한 줄 결론:** "v2는 완벽하게 방어하지만, 문서에서만 사라지고 서버에 살아남은 v1 Shadow API 하나가 전체 고객 개인정보를 무너뜨린다."

---

## 1. 공격 시나리오 (가설)

버전이 v1 → v2로 올라가면서, 공식 API 문서(`openapi.yaml`)에는 v2만 기재되어 있다.
그러나 **구버전 v1이 서버에 그대로 남아 있다면**, v2가 갖춘 인증·권한·입력 검증 없이 데이터에 접근할 수 있다.

> **핵심 아이디어:** "v2가 인증으로 막아둔 정보를, 문서 밖에 방치된 v1 Shadow API로 우회하여 빼낸다."

이는 OWASP API Security Top 10의 **API9: Improper Inventory Management(부적절한 자산 관리)** 와
**API1: Broken Object Level Authorization(BOLA/IDOR)** 의 전형적 결합 사례다.

---

## 2. PentAGI (AI 자동 펜테스트) 수행 결과

### 2.1 진행 방식
- Ubuntu VM에 PentAGI(자율형 AI 펜테스트 플랫폼)를 Docker로 구축
- LLM 제공자로 Google Gemini 연동
- 자연어 지시("사이트 보안 취약점 분석")만으로 Kali 컨테이너 기반 자동 공격 수행

### 2.2 PentAGI가 찾아낸 것
| 항목 | 결과 |
|---|---|
| 포트/서버 식별 | 22(SSH), 80(HTTP), 3306(MySQL) / Debian + Apache 2.4.54 / MySQL 8.0.46 |
| API 구조 | 쇼핑몰 Shop API v2, `/docs/openapi.yaml` 노출 |
| **v1 Shadow API 발견** | `/api/v1/users/{id}` 무인증 접근 → **IDOR/BOLA** |
| 데이터 탈취 | ID 1~50 열거 → 50명 PII 추출 (`extracted_pii.json`) |
| v2 정밀 테스트 | SQLi / IDOR / JWT 우회 → 모두 **방어됨**으로 판정 |
| 기타 지적 | openapi 노출, 보안 헤더 누락, Apache 구버전 |

### 2.3 PentAGI의 한계
- 유출 규모를 **1~50명**으로만 추정 (실제 전체 범위 미확인)
- openapi.yaml(v2) 기준으로만 스캔 → **Shadow API의 설계 원리까지는 규명 못 함**
- "방어됨" 판정의 근거 과정이 요약적

---

## 3. 직접 수동 진단 (Kali Linux, AI 미사용)

PentAGI가 찾은 결과를 **직접 재현·검증**하고, AI가 놓친 범위·원리·방어까지 규명했다.

### 3.1 정찰 (Reconnaissance)

| 시도 | 명령 | 결과 |
|---|---|---|
| API 설계도 확보 | `curl .../docs/openapi.yaml` | v2 전체 엔드포인트·파라미터 파악 |
| v2 경로를 v1으로 치환 | `/api/v1/{products,orders,login,signup,users}` | **`users`만 200, 나머지 404** |
| 전 버전 스캔 | `v0,v2,v3,v4,beta,alpha,internal,admin,dev,test,legacy,old` | **v1만 생존 확인** |
| 루트 디렉터리 퍼징 | `ffuf -u .../FUZZ` | PHP 프론트엔드 발견(login/me/orders/product/products/signup.php) |
| 백업·설정 파일 퍼징 | `-e .bak .sql .old .zip .json .yaml` | 노출 없음 (방어 양호) |
| 프론트 소스 분석 | `curl .../assets/app.js` | **프론트는 v2만 호출, XSS 방어(textContent), 하드코딩 비밀 없음** |

> **정찰 결론:** Shadow API = `GET /api/v1/users/{id}` 하나로 확정. 프론트엔드는 v1을 전혀 쓰지 않음 → v1은 순수 "유령 엔드포인트".

### 3.2 v1 Shadow API 공격 (★핵심 취약점)

| 시도 | 명령 | 결과 | 판정 |
|---|---|---|---|
| 무인증 조회 | `curl .../api/v1/users/1` | 200 + 김수민 PII | ✅ **IDOR/BOLA** |
| ID 순차 조회 | `users/2`, `users/5` | 각각 다른 사용자 PII | ✅ 전체 열람 |
| v2 대조 | `v2/users/me`(401) vs `v1/users/1`(200) | 접근통제 완전 우회 | ✅ 확증 |
| 범위 탐색 | `users/9999` | 200 (김채원) → **약 1만 명** | ✅ Critical |
| SQL Injection | `users/1'` | `{"detail":"id는 숫자여야 합니다"}` 422 | ❌ 방어됨 |
| 경계값 | `users/0`, `users/-1` | 404 "존재하지 않는 사용자" | ❌ |
| 추가 데이터 주입 | `?include=orders`, `?fields=all`, `?include=password` | 전부 무시, 기본 5개 필드만 | ❌ |
| 연관 경로 | `users/1/orders`, `orders/me` | 404 | ❌ |

> **v1 결론:** 토큰 없이 ID만 바꿔 **전체 고객 약 1만 명**의 이름·이메일·전화·주소 유출 가능. 반환 필드는 v2와 동일하며, 차이는 오직 **"인증 유무"**. 추가 데이터 주입·연관 경로는 모두 차단되어 범위는 users 조회로 확정.

### 3.3 v2 현역 API 공격 (전방위 시도 → 전부 방어)

클라이언트(app.js) 검증을 무시하고 **API를 직접 호출**하여 서버 검증을 시험했다.

| 공격 유형 | 시도 | 결과 | 판정 |
|---|---|---|---|
| 가격 조작 (Mass Assignment) | 주문에 `"price":1` 주입 | `total_price:266900` (정상 계산) | ✅ 방어 |
| 수량 경계 | `quantity: 999999 / -5 / 0` | "quantity는 1~99 사이여야" | ✅ 방어 |
| ID 조작 | 가입 시 `"id":1` 주입 | 서버가 `id:10028` 자동 할당 | ✅ 방어 |
| 권한 상승 | 가입 시 `"is_admin":true,"role":"admin"` | me 응답에 해당 필드 없음 | ✅ 방어 |
| admin API 탐색 | `/api/v2/admin`, `/api/v2/users` | 404 "존재하지 않는 경로" | ✅ 없음 |
| SQL Injection | `category=book' OR '1'='1` | 빈 배열 `[]`, 에러 없음 | ✅ 방어 |
| JWT 변조 | `Authorization: Bearer fake.fake.fake` | 401 "유효하지 않은 토큰" | ✅ 방어 |

> **v2 결론:** 인증(JWT 서명검증), SQLi, 가격·수량·ID·권한 조작 등 OWASP Top 10 공격을 **모두 방어**함을 능동적 공격으로 입증. v2 애플리케이션 로직은 견고함.

---

## 4. PentAGI vs 수동 진단 비교

| 항목 | PentAGI (AI) | 직접 수동 (Kali) |
|---|---|---|
| v1 Shadow API 발견 | ✅ | ✅ (재현·검증) |
| IDOR 증명 | ✅ (1~50명) | ✅ + **전체 1만 명 규모 확인** |
| v2 방어 검증 | 요약적 판정 | **공격 유형별 직접 검증** |
| Shadow API 설계 원리 | 미규명 | **app.js 분석으로 "프론트 미사용 유령 API" 규명** |
| 음성 결과(방어 확인) | 간략 | **SQLi·권한상승 등 시도 과정·근거 기록** |
| 범위 한정 | openapi 기준 | **전 버전 스캔 + 파라미터 주입까지 확인** |

> **의의:** AI가 찾은 취약점을 수동으로 재현·검증하는 데 그치지 않고, **피해 규모·설계 원리·v2의 견고함**까지 직접 규명하여 AI의 한계를 보완했다.

---

## 5. 발견 취약점 정리

| # | 취약점 | 위치 | 심각도 | OWASP |
|---|---|---|---|---|
| 1 | 무인증 IDOR/BOLA (전체 PII 유출) | `GET /api/v1/users/{id}` | **Critical** | API1 |
| 2 | Shadow API (구버전 미폐기) | `/api/v1/*` | **Critical** | API9 |
| 3 | API 명세 외부 노출 | `/docs/openapi.yaml` | Medium | API9 |
| 4 | 보안 헤더 누락 (CSP/HSTS 등) | 전역 | Low | — |
| 5 | 웹 서버 구버전 | Apache 2.4.54 | Low | — |

---

## 6. 개선 권고사항

1. **v1 레거시 엔드포인트 즉시 폐기 또는 차단** — 외부 접근 불가 처리 (최우선)
2. **객체 수준 접근통제(BOLA 방어)** — 모든 데이터 요청에 요청자 권한 검증 필수
3. **API 자산 목록 관리** — 문서에 없는 비공식 엔드포인트는 운영 환경에서 제거
4. **Rate Limiting + 이상행위 모니터링** — 대량 열거(enumeration) 탐지·차단
5. **API 명세 접근 제한** — `/docs`, `openapi.yaml`은 내부/인증 사용자만
6. **보안 헤더 적용 및 서버 패치** — CSP, HSTS, X-Frame-Options 등 / Apache 최신화

---

## 7. 사용 도구 및 산출물

**도구:** Kali Linux, curl, ffuf, python3, (참고용) PentAGI + Gemini

**산출물:**
- `extracted_pii.json` — PentAGI 추출 (50명)
- `idor_dump.py` — 직접 작성 익스플로잇 (전체 열거)
- `full_pii.json` — 수동 추출 증거물 (약 1만 명, *마스킹 후 보고*)

> ⚠️ 모든 데이터는 가상이나, 발표/공유 자료에는 PII를 마스킹(예: 김*민, user1***@example.com)하여 사용할 것.

---

*본 진단은 허가된 내부 실습 환경에서 교육 목적으로 수행되었으며, 모든 대상 데이터는 가상 데이터임.*
