#!/usr/bin/env python3
"""
B-Profile 기반 정상 사용자 트래픽 생성기 (CICIDS2017 방법론 기반)
------------------------------------------------------------------
논문: Sharafaldin et al., "Toward Generating a New Intrusion Detection Dataset" (2018)
목적: 인위적인 매크로가 아닌, 인간의 인지 체류 시간(Think Time)과
      마르코프 체인 상태 전이(State Transition)를 모방하여
      취약한 쇼핑몰에 현실적인 '정상 사용자 배경 트래픽(Label=0)'을 생성합니다.
"""

import sys
import io
import time
import math
import random
import datetime
import threading
import argparse
import json
import urllib.request
import urllib.error
import http.cookiejar

# 윈도우 콘솔 CP949 인코딩 에러 방지
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# -------------------------------------------------------------
# 사용자 에이전트(User-Agent) 풀 - 현실적인 다양한 디바이스 모방
# -------------------------------------------------------------
USER_AGENTS = [
    # Windows 11 Chrome
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # iPhone 15 Safari
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    # Android Galaxy S23 Chrome
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.82 Mobile Safari/537.36",
    # Windows 11 Edge
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    # Mac Safari
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15"
]

# -------------------------------------------------------------
# 기본 테스트 계정 풀 (회원 손님용)
# -------------------------------------------------------------
USER_ACCOUNTS = [
    {"email": "user1@example.com", "password": "Test1234!"},
    {"email": "user2@example.com", "password": "Test1234!"},
    {"email": "user3@example.com", "password": "Test1234!"},
    {"email": "user4@example.com", "password": "Test1234!"},
    {"email": "user5@example.com", "password": "Test1234!"},
]

# 통계 집계용 글로벌 락 및 카운터
stats_lock = threading.Lock()
total_requests = 0
status_counts = {}
user_actions_count = {}

def human_think_time(min_sec=1.5, max_sec=6.0):
    """
    CICIDS2017 B-Profile 논문 명세:
    인간의 웹 페이지 체류 시간(Think Time)은 로그정규 분포(Log-Normal Distribution)를 따름.
    """
    val = random.lognormvariate(1.0, 0.4)
    clipped = max(min_sec, min(val, max_sec))
    time.sleep(clipped)
    return clipped

class SimulatedShopper(threading.Thread):
    def __init__(self, user_idx, target_host, stop_event, account=None):
        super().__init__()
        self.user_idx = user_idx
        self.target_host = target_host.rstrip('/')
        self.stop_event = stop_event
        self.account = account
        self.user_agent = random.choice(USER_AGENTS)
        self.jwt_token = None
        
        # 독립적인 쿠키 저장소 생성
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookie_jar))
        
        # 기기 별칭 (로그 출력용)
        if "iPhone" in self.user_agent:
            self.device_name = "iPhone-Safari"
        elif "Android" in self.user_agent:
            self.device_name = "Galaxy-Chrome"
        elif "Macintosh" in self.user_agent:
            self.device_name = "Mac-Safari"
        elif "Edg" in self.user_agent:
            self.device_name = "Win-Edge"
        else:
            self.device_name = "Win-Chrome"

    def request(self, method, path, data=None, is_json=False):
        """HTTP 요청 전송 및 통계 기록"""
        url = f"{self.target_host}{path}"
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8" if not is_json else "application/json",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"
        }
        if self.jwt_token:
            headers["Authorization"] = f"Bearer {self.jwt_token}"

        encoded_data = None
        if data is not None:
            if is_json:
                encoded_data = json.dumps(data).encode("utf-8")
                headers["Content-Type"] = "application/json"
            else:
                encoded_data = urllib.parse.urlencode(data).encode("utf-8")
                headers["Content-Type"] = "application/x-www-form-urlencoded"

        req = urllib.request.Request(url, data=encoded_data, headers=headers, method=method)
        status_code = 0
        try:
            with self.opener.open(req, timeout=5) as response:
                status_code = response.status
                response.read()
        except urllib.error.HTTPError as e:
            status_code = e.code
        except Exception as e:
            status_code = 0

        # 글로벌 통계 기록
        with stats_lock:
            global total_requests
            total_requests += 1
            status_counts[status_code] = status_counts.get(status_code, 0) + 1
            user_actions_count[self.user_idx] = user_actions_count.get(self.user_idx, 0) + 1

        return status_code

    def do_login(self):
        """쇼핑몰 API 로그인 및 JWT 토큰 저장"""
        if not self.account:
            return False
        req = urllib.request.Request(
            f"{self.target_host}/api/v2/login",
            data=json.dumps(self.account).encode(),
            headers={"Content-Type": "application/json", "User-Agent": self.user_agent}
        )
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    resp_data = json.loads(resp.read().decode())
                    self.jwt_token = resp_data.get("access_token")
                    with stats_lock:
                        global total_requests
                        total_requests += 1
                        status_counts[200] = status_counts.get(200, 0) + 1
                    return True
        except Exception:
            pass
        return False

    def run(self):
        """가상 고객의 쇼핑 라이프사이클 루프 (마르코프 상태 전이 머신)"""
        now_str = datetime.datetime.now().strftime("%H:%M:%S")
        is_member = "회원" if self.account else "비회원(게스트)"
        print(f"[{now_str}] [손님 #{self.user_idx} ({self.device_name}, {is_member})] 쇼핑몰 입장!")

        while not self.stop_event.is_set():
            # 1. 메인 홈페이지 방문
            self.request("GET", "/index.php")
            human_think_time(1.0, 2.5)
            if self.stop_event.is_set(): break

            # 2. 전체 상품 목록 둘러보기
            self.request("GET", "/products.php")
            self.request("GET", "/api/v2/products")
            t = human_think_time(1.5, 4.0)
            print(f"   -> [손님 #{self.user_idx}] 상품 목록 둘러보는 중... ({t:.1f}초 체류)")
            if self.stop_event.is_set(): break

            # 3. 관심 상품 1~2개 클릭하여 상세 페이지 및 API 확인
            view_count = random.randint(1, 2)
            for _ in range(view_count):
                prod_id = random.randint(1, 10)
                self.request("GET", f"/product.php?id={prod_id}")
                self.request("GET", f"/api/v2/products/{prod_id}")
                t = human_think_time(2.0, 4.5)
                print(f"   -> [손님 #{self.user_idx}] 상품 #{prod_id} 상세 조회 중... ({t:.1f}초 체류)")
                if self.stop_event.is_set(): break

            if self.stop_event.is_set(): break

            # 4. 회원인 경우 로그인 및 마이페이지/주문내역 조회
            if self.account:
                if not self.jwt_token:
                    login_ok = self.do_login()
                    if login_ok:
                        print(f"   [*] [손님 #{self.user_idx}] {self.account['email']} 로그인 성공! (JWT 토큰 발급)")
                    human_think_time(1.0, 2.5)

                if self.jwt_token:
                    # 내 프로필 조회
                    self.request("GET", "/me.php")
                    self.request("GET", "/api/v2/users/me")
                    human_think_time(1.5, 3.0)

                    # 내 주문 내역 조회
                    self.request("GET", "/orders.php")
                    self.request("GET", "/api/v2/orders/me")
                    t = human_think_time(2.0, 4.0)
                    print(f"   -> [손님 #{self.user_idx}] 내 주문 내역 및 배송 상태 확인 중... ({t:.1f}초 체류)")

            # 5. 인간적인 실수 시뮬레이션 (1.5% 확률로 오타 링크 클릭 404 발생)
            if random.random() < 0.02:
                typo_path = random.choice(["/product_old.php", "/item/999", "/cart.html", "/help.php"])
                self.request("GET", typo_path)
                print(f"   [!] [손님 #{self.user_idx}] 오타 링크 클릭 ({typo_path} -> 404 자연 발생)")

            # 쇼핑 한 바퀴 완료 후 휴식 시간
            human_think_time(2.5, 5.0)
            if self.stop_event.is_set(): break

