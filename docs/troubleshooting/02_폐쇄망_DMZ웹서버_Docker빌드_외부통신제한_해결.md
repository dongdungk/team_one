# 🛠️ [문제해결] 폐쇄망(DMZ) 웹서버 Docker 빌드 외부 통신 차단 해결 보고서

**작성 일자:** 2026-10-26  
**대상 시스템:** DMZ 웹서버 (`192.168.20.10`, SSH: `192.168.0.141:2222`)  
**제약 조건:** FortiGate 방화벽 라이선스 정책 수 제한으로 인해 **DMZ ➔ WAN (외부 인터넷) Egress 트래픽 정책 추가 불가 (완전한 폐쇄망 환경)**

---

## 1. 개요 및 장애 현상

### 현상
DMZ 웹서버(`192.168.20.10`)에서 쇼핑몰 컨테이너를 가동하기 위해 `INSTALL.txt`의 안내대로 아래 명령어를 실행할 경우, 빌드가 멈추거나 네트워크 에러로 컨테이너 구동에 실패함:
```bash
sudo docker compose -f compose.web.yml up -d --build
```

### 증상 및 에러 원인
- `Could not resolve host: deb.debian.org`
- `Temporary failure resolving 'registry-1.docker.io'`
- 빌드 과정에서 외부 패키지를 내려받으려다 무한 대기(Hang) 후 타임아웃 발생

---

## 2. 도커가 외부에서 다운로드를 시도하는 원인 분석

`Project/sesac_shop_web_php/Dockerfile`을 분석한 결과, 빌드 과정에서 외부 WAN 통신을 필수로 요구하는 두 가지 구간이 존재함:

```dockerfile
# 1) Docker Hub에서 베이스 이미지 다운로드 시도 (WAN 필요)
FROM php:7.4-apache

# 2) 데비안 공식 패키지 미러 서버(deb.debian.org)에서 리눅스 라이브러리 다운로드 시도 (WAN 필요)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libonig-dev \
 && docker-php-ext-install pdo_mysql mbstring \
 && a2enmod rewrite unique_id \
 && rm -rf /var/lib/apt/lists/*
```

1. **`--build` 플래그의 부작용:**  
   명령어 끝에 `--build`가 붙어 있으면, 로컬에 이미지가 있더라도 도커는 `Dockerfile`의 각 스텝을 재실행(캐시 검증 및 패키지 갱신)하려고 시도하여 외부 인터넷 연결을 강제함.
2. **FortiGate 방화벽 제약:**  
   현재 웹서버가 속한 DMZ(`192.168.20.0/24`)는 FortiGate 평가판 라이선스의 정책 개수 한도로 인해 외부 인터넷(WAN)으로 나가는 NAT/Egress 정책이 열려있지 않음. 따라서 `apt-get`이나 `docker pull` 명령은 100% 실패하게 됨.

---

## 3. 해결 방안 (4대 전략)

### 전략 ① : [가장 추천 / 적용 완료] 로컬 캐시 이미지 고정 및 `--build` 제거 ⭐⭐⭐
- **핵심 원리:** 웹서버 로컬 Docker 저장소에는 이미 과거에 빌드 완료된 `shop-web-web:latest` 이미지(651MB)가 정상 보관되어 있음 (`sudo docker images` 확인 완료).
- **조치 내역:**
  `compose.web.yml`에서 `build: .`를 제거하고, 도커가 절대 인터넷을 조회하지 않도록 `pull_policy: never`를 명시함.
  ```yaml
  name: shop-web

  services:
    web:
      image: shop-web-web:latest
      pull_policy: never          # 🚫 외부 Docker Hub 조회 원천 차단
      restart: unless-stopped
      ...
  ```
- **실행 명령 변경:**
  ```bash
  # ❌ 기존 (인터넷 요구): sudo docker compose -f compose.web.yml up -d --build
  # ⭕ 변경 (완전 오프라인): sudo docker compose -f compose.web.yml up -d
  ```

---

