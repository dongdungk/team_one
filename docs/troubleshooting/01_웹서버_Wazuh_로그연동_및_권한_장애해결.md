# 🛠️ [문제해결] DMZ 웹서버 Wazuh 로그 수집 누락 및 권한 장애 해결 보고서

**작성 일자:** 2026-10-26  
**대상 시스템:** DMZ 웹서버 (`192.168.20.10`, 외부 포트포워딩: `192.168.0.141:2222`)  
**연계 관제:** Wazuh 중앙 서버 (`192.168.10.30`, 외부 포트포워딩: `192.168.0.141:8822`)

---

## 1. 개요 및 증상

웹서버의 Wazuh Agent(`004`, `web-server`)가 Wazuh 중앙 서버(`192.168.10.30:1514`)와 통신은 정상 연결되어 있었으나, **실제 웹 공격 및 비즈니스 요청 로그가 중앙 관제 서버로 전혀 수집되지 않는 문제**가 발생함.

### 주요 증상
1. **쇼핑몰 API 비즈니스 로그(`app.log`) 부재:** 머신러닝의 핵심 학습 데이터인 JSON 비즈니스 로그 파일 자체가 생성되지 않음.
2. **Apache 웹 접근 로그 누락:** 공격 도구(PentAGI, curl 등)로 웹서버에 요청을 보내도 Wazuh Discover 및 `archives.json`에 웹 접근 기록이 기록되지 않음.
3. **불필요한 OS 시스템 잡음 폭증:** 에이전트에서 `journald`, `df -P`, `netstat`, `last -n 20`, `dpkg.log`가 지속 전송되어 보안 관제 알람창을 심각하게 오염시킴.

---

## 2. 근본 원인 분석 (Root Cause Analysis)

### 원인 ① : Docker 컨테이너의 권한 거부로 인한 `app.log` 기록 실패
- **구조:** 웹서버 쇼핑몰 애플리케이션은 Docker Compose(`compose.web.yml`)를 통해 구동 중이며, 호스트의 `./logs` 디렉터리가 컨테이너 내부 `/var/www/html/logs`로 마운트되어 있음.
- **원인:** 호스트의 `/home/ubuntu/sesac_shop_web_php/logs` 디렉터리가 `ubuntu:ubuntu` (755) 권한으로 생성되어 있었음. 컨테이너 내부의 Apache/PHP 프로세스(`www-data`, UID 33)가 쓰기 권한이 없어 파일 생성에 실패함.
- **에러 로그 확인:** `/home/ubuntu/sesac_shop_web_php/logs/apache/shop_error.log`에서 확인됨.
  ```text
  [php7:notice] [shop-api] 로그 파일 쓰기 실패: /var/www/html/public/api/v1/../../../logs/app.log
  ```

### 원인 ② : 컨테이너 볼륨 마운트로 인한 로그 경로 불일치
- **원인:** 기존 Wazuh 설정(`agent.conf`)은 웹서버가 네이티브로 동작한다고 가정하고 `/var/log/apache2/access.log` 및 `/var/log/apache2/error.log`를 모니터링하도록 지정되어 있었음.
- **실제 환경:** Apache가 Docker 컨테이너 안에서 동작하며, 호스트 디렉터리 `./logs/apache`를 컨테이너의 `/var/log/apache2`에 마운트하여 사용함.
- **실제 파일 위치:**
  - 호스트 상의 실제 경로: `/home/ubuntu/sesac_shop_web_php/logs/apache/shop_access.log`
  - 호스트 상의 에러 경로: `/home/ubuntu/sesac_shop_web_php/logs/apache/shop_error.log`
  - 에이전트는 호스트 OS에서 동작하므로 호스트의 실측 경로를 바라봐야 했음.

### 원인 ③ : 에이전트 로컬 기본 설정(`ossec.conf`)의 잡음 수집 잔존
- **원인:** 웹서버의 `/var/ossec/etc/ossec.conf`에 기본 설치 시 포함된 시스템 진단 명령(`df -P`, `netstat`, `last -n 20`)과 OS 로그(`journald`, `dpkg.log`) 수집 설정이 남아있어 주기적으로 불필요한 이벤트를 매니저로 발송하고 있었음.

---

## 3. 해결 조치 내역

### 조치 ① : 로그 디렉터리 및 파일 쓰기 권한 부여
컨테이너 내부의 PHP 데몬이 호스트의 `logs` 디렉터리에 파일을 자유롭게 쓸 수 있도록 권한을 조정함.
```bash
# 웹서버 VM 내부 (ubuntu@192.168.0.141:2222)
sudo chmod 777 /home/ubuntu/sesac_shop_web_php/logs
sudo touch /home/ubuntu/sesac_shop_web_php/logs/app.log
sudo chmod 666 /home/ubuntu/sesac_shop_web_php/logs/app.log
```
- **결과:** 즉시 API 요청 시 실시간 JSON 비즈니스 로그가 `app.log`에 정상 기록됨.

---

### 조치 ② : Wazuh 에이전트 수집 경로 최적화 및 잡음 제거
웹서버의 로컬 `/var/ossec/etc/ossec.conf` 및 중앙 Wazuh 서버의 `/var/ossec/etc/shared/default/agent.conf`를 실측 경로에 맞춰 일치시키고, 모든 잡음 설정을 제거함.

