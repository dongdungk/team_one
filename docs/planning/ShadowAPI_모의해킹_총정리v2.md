# 🛡️ 모의해킹 종합 진단 결과 보고서

> **진단 대상:** `http://192.168.0.141:8000` (가상 쇼핑몰 환경)
>
> **진단 방식:** ① PentAGI(AI 자동 스캔) → ② Kali Linux 수동 정밀 진단

## 1. 진단 요약 (Executive Summary)

* **v2 현역 API 보안성:** SQL Injection, 권한 상승, 가격 조작, 입력값 경계값 테스트 등 주요 웹 공격 기법을 **모두 견고하게 방어**하고 있음을 확인했습니다.

* **v1 레거시 API (Shadow API) 취약점:** 외부 문서(`openapi.yaml`) 및 프론트엔드 코드에서는 제거되었으나, 서버에 방치된 **`GET /api/v1/users/{id}` 엔드포인트를 통해 무인증 개인정보(PII) 대량 유출(IDOR/BOLA)이 가능**함을 직접 실증했습니다.

## 2. 공격 시나리오 (Attack Scenario)

본 시스템에 대한 공격 시나리오는 "현역 API의 강력한 보안을 우회하기 위해 방치된 구버전 API(Shadow API)를 타깃팅하는 공격"으로 요약됩니다.

```
[1단계: 정찰 및 자산 식별]
  │  - openapi.yaml 분석을 통해 v2 API 구조 파악
  │  - URL 패턴 분석을 통해 미기재된 v1 레거시 API 경로 역추적
  ▼
[2단계: Shadow API 우회 진입]
  │  - v2/users/me (인증 필요, JWT 토큰 없으면 401 Unauthorized)
  │  - v1/users/{id} (인증 검증 로직 누락 확인, 200 OK)
  ▼
[3단계: 권한 우회 및 PII 대량 추출 (IDOR/BOLA)]
  │  - Authorization 헤더 없이 요청
  │  - ID 파라미터(1~10000) 자동화 순차 열거(Enumeration)
  ▼
[4단계: 데이터 유출 완료]
  └─ 약 1만 명의 고객 이름, 이메일, 전화번호, 주소 등 개인정보(PII) 전량 유출

```

## 3. PentAGI (AI) vs 수동 진단 비교 분석

| 진단 항목 | PentAGI (AI 자동화 스캔) | 수동 정밀 진단 (Manual Pentest) | 차이점 및 수동 진단 의의 | 
| ----- | ----- | ----- | ----- | 
| **Shadow API 식별** | `/api/v1/users/{id}` 엔드포인트 존재 탐지 | `v0`\~`v4`, `beta`, `admin` 등 전 버전 스캔을 통해 **v1만 유일하게 생존함을 확증** | 단순 탐지를 넘어 서버 내 레거시 API의 정확한 분포 범위를 규명함 | 
| **피해 규모 측정** | ID 1\~50 수준의 샘플링 탐색 (`extracted_pii.json`) | ID 9999 등 경계값 탐색으로 **전체 고객(약 1만 명)의 PII 유출 가능성 입증** | 단편적 취약점 입증을 넘어 실제 사업적/법적 파급력(피해 규모)을 명확히 산출함 | 
| **v2 API 보안 검증** | "방어됨(Defended)" 결과 요약 출력 | **가격 조작, 권한 주입, SQLi, 경계값** 등 유형별 능동적 공격을 직접 주입하여 검증 | AI가 제시한 "안전함" 판정에 대해 구체적인 공격 로그와 응답값으로 검증 근거 마련 | 
| **원인 분석 (Root Cause)** | openapi.yaml 스캔 기반의 단편적 탐지 | `app.js` 소스 분석을 통해 **프론트엔드는 v2만 호출하며 v1은 완전한 "유령 API"임을 규명** | 단순 취약점 탐지에 그치지 않고, 자산 관리 미흡(API9)이라는 근본 원인을 도출함 | 

## 4. 수동 진단 세부 내역 및 결과

### 1️⃣ 디렉터리 및 파일 퍼징 (Reconnaissance)

* **사용 코드:**

  ```
  ffuf -u http://192.168.0.141:8000/FUZZ -w /usr/share/wordlists/dirb/common.txt -e .php,.bak,.old,.zip,.tar.gz,.sql,.json,.yaml,.txt -mc 200
  
  ```

* **시도 목적:** 웹서버 내 숨겨진 파일, 디렉터리, 백업 파일(`.bak`, `.old`), 데이터베이스 덤프(`.sql`) 노출 여부 확인

* **결과 및 판단:** `login.php`, `me.php` 등 주요 프론트엔드 파일이 식별되었으며, 백업 파일 노출은 없어 기본 파일 관리는 **양호**합니다.

### 2️⃣ 프론트엔드 소스코드 및 로직 분석

* **사용 코드:**

  ```
  curl http://192.168.0.141:8000/assets/app.js
  
  ```

* **시도 목적:** 자바스크립트 소스를 분석하여 API 호출 구조, 토큰 저장 방식, 하드코딩된 Secret Key, XSS 방어 로직 점검