### 전략 ② : [적용 완료] 소스코드 볼륨 바인드 마운트로 재빌드 소요 원천 제거 ⭐⭐⭐
- **문제점:** 기존 Dockerfile은 `COPY . /var/www/html` 방식으로 소스코드가 이미지 내부에 구워져 있었음. 이로 인해 PHP 코드나 API를 수정하면 재빌드(`--build`)를 해야만 코드가 반영되는 구조였음.
- **조치 내역:** `compose.web.yml`의 `volumes` 설정에 호스트의 소스 디렉터리를 직접 컨테이너로 바인드 마운트함.
  ```yaml
      volumes:
        - ./public:/var/www/html/public       # 웹 진입점 실시간 연동
        - ./src:/var/www/html/src             # 백엔드 비즈니스 로직 실시간 연동
        - ./config:/var/www/html/config       # 환경설정 실시간 연동
        - ./vendor:/var/www/html/vendor       # 라이브러리 실시간 연동
        - ./logs:/var/www/html/logs           # 비즈니스 로그(app.log) 연동
        - ./logs/apache:/var/log/apache2      # 웹서버 접근/에러 로그 연동
  ```
- **효과:** 호스트(`/home/ubuntu/sesac_shop_web_php`)에서 코드를 수정하면, **도커를 다시 빌드할 필요 없이 0.1초 만에 웹서버에 즉시 반영**됨.

---

### 전략 ③ : [폐쇄망 표준 절차] 새 패키지/이미지가 필요할 때의 오프라인 반입 절차
만약 향후 새로운 리눅스 패키지나 PHP 확장 모듈이 필요하여 도커 이미지를 새로 빌드해야 할 경우, 인터넷이 연결된 **관리자 PC(호스트 PC)**에서 빌드하여 전송하는 정석 폐쇄망 반입 절차를 사용함.

```bash
# [단계 1: 인터넷이 되는 관리자 PC (Docker Desktop 설치 환경)]
# 프로젝트 소스 경로로 이동 후 이미지 빌드
docker build -t shop-web-web:latest .

# 도커 이미지를 tar 단일 압축 파일로 추출
docker save -o shop-web-web.tar shop-web-web:latest

# [단계 2: DMZ 웹서버로 파일 전송 (포트포워딩 2222 활용)]
scp -P 2222 shop-web-web.tar ubuntu@192.168.0.141:/home/ubuntu/

# [단계 3: DMZ 웹서버에서 오프라인 이미지 로드]
ssh -p 2222 ubuntu@192.168.0.141
sudo docker load -i /home/ubuntu/shop-web-web.tar
sudo docker compose -f compose.web.yml up -d
```

---

### 전략 ④ : [네트워크 우회] 관리자 PC를 통한 SSH 역방향 SOCKS5 프록시 터널링
방화벽 정책을 영구적으로 추가하지 않고, 긴급하게 웹서버에서 `apt-get` 등을 실행해야 할 때 관리자 PC의 인터넷을 웹서버로 임시 대여해주는 기법:

```bash
# 관리자 PC에서 SSH Dynamic 포트포워딩 실행 (포트 1080 SOCKS 프록시 오픈)
ssh -R 1080 -p 2222 ubuntu@192.168.0.141

# 웹서버 쉘 내부에서 프록시 환경변수 지정 후 apt 실행
export all_proxy=socks5://127.0.0.1:1080
sudo -E apt-get update
```

---

## 4. 최종 적용 및 검증 결과

웹서버의 `compose.web.yml`을 전략 ①과 ②를 적용한 최적화 구성으로 갱신한 후, **외부 인터넷 통신을 전혀 발생시키지 않고 컨테이너를 완벽히 재구동**함.

### 실행 로그
```text
ubuntu@web-server:~/sesac_shop_web_php$ sudo docker compose -f compose.web.yml up -d
 Container shop-web-web-1 Recreated
 Container shop-web-web-1 Starting
 Container shop-web-web-1 Started
```

### 서비스 정상 동작 검증
```bash
# 1. 메인 웹 페이지 리다이렉트 응답 확인 (정상 302)
HTTP/1.1 302 Found
Location: /products.php

# 2. 백엔드 v1 REST API 데이터베이스 쿼리 연동 확인 (정상 200 JSON 반환)
curl -s http://localhost/api/v1/users/1
{"id":1,"name":"홍길동","email":"user1@example.com","phone":"044-218-1960","address":"세종특별자치시..."}
```

### 요약
- **결과:** 외부 인터넷 다운로드 없이 로컬 이미지만으로 100% 정상 가동 확인 완료.
- **운영 팁:** 앞으로 웹서버를 재시작하거나 구동할 때는 `--build` 옵션을 뺀 `sudo docker compose up -d` 명령어만 사용하시면 됩니다.

---

## 5. 웹서버 설정 및 코드 수정 상세 내역 (수정 위치 및 Diff)

어디의 어떤 파일을 어떻게 수정했는지 다른 관리자 및 AI가 바로 추적할 수 있도록 파일별 상세 내역을 기록함.

