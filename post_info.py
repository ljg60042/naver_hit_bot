"""
네이버 카페 게시글의 제목과 조회수를 조회하는 모듈.

읽기 전용 요청만 보내며, 방문 봇(crawler.py)과는 독립적으로 동작한다.
GUI의 URL 추가/조회수 동기화, 크롤러의 목표 달성 후 확인에서 공용으로 쓴다.
"""
import re
from dataclasses import dataclass
import requests
from bs4 import BeautifulSoup
from typing import Optional

from config import FetchConfig

# 조회 요청에 고정으로 사용하는 브라우저 User-Agent
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


@dataclass
class PostInfo:
    """
    게시글 조회 결과.

    성공 시 title/views가 채워지고 error는 None.
    실패 시 error에 사유 문자열이 들어가고 views는 None.
    """
    title: str = ""                # 게시글 제목 (API의 subject)
    views: Optional[int] = None    # 조회수 (API의 readCount)
    error: Optional[str] = None    # 실패 사유. None이면 성공

    @property
    def ok(self) -> bool:
        """조회 성공 여부"""
        return self.error is None


def short_error(e: Exception) -> str:
    """
    예외 메세지 단순화.

    여러 줄짜리 예외 메시지(스택 정보 등)에서 첫 줄만 뽑아 로그에 쓰기 좋게 만든다.
    메시지가 비어 있으면 예외 클래스 이름을 돌려준다.
    """
    first_line = str(e).strip().splitlines()[0] if str(e).strip() else ""
    return first_line or type(e).__name__


def fetch_post_info(url: str, config: Optional[FetchConfig] = None) -> PostInfo:
    """
    네이버 API를 통해 게시글 제목 및 조회수를 프록시 없이 빠르게 조회합니다.

    처리 순서:
      1. URL에서 clubid(카페 숫자 ID)와 articleid(글 번호)를 뽑는다.
         - 신형 URL: cafe.naver.com/ca-fe/cafes/{clubid}/articles/{articleid} → 바로 추출
         - 구형 URL: cafe.naver.com/{cafename}/{articleid} → 페이지 HTML에서 clubid를 찾아야 함
      2. article API를 호출해 JSON에서 제목과 조회수를 읽는다.

    Args:
        url: 조회할 카페 게시글 주소
        config: API 주소/타임아웃 설정. 생략하면 FetchConfig 기본값 사용

    Returns:
        PostInfo. 실패해도 예외를 던지지 않고 error에 사유를 담아 돌려준다.
    """
    cfg = config or FetchConfig()
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*"
    }

    try:
        # 신형(group 1,2) 또는 구형(group 3,4) 카페 URL 패턴 매칭
        m = re.search(r"cafe\.naver\.com/(?:ca-fe/cafes/(\d+)/articles/(\d+)|([^/?#]+)/(\d+))", url)
        if not m:
            return PostInfo(error="URL 형식 오류")

        if m.group(1):
            # 신형 URL: clubid가 주소에 들어 있음
            clubid, articleid = m.group(1), m.group(2)
        else:
            # 구형 URL: 카페 이름만 있으므로 페이지를 받아서 clubid를 찾는다
            cafename, articleid = m.group(3), m.group(4)
            # 프록시 없이 직접 접속하여 clubid 파싱
            resp = requests.get(cfg.cafe_article_url.format(cafename=cafename, articleid=articleid), headers=headers, timeout=cfg.timeout)

            # 1차: HTML 전체에서 "clubid=숫자" 패턴 검색
            soup = BeautifulSoup(resp.text, 'html.parser')
            club_m = re.search(r"clubid=(\d+)", resp.text)
            if not club_m:
                # 2차: 본문을 감싸는 iframe(#cafe_main)의 src 속성에서 검색
                iframe = soup.find('iframe', id='cafe_main')
                if iframe and 'src' in iframe.attrs:
                    club_m = re.search(r"clubid=(\d+)", iframe['src'])

            if not club_m:
                return PostInfo(error="clubid 파싱 실패")
            clubid = club_m.group(1)

        # API 직접 호출 (proxies 옵션 제거)
        # 브라우저에서 글을 열었을 때처럼 원래 글 주소를 Referer로 함께 보낸다
        api_url = cfg.article_api_url.format(clubid=clubid, articleid=articleid)
        api_headers = dict(headers, Referer=url)
        r = requests.get(api_url, headers=api_headers, timeout=cfg.timeout)

        if r.status_code != 200:
            return PostInfo(error=f"HTTP {r.status_code}")

        # 응답 구조: {"result": {"article": {"subject": ..., "readCount": ...}}}
        # 삭제글/비공개글/등급 제한 글은 article이 비어 있다
        data = r.json()
        article = data.get("result", {}).get("article")
        if not article:
            return PostInfo(error="접근 불가 게시글")

        return PostInfo(
            title=(article.get("subject") or "").strip(),
            views=int(article.get("readCount", 0)),
        )

    except Exception as e:
        # 타임아웃, 연결 오류, JSON 파싱 오류 등을 모두 실패 결과로 변환
        return PostInfo(error=f"오류: {short_error(e)}")
