"""샘플 데이터 시딩 스크립트.

사용:
    python board/seed.py

이미 게시글이 있으면 아무 것도 하지 않는다(멱등).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import db as board_db

DEMO_PASSWORD = "1234"

SAMPLE_POSTS: list[dict[str, object]] = [
    {
        "board": "family",
        "category": "공지",
        "title": "가족 게시판을 열었습니다",
        "author": "운영자",
        "content": (
            "우리 가족 사진과 근황을 나누는 공간입니다.\n\n"
            "- 사진 이야기, 나들이 후기 무엇이든 환영합니다\n"
            "- 글 비밀번호는 수정·삭제에만 사용됩니다\n"
            "- 서로 예쁜 말로 남겨 주세요"
        ),
        "password": DEMO_PASSWORD,
        "is_pinned": True,
    },
    {
        "board": "family",
        "category": "자유",
        "title": "가을 나들이 사진 올려요",
        "author": "민지",
        "content": "주말에 다녀온 수목원 사진입니다. 단풍이 벌써 예뻐졌어요.",
        "password": DEMO_PASSWORD,
    },
    {
        "board": "family",
        "category": "자유",
        "title": "할머니 생신상 준비 후기",
        "author": "수민",
        "content": "아버지가 미역국을 끓이고 저는 잡채를 만들었습니다. 다들 좋아하셨어요.",
        "password": DEMO_PASSWORD,
    },
    {
        "board": "tips",
        "category": "정보",
        "title": "무료 배포 시 데이터가 사라지는 이유",
        "author": "지훈",
        "content": (
            "Streamlit Community Cloud 같은 무료 호스팅은 컨테이너 파일 시스템이 "
            "휘발성입니다. SQLite 파일에 글을 쌓아도 재시작하면 초기화될 수 있습니다.\n\n"
            "해결책은 두 가지입니다.\n\n"
            "1. 관리자 화면에서 DB 백업을 주기적으로 내려받는다\n"
            "2. Neon 같은 무료 Postgres로 이전한다"
        ),
        "password": DEMO_PASSWORD,
        "is_pinned": True,
    },
    {
        "board": "tips",
        "category": "정보",
        "title": "마크다운으로 글을 예쁘게 쓰는 팁",
        "author": "지훈",
        "content": (
            "본문은 마크다운을 지원합니다.\n\n"
            "```\n## 소제목\n- 목록\n**굵게**\n```\n\n"
            "위처럼 쓰면 소제목과 목록이 적용됩니다."
        ),
        "password": DEMO_PASSWORD,
    },
    {
        "board": "tips",
        "category": "질문",
        "title": "비밀번호를 잊어버리면 어떻게 하나요?",
        "author": "수민",
        "content": "글을 쓸 때 비밀번호를 입력했는데 기억이 안 납니다. 복구할 수 있나요?",
        "password": DEMO_PASSWORD,
    },
    {
        "board": "study",
        "category": "자유",
        "title": "이번 주 스터디 후기",
        "author": "민지",
        "content": (
            "오늘은 Streamlit으로 대시보드 만드는 법을 배웠습니다. "
            "`st.metric` 세 줄만으로 지표 화면이 완성되는 게 인상적이었어요."
        ),
        "password": DEMO_PASSWORD,
    },
    {
        "board": "study",
        "category": "정보",
        "title": "파이썬 리스트 컴프리헨션 정리",
        "author": "지훈",
        "content": (
            "for 문을 한 줄로 줄이는 문법입니다.\n\n"
            "```python\nsquares = [n * n for n in range(1, 6)]\n```\n\n"
            "조건을 붙일 때는 `if`를 뒤에 씁니다."
        ),
        "password": DEMO_PASSWORD,
    },
]

SAMPLE_COMMENTS: list[tuple[int, str, str]] = [
    (1, "지훈", "사진 잘 봤습니다. 다음엔 단체샷도 부탁해요!"),
    (2, "수민", "배경이 정말 예쁘네요."),
    (6, "운영자", "비밀번호는 해시로만 저장되어 복구가 불가능합니다. 관리자에게 삭제를 요청해 주세요."),
    (7, "수민", "저도 들었는데 st.metric 편하더라고요."),
    (8, "민지", "정리 감사합니다. 다음엔 딕셔너리 컴프리헨션도 부탁드려요."),
]


def seed(db_path: str | Path | None = None) -> None:
    board_db.init_db(db_path)

    _, existing = board_db.list_posts(page=1, page_size=1, db_path=db_path)
    if existing:
        print(f"이미 게시글 {existing}건이 있어 시딩을 건너뜁니다.")
        return

    created_ids: list[int] = []
    for post in SAMPLE_POSTS:
        post_id = board_db.create_post(
            board=str(post["board"]),
            category=str(post["category"]),
            title=str(post["title"]),
            author=str(post["author"]),
            content=str(post["content"]),
            password=str(post["password"]),
            is_pinned=bool(post.get("is_pinned", False)),
            db_path=db_path,
        )
        created_ids.append(post_id)

    for index, author, content in SAMPLE_COMMENTS:
        board_db.add_comment(
            created_ids[index - 1],
            author=author,
            content=content,
            password=DEMO_PASSWORD,
            db_path=db_path,
        )

    summary = board_db.stats(db_path)
    print(
        f"게시글 {summary['total_posts']}건, 댓글 {summary['total_comments']}건을 생성했습니다."
    )
    print(f"DB 경로: {board_db.resolve_db_path(db_path)}")
    print(f"샘플 글 비밀번호: {DEMO_PASSWORD} / 관리자 기본 비밀번호: admin123")


if __name__ == "__main__":
    seed()