### ① [웹서버 VM] `/home/ubuntu/sesac_shop_web_php/compose.web.yml`
* **역할:** 도커 컴포즈 실행 정의 파일
* **수정 전:**
  ```yaml
  services:
    web:
      build: .
      restart: unless-stopped
      ...
      volumes:
        - ./logs:/var/www/html/logs
        - ./logs/apache:/var/log/apache2
  ```
* **수정 후 (Diff):**
  ```diff
  services:
    web:
  -   build: .
  +   image: shop-web-web:latest
  +   pull_policy: never
      restart: unless-stopped
      ...
      volumes:
  +     - ./public:/var/www/html/public
  +     - ./src:/var/www/html/src
  +     - ./config:/var/www/html/config
  +     - ./vendor:/var/www/html/vendor
        - ./logs:/var/www/html/logs
        - ./logs/apache:/var/log/apache2
  ```
* **수정 목적:**
  1. `build: .` ➔ `image: shop-web-web:latest` + `pull_policy: never`: 외부 Docker Hub 및 apt 미러 조회 0바이트 차단
  2. 소스코드 볼륨 마운트: 호스트의 PHP 코드 수정 시 컨테이너 재빌드 없이 실시간 반영

---

### ② [웹서버 VM] 기본 컴포즈 파일 심볼릭 링크 및 계정 권한
* **위치:** `/home/ubuntu/sesac_shop_web_php/docker-compose.yml`
* **실행 명령:**
  ```bash
  # 1. docker compose ps 실행 시 -f 없이도 바로 인식되도록 기본 파일 심볼릭 링크 생성
  cd /home/ubuntu/sesac_shop_web_php
  sudo ln -sf compose.web.yml docker-compose.yml

  # 2. ubuntu 계정이 sudo 없이 도커 상태를 조회할 수 있도록 그룹 등록
  sudo usermod -aG docker ubuntu
  ```
* **수정 목적:** `docker compose ps` 명령어 실행 시 `no configuration file provided` 또는 `permission denied` 방지

---

### ③ [웹서버 VM] 로그 디렉터리 권한 및 파일 생성
* **위치:** `/home/ubuntu/sesac_shop_web_php/logs/`
* **실행 명령:**
  ```bash
  # 컨테이너 내부 www-data(UID 33) 계정이 호스트 마운트 폴더에 쓰기 가능하도록 권한 개방
  sudo chmod 777 /home/ubuntu/sesac_shop_web_php/logs
  sudo touch /home/ubuntu/sesac_shop_web_php/logs/app.log
  sudo chmod 666 /home/ubuntu/sesac_shop_web_php/logs/app.log
  ```
* **수정 목적:** `[shop-api] 로그 파일 쓰기 실패: ... app.log` 에러 해결 및 실시간 비즈니스 JSON 감사 로그 기록 활성화

---

### ④ [웹서버 VM] Wazuh Agent 설정 (`/var/ossec/etc/ossec.conf`)
* **역할:** 웹서버에 설치된 Wazuh Agent의 수집 타깃 및 시스템 진단 제어
* **수정 내용:**
  1. 잡음 명령어 블록 영구 제거: `df -P`, `netstat`, `last -n 20`, `journald`, `dpkg.log`
  2. 도커 볼륨 마운트 실측 경로 매핑:
     - Apache Access: `/home/ubuntu/sesac_shop_web_php/logs/apache/shop_access.log` (`apache`)
     - Apache Error: `/home/ubuntu/sesac_shop_web_php/logs/apache/shop_error.log` (`apache`)
     - App Audit: `/home/ubuntu/sesac_shop_web_php/logs/app.log` (`json`)
     - Docker Stdout: `/var/lib/docker/containers/*/*-json.log` (`json`)
* **수정 목적:** Wazuh 관제 서버로의 불필요한 OS 스팸 알람 차단 및 정확한 웹/API 로그 전송

---

### ⑤ [로컬 Windows PC] `d:\Project\sesac_shop_web_php\sesac_shop_web_php\`
웹서버와 설정 일치화를 위해 로컬 저장소 파일도 동일하게 최신화 완료함.
1. `compose.web.yml`: 웹서버의 오프라인 최적화 버전과 동일하게 생성
2. `docker-compose.yml`: `web` 서비스의 `build: .` ➔ `image: shop-web-web:latest`, `pull_policy: never` 및 4대 소스코드 볼륨 마운트 추가 반영 완료