* **결과 및 판단:** JWT 토큰을 `localStorage`에 보관하며, `textContent` 사용으로 DOM XSS를 **방어**하고 있음을 확인했습니다. 또한 프론트엔드는 v2 API만 호출하고 있어 v1은 방치된 유령 API임을 파악했습니다.

### 3️⃣ 계정 생성 및 JWT 인증 토큰 발급 테스트

* **사용 코드:**

  ```
  # 계정 가입 및 로그인 후 토큰 획득
  curl -s -X POST http://192.168.0.141:8000/api/v2/signup -H "Content-Type: application/json" -d '{"name":"tester","email":"hack@test.com","password":"Test1234!"}'
  curl -s -X POST http://192.168.0.141:8000/api/v2/login -H "Content-Type: application/json" -d '{"email":"hack@test.com","password":"Test1234!"}'
  
  ```

* **시도 목적:** v2/v1 API 인증 검증 및 우회 테스트에 사용할 정상 사용자 인증 토큰(`Bearer Token`) 확보

* **결과 및 판단:** 발급된 `access_token`을 변수(`$TOKEN`)에 저장하여 이후 수동 공격 검증에 활용했습니다.

### 4️⃣ v2 현역 API 보안성 검증 (Mass Assignment / 권한 상승)

* **사용 코드:**

  ```
  # 가격 조작 및 관리자 권한 주입 시도
  curl -s -X POST http://192.168.0.141:8000/api/v2/orders -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" -d '{"items":[{"product_id":1,"quantity":1,"price":1}]}'; echo
  curl -s -X POST http://192.168.0.141:8000/api/v2/signup -H "Content-Type: application/json" -d '{"name":"adm","email":"adm2@test.com","password":"Test1234!","is_admin":true,"role":"admin","id":1}'; echo
  
  ```

* **시도 목적:** 클라이언트 검증을 우회하여 주문 가격 조작(`price: 1`) 및 회원가입 시 관리자 권한(`is_admin: true`) 주입 시도

* **결과 및 판단:** 가격 조작 시 서버 DB의 정가 기준으로 결제 금액이 산출(`total_price: 266900`)되었고, 관리자 속성은 무시되어 **모두 정상 방어**되었습니다.

### 5️⃣ 입력값 검증 및 SQL Injection 테스트

* **사용 코드:**

  ```
  # SQL Injection 및 비정상 수량 입력 테스트
  curl -i "http://192.168.0.141:8000/api/v2/products?category=book%27%20OR%20%271%27=%271"
  curl -s -X POST http://192.168.0.141:8000/api/v2/orders -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" -d '{"items":[{"product_id":1,"quantity":999999}]}'; echo
  
  ```

* **시도 목적:** 카테고리 파라미터에 SQL 구문 주입 시도 및 수량 파라미터 경계값 검증

* **결과 및 판단:** SQLi 시도 시 에러 없이 빈 배열(`[]`)이 반환되어 안전하게 방어되었으며, 수량 오버플로우 공격 시 `{"detail":"quantity는 1~99 사이여야 합니다"}` 예외 응답으로 정상 차단되었습니다.

### 6️⃣ Shadow API 탐색 및 IDOR (무인증 PII 유출) 실증 (★ 핵심 취약점)

* **사용 코드:**

  ```
  # 무인증 상태로 레거시 v1 API 호출
  curl -s http://192.168.0.141:8000/api/v1/users/1 | python3 -m json.tool
  curl -s http://192.168.0.141:8000/api/v1/users/10027
  
  ```

* **시도 목적:** 방치된 v1 API의 인증/권한 검증 누락 여부(OWASP API1, API9) 실증

* **결과 및 판단 (Critical):** `Authorization` 헤더가 없는 무인증 요청에도 HTTP 200 OK와 함께 사용자 1번의 개인정보가 반환되었습니다. ID 번호 조작을 통해 **약 1만 명 규모의 전체 고객 개인정보를 무인증으로 탈취할 수 있는 치명적 IDOR/BOLA 취약점**을 확증했습니다.

## 5. 종합 의견 및 조치 권고사항

| 구분 | 내용 | 
| ----- | ----- | 
| **종합 의견** | 현역 v2 API는 매우 견고하게 구현되어 있으나, 시스템 고도화 과정에서 미폐기된 **v1 Shadow API 한 개로 인해 전체 고객 개인정보가 노출되는 보안 사각지대**가 존재합니다. | 
| **권고 1** | `GET /api/v1/*` 레거시 엔드포인트를 운영 환경에서 **즉시 삭제 및 접근 차단**할 것. | 
| **권고 2** | 레거시 API 유지가 불가피할 경우 v2와 동일한 **JWT 인증 및 본인 권한 검증(BOLA 방어) 로직을 적용**할 것. | 
| **권고 3** | API 자산 관리(Inventory Management) 프로세스를 수립하여 문서에 없는 미인증 엔드포인트 발생을 주기적으로 모니터링할 것. | 
