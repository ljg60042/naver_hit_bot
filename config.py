"""
프로그램 전반에서 쓰는 설정/데이터 구조 정의.

- CafeTarget  : 작업 대상 게시글 한 건의 정보와 진행 상태
- FetchConfig : 게시글 조회(post_info.py)에 쓰는 API 주소와 타임아웃
- CafeConfig  : 작업 전체 설정 (대상 목록, 간격, 워커 수)
"""
from dataclasses import dataclass, field
from typing import List

@dataclass
class CafeTarget:
    """작업 대상 게시글 한 건. GUI 목록의 한 행에 대응한다."""
    url: str                  # 게시글 주소
    title: str = ""           # 게시글 제목 (조회로 채워짐)
    initial_views: str = "0"  # 조회수(작업전)
    views: str = "0"          # 조회수(작업후)
    target_count: int = 10    # 목표 횟수
    current_count: int = 0    # 현재까지 진행한 횟수

@dataclass
class FetchConfig:
    """게시글 제목/조회수 조회 설정. post_info.fetch_post_info에서 사용."""
    # 게시글 상세 JSON API. {clubid}=카페 숫자 ID, {articleid}=글 번호
    article_api_url: str = "https://article.cafe.naver.com/gw/v4/cafes/{clubid}/articles/{articleid}?useCafeId=true&requestFrom=A"
    # 구형 카페 글 주소. clubid를 모를 때 이 페이지에서 clubid를 찾아낸다
    cafe_article_url: str = "https://cafe.naver.com/{cafename}/{articleid}"
    # 요청 하나당 최대 대기 시간(초)
    timeout: float = 5

@dataclass
class CafeConfig:
    """작업 전체 설정. GUI에서 시작 버튼을 누를 때 만들어진다."""
    targets: List[CafeTarget] = field(default_factory=list)  # 작업 대상 목록
    min_sec: float = 5.0   # 대기 시간 최소값(초)
    max_sec: float = 12.0  # 대기 시간 최대값(초)
    worker_count: int = 2  # 동시에 방문을 처리할 워커(브라우저) 수. 같은 타겟은 항상 워커 1개만 붙음