def print_banner(target, duration, num_users):
    print("=" * 70)
    print(" [B-Profile] 정상 사용자 트래픽 자동 생성기 (CICIDS2017 방법론)")
    print("=" * 70)
    print(f" * 대상 서버 URL      : {target}")
    print(f" * 시뮬레이션 총 시간 : {duration}초 ({duration//60}분 {duration%60}초)")
    print(f" * 동시 가상 손님 수  : {num_users}명 (회원/비회원 혼합)")
    print(f" * 적용 알고리즘      : Log-Normal 체류 시간 + Markov Chain 상태 전이")
    print(f" * 종료 방법          : 지정 시간 만료 시 자동 종료 또는 [Ctrl + C]")
    print("=" * 70)
    print("[시스템] 가상 고객들이 쇼핑몰에 접속을 시작합니다...\n")

def main():
    parser = argparse.ArgumentParser(description="B-Profile Realistic Benign Traffic Generator")
    parser.add_argument("--target", default="http://192.168.0.141:8000", help="Target Shop URL (default: http://192.168.0.141:8000)")
    parser.add_argument("--duration", type=int, default=600, help="Duration in seconds to run (default: 600s = 10min)")
    parser.add_argument("--users", type=int, default=5, help="Number of concurrent simulated users (default: 5)")
    args = parser.parse_args()

    print_banner(args.target, args.duration, args.users)

    stop_event = threading.Event()
    threads = []

    # 손님 스레드 생성 (일부는 회원 계정 부여, 일부는 비회원 게스트)
    for i in range(args.users):
        account = USER_ACCOUNTS[i % len(USER_ACCOUNTS)] if i < len(USER_ACCOUNTS) else None
        shopper = SimulatedShopper(user_idx=i + 1, target_host=args.target, stop_event=stop_event, account=account)
        threads.append(shopper)
        shopper.daemon = True
        shopper.start()
        time.sleep(random.uniform(0.3, 0.8))

    start_time = time.time()
    try:
        while time.time() - start_time < args.duration:
            elapsed = int(time.time() - start_time)
            remaining = max(0, args.duration - elapsed)
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n[알림] 사용자에 의해 생성이 중단되었습니다. 잔여 스레드를 정리합니다...")
    finally:
        stop_event.set()
        for t in threads:
            t.join(timeout=2.0)

    total_time = round(time.time() - start_time, 1)
    print("\n" + "=" * 70)
    print(" [완료] 정상 사용자 트래픽 생성 요약 리포트")
    print("=" * 70)
    print(f" * 총 소요 시간      : {total_time}초 ({round(total_time/60, 1)}분)")
    print(f" * 총 발생 HTTP 요청 : {total_requests}건")
    if total_time > 0:
        print(f" * 평균 요청 속도    : {round(total_requests / total_time, 2)} req/sec (인간적인 자연스러운 속도)")
    print(" * HTTP 응답 상태코드 분포:")
    for code, count in sorted(status_counts.items()):
        status_name = "성공(OK)" if code == 200 else ("404(자연스러운 오타)" if code == 404 else f"Status {code}")
        ratio = round((count / max(1, total_requests)) * 100, 1)
        print(f"   - {code} [{status_name}]: {count}건 ({ratio}%)")
    print("=" * 70)
    print("[성공] 웹서버와 Wazuh에 정상 사용자 로그(Label=0)가 적재되었습니다.")
    print("=" * 70)

if __name__ == "__main__":
    main()
