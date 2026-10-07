import os
import time
import random
import requests
from typing import Callable, Optional, Dict, Any
from urllib.parse import quote

from dotenv import load_dotenv

from playwright.sync_api import sync_playwright
from config import CafeConfig, CafeTarget
from post_info import fetch_post_info, short_error

# ==============================================================================
# 1. 프록시 설정 (단일 게이트웨이 / 로테이팅 적용)
# ==============================================================================
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

PROXIES_LIST = [
    {
        "host": os.environ["PROXY_HOST"],
        "port": int(os.environ["PROXY_PORT"]),
        "user": os.environ["PROXY_USER"],
        "pass": os.environ["PROXY_PASS"]
    }
]

_proxy_cursor = 0

def get_next_proxy_info() -> dict:
    """프록시 정보를 순차적으로 꺼내옵니다."""
    global _proxy_cursor
    proxy_info = PROXIES_LIST[_proxy_cursor % len(PROXIES_LIST)]
    _proxy_cursor += 1
    return proxy_info

def build_requests_proxies(p: dict) -> Dict[str, str]:
    """requests용 프록시 Dict 생성"""
    user_q = quote(p['user'], safe='')
    pass_q = quote(p['pass'], safe='')
    proxy_url = f"http://{user_q}:{pass_q}@{p['host']}:{p['port']}"
    return {"http": proxy_url, "https": proxy_url}

def build_playwright_proxy_options(p: dict) -> dict:
    """Playwright 브라우저용 프록시 설정 생성"""
    return {
        "server": f"http://{p['host']}:{p['port']}",
        "username": p['user'],
        "password": p['pass']
    }

def get_current_proxy_ip(p: dict) -> str:
    """현재 연결된 로테이팅 프록시의 외부 IP를 확인합니다 (타임아웃 1.5초)."""
    req_proxies = build_requests_proxies(p)
    try:
        res = requests.get("https://ip.decodo.com/json", proxies=req_proxies, timeout=1.5)
        if res.status_code == 200:
            data = res.json()
            return data.get("ip") or data.get("query") or "IP 추출 실패"
        return f"HTTP {res.status_code}"
    except Exception:
        return "IP 확인 스킵"

# ==============================================================================

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
]

class NaverCafeViewAutomation:
    def __init__(
        self,
        config: Optional[CafeConfig] = None,
        log_callback: Optional[Callable[[str, str], None]] = None,
        count_callback: Optional[Callable[[int, int], None]] = None,
        target_complete_callback: Optional[Callable[[int, str], None]] = None
    ):
        self.config = config
        self.log_callback = log_callback
        self.count_callback = count_callback
        self.target_complete_callback = target_complete_callback
        self._is_running = False

    def log(self, message: str, level: str = "INFO"):
        if self.log_callback:
            self.log_callback(message, level)
        else:
            print(f"[{level}] {message}")

    def update_count(self, index: int, current_count: int):
        if self.count_callback:
            self.count_callback(index, current_count)

    def notify_target_complete(self, index: int, views: str):
        if self.target_complete_callback:
            self.target_complete_callback(index, views)

    def stop(self):
        self._is_running = False
        self.log("작업 중지 요청 수신.", "WARN")

    def _visit_target(self, idx: int, target: CafeTarget):
        """Playwright를 구동하여 1회 방문(조회수 올려주기)을 수행합니다."""
        proxy_info = get_next_proxy_info()
        pw_proxy = build_playwright_proxy_options(proxy_info)

        current_ip = get_current_proxy_ip(proxy_info)
        self.log(f"[{idx + 1}] 방문 시도 중... (할당된 외부 IP: {current_ip})")

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
                )

                context = browser.new_context(
                    proxy=pw_proxy,
                    user_agent=random.choice(USER_AGENTS),
                    viewport={"width": 1920, "height": 1080}
                )

                page = context.new_page()
                page.set_default_timeout(8000)

                # 1. 카페 접속
                page.goto(target.url, wait_until="domcontentloaded")

                # 2. cafe_main iframe 존재 여부 로딩 확인 (특정 클래스 검수 제거로 Timeout 방지)
                page.wait_for_selector("#cafe_main", timeout=5000)

                # 3. iframe 스크롤 및 안정화
                frame = page.frame(name="cafe_main")
                if frame:
                    try:
                        frame.evaluate("window.scrollBy(0, 300);")
                    except Exception:
                        pass

                # 4. 조회수 집계 핑(Ping) 전송을 위한 체류 (1.5 ~ 2.0초)
                stay_time = random.uniform(1.5, 2.0)
                time.sleep(stay_time)

                browser.close()

            # 정상 통과 시 카운트 반영
            target.current_count += 1
            self.update_count(idx, target.current_count)
            self.log(f"[{idx + 1}] 방문 완료 ({target.current_count}/{target.target_count})")

        except Exception as e:
            # 실패 시 카운트를 올리지 않고 재시도 유도
            self.log(f"[{idx + 1}] 방문 실패 (로딩 미완료/통신 오류): {short_error(e)}", "WARN")

    def start_loop(self):
        """단일 루프로 게시글 목록을 하나씩 순차 방문합니다."""
        if not self.config or not self.config.targets:
            return

        self._is_running = True
        self.log(f"단일 순차 자동화 작업을 시작합니다. (총 {len(self.config.targets)}개 타겟)")

        while self._is_running:
            active_targets = [
                (idx, t) for idx, t in enumerate(self.config.targets) 
                if t.current_count < t.target_count
            ]

            if not active_targets:
                break

            for idx, target in active_targets:
                if not self._is_running:
                    break

                self._visit_target(idx, target)

                if target.current_count >= target.target_count:
                    self.log(f"[{idx + 1}] 목표 달성! 최신 조회수 확인 중...", "SUCCESS")
                    info = fetch_post_info(target.url)
                    new_views = str(info.views) if info.ok else target.views
                    target.views = new_views
                    self.notify_target_complete(idx, new_views)
                else:
                    # 방문 간 대기 시간을 0.8초 ~ 1.2초로 고정
                    sleep_time = random.uniform(0.8, 1.2)
                    self.log(f"[{idx + 1}] 다음 방문까지 {sleep_time:.1f}초 대기...")
                    
                    end_time = time.time() + sleep_time
                    while time.time() < end_time and self._is_running:
                        time.sleep(0.1)

        if self._is_running:
            self.log("모든 타겟의 목표 작업이 완료되었습니다.", "SUCCESS")
        else:
            self.log("작업이 사용자에 의해 중지되었습니다.", "WARN")

        self._is_running = False