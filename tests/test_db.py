"""board/db.py 의 데이터 접근 계층 단위 테스트.

실행:
    python -m pytest board/tests -q
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db as board_db


@pytest.fixture()
def db_file(tmp_path: Path) -> Path:
    path = tmp_path / "test_board.db"
    board_db.init_db(path)
    return path


def _create(board_db_path: Path, **overrides: object) -> int:
    payload: dict[str, object] = {
        "category": "자유",
        "title": "테스트 제목",
        "author": "테스터",
        "content": "테스트 내용입니다.",
        "password": "1234",
    }
    payload.update(overrides)
    return board_db.create_post(db_path=board_db_path, **payload)  # type: ignore[arg-type]


# --- 비밀번호 -------------------------------------------------------------


def test_hash_is_salted_and_verifiable() -> None:
    first = board_db.hash_password("1234")
    second = board_db.hash_password("1234")

    assert first != second, "같은 비밀번호라도 salt 가 달라 해시가 달라야 한다"
    assert first.startswith("pbkdf2_sha256$200000$")
    assert "1234" not in first
    assert board_db.verify_password("1234", first)
    assert not board_db.verify_password("12345", first)
    assert not board_db.verify_password("1234", "garbage")


# --- 생성 / 조회 ----------------------------------------------------------


def test_create_and_get_post(db_file: Path) -> None:
    post_id = _create(db_file)
    post = board_db.get_post(post_id, db_path=db_file)

    assert post is not None
    assert post["title"] == "테스트 제목"
    assert post["views"] == 0
    assert post["comment_count"] == 0
    assert board_db.get_post(9999, db_path=db_file) is None


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"title": "가"}, "제목"),
        ({"title": "가" * 101}, "제목"),
        ({"author": ""}, "작성자"),
        ({"content": ""}, "내용"),
        ({"password": "12"}, "비밀번호"),
        ({"category": "없는분류"}, "카테고리"),
    ],
)
def test_create_post_validates_input(
    db_file: Path, overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError) as excinfo:
        _create(db_file, **overrides)
    assert message in str(excinfo.value)


def test_validation_does_not_persist_rows(db_file: Path) -> None:
    with pytest.raises(ValueError):
        _create(db_file, title="가")
    _, total = board_db.list_posts(db_path=db_file)
    assert total == 0


# --- 목록 / 검색 / 정렬 / 페이지네이션 ------------------------------------


def test_list_search_and_category_filter(db_file: Path) -> None:
    _create(db_file, title="파이썬 스터디", category="정보")
    _create(db_file, title="자바 스터디", category="질문", content="자바 이야기")

    found, total = board_db.list_posts(query="파이썬", db_path=db_file)
    assert total == 1
    assert found[0]["title"] == "파이썬 스터디"

    _, total_by_author = board_db.list_posts(query="테스터", db_path=db_file)
    assert total_by_author == 2

    _, total_by_category = board_db.list_posts(category="질문", db_path=db_file)
    assert total_by_category == 1

    _, total_all = board_db.list_posts(category=board_db.ALL_CATEGORY, db_path=db_file)
    assert total_all == 2


def test_like_wildcards_are_escaped(db_file: Path) -> None:
    _create(db_file, title="100% 달성")
    _create(db_file, title="그냥 글")

    _, total = board_db.list_posts(query="%", db_path=db_file)
    assert total == 1, "% 는 와일드카드가 아니라 문자 그대로 검색되어야 한다"


def test_sort_by_views_and_comments(db_file: Path) -> None:
    first = _create(db_file, title="인기글")
    second = _create(db_file, title="댓글많은글")
    _create(db_file, title="평범한글")

    for _ in range(3):
        board_db.increment_views(first, db_path=db_file)
    board_db.add_comment(second, author="a", content="댓글", password="1234", db_path=db_file)

    by_views, _ = board_db.list_posts(sort=board_db.SORT_VIEWS, db_path=db_file)
    assert by_views[0]["title"] == "인기글"

    by_comments, _ = board_db.list_posts(sort=board_db.SORT_COMMENTS, db_path=db_file)
    assert by_comments[0]["title"] == "댓글많은글"


def test_pinned_posts_come_first(db_file: Path) -> None:
    _create(db_file, title="보통글")
    _create(db_file, title="고정글", is_pinned=True)

    posts, _ = board_db.list_posts(db_path=db_file)
    assert posts[0]["title"] == "고정글"


def test_pagination(db_file: Path) -> None:
    for index in range(7):
        _create(db_file, title=f"글 {index}")

    page_one, total = board_db.list_posts(page=1, page_size=5, db_path=db_file)
    page_two, _ = board_db.list_posts(page=2, page_size=5, db_path=db_file)

    assert total == 7
    assert len(page_one) == 5
    assert len(page_two) == 2
    assert {post["id"] for post in page_one}.isdisjoint(
        {post["id"] for post in page_two}
    )


# --- 게시판 ---------------------------------------------------------------


def test_board_filter_and_scoped_stats(db_file: Path) -> None:
    _create(db_file, board="family", title="가족 사진")
    _create(db_file, board="tips", title="정보 팁")

    family, total = board_db.list_posts(board="family", db_path=db_file)
    assert total == 1
    assert family[0]["board"] == "family"

    _, all_total = board_db.list_posts(db_path=db_file)
    assert all_total == 2

    scoped = board_db.stats("tips", db_path=db_file)
    assert scoped["total_posts"] == 1
    assert scoped["total_comments"] == 0

    overall = board_db.stats(db_path=db_file)
    assert overall["total_posts"] == 2


def test_invalid_board_is_rejected(db_file: Path) -> None:
    with pytest.raises(ValueError):
        _create(db_file, board="unknown")
    with pytest.raises(ValueError):
        board_db.list_posts(board="unknown", db_path=db_file)


def test_init_db_migrates_legacy_posts_table(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(legacy))
    conn.executescript(
        """
        CREATE TABLE posts (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            category      TEXT    NOT NULL DEFAULT '자유',
            title         TEXT    NOT NULL,
            author        TEXT    NOT NULL,
            content       TEXT    NOT NULL,
            password_hash TEXT    NOT NULL,
            views         INTEGER NOT NULL DEFAULT 0,
            is_pinned     INTEGER NOT NULL DEFAULT 0,
            created_at    TEXT    NOT NULL,
            updated_at    TEXT    NOT NULL
        );
        """
    )
    conn.execute(
        """
        INSERT INTO posts (title, author, content, password_hash, created_at, updated_at)
        VALUES ('옛날 글', '작성자', '내용', 'x', '2026-01-01T00:00:00+00:00',
                '2026-01-01T00:00:00+00:00')
        """
    )
    conn.commit()
    conn.close()

    board_db.init_db(legacy)

    posts, total = board_db.list_posts(board=board_db.DEFAULT_BOARD, db_path=legacy)
    assert total == 1
    assert posts[0]["title"] == "옛날 글"
    assert posts[0]["board"] == board_db.DEFAULT_BOARD


# --- 수정 / 삭제 ----------------------------------------------------------


def test_update_requires_correct_password(db_file: Path) -> None:
    post_id = _create(db_file)

    with pytest.raises(PermissionError):
        board_db.update_post(
            post_id,
            password="9999",
            title="바뀐 제목",
            content="바뀐 내용",
            category="정보",
            db_path=db_file,
        )

    board_db.update_post(
        post_id,
        password="1234",
        title="바뀐 제목",
        content="바뀐 내용",
        category="정보",
        db_path=db_file,
    )
    post = board_db.get_post(post_id, db_path=db_file)
    assert post["title"] == "바뀐 제목"
    assert post["category"] == "정보"
    assert post["updated_at"] >= post["created_at"]


def test_delete_requires_correct_password_and_cascades(db_file: Path) -> None:
    post_id = _create(db_file)
    board_db.add_comment(post_id, author="댓글러", content="댓글", password="1234", db_path=db_file)

    with pytest.raises(PermissionError):
        board_db.delete_post(post_id, password="0000", db_path=db_file)
    assert board_db.get_post(post_id, db_path=db_file) is not None

    board_db.delete_post(post_id, password="1234", db_path=db_file)
    assert board_db.get_post(post_id, db_path=db_file) is None
    assert board_db.list_comments(post_id, db_path=db_file) == []


def test_delete_missing_post_raises_not_found(db_file: Path) -> None:
    with pytest.raises(board_db.PostNotFoundError):
        board_db.delete_post(404, password="1234", db_path=db_file)
    with pytest.raises(board_db.PostNotFoundError):
        board_db.admin_delete_post(404, db_path=db_file)


# --- 댓글 -----------------------------------------------------------------


def test_comment_crud(db_file: Path) -> None:
    post_id = _create(db_file)
    comment_id = board_db.add_comment(
        post_id, author="댓글러", content="첫 댓글", password="1234", db_path=db_file
    )

    comments = board_db.list_comments(post_id, db_path=db_file)
    assert len(comments) == 1
    assert comments[0]["content"] == "첫 댓글"
    assert "password_hash" not in comments[0]

    with pytest.raises(PermissionError):
        board_db.delete_comment(comment_id, password="0000", db_path=db_file)

    board_db.delete_comment(comment_id, password="1234", db_path=db_file)
    assert board_db.list_comments(post_id, db_path=db_file) == []


def test_comment_on_missing_post_raises(db_file: Path) -> None:
    with pytest.raises(board_db.PostNotFoundError):
        board_db.add_comment(
            777, author="a", content="내용", password="1234", db_path=db_file
        )


def test_comment_validation(db_file: Path) -> None:
    post_id = _create(db_file)
    with pytest.raises(ValueError):
        board_db.add_comment(
            post_id, author="a", content="가" * 501, password="1234", db_path=db_file
        )


# --- 통계 / 관리자 --------------------------------------------------------


def test_stats_and_categories(db_file: Path) -> None:
    first = _create(db_file, category="공지")
    _create(db_file, category="정보")
    board_db.add_comment(first, author="a", content="댓글", password="1234", db_path=db_file)
    board_db.increment_views(first, db_path=db_file)

    summary = board_db.stats(db_path=db_file)
    assert summary["total_posts"] == 2
    assert summary["total_comments"] == 1
    assert summary["posts_today"] == 2
    assert summary["total_views"] == 1

    categories = dict(board_db.list_categories(db_path=db_file))
    assert categories == {"공지": 1, "정보": 1}


def test_admin_delete_and_pin(db_file: Path) -> None:
    post_id = _create(db_file)
    board_db.set_pinned(post_id, True, db_path=db_file)
    assert board_db.get_post(post_id, db_path=db_file)["is_pinned"] == 1

    board_db.admin_delete_post(post_id, db_path=db_file)
    assert board_db.get_post(post_id, db_path=db_file) is None


def test_admin_list_excludes_content(db_file: Path) -> None:
    _create(db_file)
    rows = board_db.all_posts_for_admin(db_path=db_file)
    assert len(rows) == 1
    assert "content" not in rows[0]
    assert rows[0]["comment_count"] == 0


def test_export_all_includes_posts_comments_and_images(db_file: Path) -> None:
    post_id = _create(db_file)
    board_db.add_comment(
        post_id, author="댓글러", content="백업 댓글", password="1234", db_path=db_file
    )
    board_db.add_post_images(post_id, [_image_meta("backup")], db_path=db_file)

    data = board_db.export_all(db_path=db_file)

    assert data["storage"] == "sqlite"
    assert len(data["posts"]) == 1
    assert data["posts"][0]["content"] == "테스트 내용입니다."
    assert "password_hash" in data["posts"][0]
    assert data["comments"][0]["content"] == "백업 댓글"
    assert data["post_images"][0]["stored_name"] == "backup.jpg"


# --- 사진 첨부 -------------------------------------------------------------


def _image_meta(token: str) -> dict[str, object]:
    return {
        "stored_name": f"{token}.jpg",
        "thumb_name": f"{token}_t.jpg",
        "mime": "image/jpeg",
        "width": 100,
        "height": 80,
        "byte_size": 1234,
    }


def test_post_images_roundtrip_and_order(db_file: Path) -> None:
    post_id = _create(db_file)
    board_db.add_post_images(
        post_id, [_image_meta("first"), _image_meta("second")], db_path=db_file
    )
    board_db.add_post_images(post_id, [_image_meta("third")], db_path=db_file)

    rows = board_db.list_post_images(post_id, db_path=db_file)

    assert [row["stored_name"] for row in rows] == [
        "first.jpg",
        "second.jpg",
        "third.jpg",
    ]
    assert [row["position"] for row in rows] == [0, 1, 2]


def test_delete_post_image_returns_metadata(db_file: Path) -> None:
    post_id = _create(db_file)
    board_db.add_post_images(post_id, [_image_meta("keep"), _image_meta("drop")], db_path=db_file)
    rows = board_db.list_post_images(post_id, db_path=db_file)

    removed = board_db.delete_post_image(
        int(rows[1]["id"]), post_id, db_path=db_file
    )

    assert removed is not None
    assert removed["stored_name"] == "drop.jpg"
    assert removed["thumb_name"] == "drop_t.jpg"
    assert board_db.delete_post_image(int(rows[1]["id"]), post_id, db_path=db_file) is None
    assert [row["stored_name"] for row in board_db.list_post_images(post_id, db_path=db_file)] == ["keep.jpg"]


def test_post_images_cascade_on_post_delete(db_file: Path) -> None:
    post_id = _create(db_file)
    board_db.add_post_images(post_id, [_image_meta("gone")], db_path=db_file)

    board_db.delete_post(post_id, password="1234", db_path=db_file)

    with sqlite3.connect(db_file) as conn:
        remaining = conn.execute("SELECT COUNT(*) FROM post_images").fetchone()[0]
    assert remaining == 0


def test_list_posts_exposes_thumbnail_and_image_count(db_file: Path) -> None:
    post_id = _create(db_file)
    board_db.add_post_images(post_id, [_image_meta("solo")], db_path=db_file)

    posts, _ = board_db.list_posts(board="family", db_path=db_file)
    entry = next(post for post in posts if post["id"] == post_id)

    assert entry["image_count"] == 1
    assert entry["thumb_name"] == "solo_t.jpg"


def test_init_db_adds_post_images_to_legacy_database(tmp_path: Path) -> None:
    path = tmp_path / "legacy_images.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE posts (
                id INTEGER PRIMARY KEY, board TEXT, category TEXT, title TEXT,
                author TEXT, content TEXT, password_hash TEXT, views INTEGER,
                is_pinned INTEGER, created_at TEXT, updated_at TEXT
            );
            CREATE TABLE comments (
                id INTEGER PRIMARY KEY, post_id INTEGER, author TEXT,
                content TEXT, password_hash TEXT, created_at TEXT
            );
            """
        )

    board_db.init_db(path)

    with sqlite3.connect(path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert "post_images" in tables