#### 최종 적용된 핵심 6대 로그 수집 명세:
```xml
  <!-- 1. Web Application Access Log (Apache mounted from Docker) -->
  <localfile>
    <log_format>apache</log_format>
    <location>/home/ubuntu/sesac_shop_web_php/logs/apache/shop_access.log</location>
  </localfile>

  <!-- 2. Web Application Error Log -->
  <localfile>
    <log_format>apache</log_format>
    <location>/home/ubuntu/sesac_shop_web_php/logs/apache/shop_error.log</location>
  </localfile>

  <!-- 3. Web Application API JSON Audit Log -->
  <localfile>
    <log_format>json</log_format>
    <location>/home/ubuntu/sesac_shop_web_php/logs/app.log</location>
  </localfile>

  <!-- 4. Docker Container Stdout/Stderr Raw JSON Logs -->
  <localfile>
    <log_format>json</log_format>
    <location>/var/lib/docker/containers/*/*-json.log</location>
  </localfile>

  <!-- 5. Linux Auth / SSH Login Log -->
  <localfile>
    <log_format>syslog</log_format>
    <location>/var/log/auth.log</location>
  </localfile>

  <!-- 6. System Core Log -->
  <localfile>
    <log_format>syslog</log_format>
    <location>/var/log/syslog</location>
  </localfile>
```

#### 비활성화/제거된 항목:
- `journald`
- `active-responses.log` (로컬 수집 배제)
- `dpkg.log`
- `df -P`, `netstat`, `last -n 20` 커맨드 블록

---

### 조치 ③ : Wazuh Agent 데몬 재구동 및 로그 수집 확인
```bash
sudo systemctl restart wazuh-agent
```
`/var/ossec/logs/ossec.log` 확인 결과:
```text
wazuh-logcollector: INFO: (1950): Analyzing file: '/home/ubuntu/sesac_shop_web_php/logs/apache/shop_access.log'.
wazuh-logcollector: INFO: (1950): Analyzing file: '/home/ubuntu/sesac_shop_web_php/logs/apache/shop_error.log'.
wazuh-logcollector: INFO: (1950): Analyzing file: '/home/ubuntu/sesac_shop_web_php/logs/app.log'.
wazuh-logcollector: INFO: (1950): Analyzing file: '/var/log/auth.log'.
wazuh-logcollector: INFO: (1950): Analyzing file: '/var/log/syslog'.
wazuh-logcollector: INFO: (1950): Analyzing file: '/var/lib/docker/containers/.../...-json.log'.
```
타깃 6개 파일이 완벽하게 실시간 분석 대상으로 등록됨.

---

## 4. 최종 검증 결과 (Verification)

웹서버를 대상으로 테스트 인젝션 요청(`sqlmap/1.5`)을 발생시킨 후, **Wazuh 중앙 관제 서버(`192.168.10.30`)의 아카이브 로그 수신 상태를 점검**함.

### 검증 로그: `/var/ossec/logs/archives/archives.json`
```json
/* 1. Apache Access Log 수신 및 web-accesslog 디코더 자동 파싱 확인 */
{
  "timestamp": "2026-10-26T10:50:48.691+0000",
  "agent": {
    "id": "004",
    "name": "web-server",
    "ip": "192.168.20.10"
  },
  "full_log": "172.18.0.1 - - [26/Oct/2026:10:50:45 +0000] \"GET /api/v1/users/1?id=1%20OR%201=1 HTTP/1.1\" 200 332 \"-\" \"sqlmap/1.5\"",
  "decoder": { "name": "web-accesslog" },
  "data": {
    "protocol": "GET",
    "srcip": "172.18.0.1",
    "id": "200",
    "url": "/api/v1/users/1?id=1%20OR%201=1"
  },
  "location": "/home/ubuntu/sesac_shop_web_php/logs/apache/shop_access.log"
}

/* 2. 쇼핑몰 PHP API JSON 비즈니스 로그 수신 및 json 디코더 파싱 확인 */
{
  "timestamp": "2026-10-26T10:50:48.695+0000",
  "agent": {
    "id": "004",
    "name": "web-server",
    "ip": "192.168.20.10"
  },
  "decoder": { "name": "json" },
  "data": {
    "status": "200",
    "request_id": "at8whUAI4B_O7woXDLhrdgAAAAE",
    "client_ip": "172.18.0.1",
    "method": "GET",
    "path": "/api/v1/users/1?id=1%20OR%201=1",
    "duration_ms": "30.700000",
    "user_agent": "sqlmap/1.5"
  },
  "location": "/home/ubuntu/sesac_shop_web_php/logs/app.log"
}
```

### 결론
- 쇼핑몰 비즈니스 로직 로그(`app.log`)와 웹 서버 접근 로그(`shop_access.log`)가 모두 지연 없이 Wazuh 중앙 서버로 정상 수집되고 있으며, 내장 디코더(`web-accesslog`, `json`)를 통해 완벽히 필드 파싱됨을 검증 완료함.
- 머신러닝 학습 피처 추출을 위한 원천 로그 파이프라인이 100% 정상 작동 상태로 복구됨.
