"""게시판 - SQLite/Postgres 데이터 접근 계층.

Streamlit에 의존하지 않는 순수 데이터 모듈이다. UI(app.py)에서 이 모듈을 호출한다.
모든 SQL은 파라미터 바인딩(?)을 사용하며, 비밀번호는 해시로만 저장한다.

Postgres(Neon 등) 사용: 환경변수 BOARD_DATABASE_URL 또는 DATABASE_URL,
또는 Streamlit secrets의 DATABASE_URL 이 설정되면 Postgres 모드로 동작한다.
BOARD_DB_PATH 가 설정되면 DATABASE_URL 이 있어도 해당 SQLite 파일을 사용한다.
아무 것도 없으면 data/board.db (SQLite)를 사용한다.

created_at/updated_at 은 UTC ISO 문자열로 저장하고, "오늘" 통계는 KST 기준이다.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def _resolve_database_url() -> str:
    url = os.environ.get("BOARD_DATABASE_URL", "").strip()
    if not url:
        url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        try:
            import streamlit as st

            url = str(st.secrets.get("DATABASE_URL", "")).strip()
        except Exception:
            pass
    return url


DATABASE_URL: str = _resolve_database_url()
USE_POSTGRES: bool = bool(DATABASE_URL)


def _using_postgres(db_path: str | Path | None = None) -> bool:
    """이번 호출이 실제로 Postgres 연결을 쓰는지 판단한다.

    ``BOARD_DB_PATH`` 가 설정되면 DATABASE_URL 이 있어도 SQLite 를 쓴다.
    (테스트·로컬 백업처럼 명시적으로 SQLite 파일을 지정하는 경우)
    """
    board_env = os.environ.get("BOARD_DB_PATH", "").strip()
    return (db_path is None) and (not board_env) and USE_POSTGRES


def is_postgres() -> bool:
    """기본 연결(인자 없음)이 Postgres 를 사용하는지 반환한다."""
    return _using_postgres(None)


# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

CATEGORIES: tuple[str, ...] = ("자유", "질문", "정보", "공지")
DEFAULT_CATEGORY: str = "자유"
ALL_CATEGORY: str = "전체"

BOARDS: dict[str, str] = {
    "family": "우리 가족 게시판",
    "tips": "알아두면 좋은 정보",
    "study": "공지사항",
}
DEFAULT_BOARD: str = "family"
BOARD_LABELS: tuple[str, ...] = tuple(BOARDS.values())

SORT_LATEST: str = "latest"
SORT_VIEWS: str = "views"
SORT_COMMENTS: str = "comments"
SORT_OPTIONS: dict[str, str] = {
    "최신순": SORT_LATEST,
    "조회순": SORT_VIEWS,
    "댓글순": SORT_COMMENTS,
}

MIN_TITLE: int = 2
MAX_TITLE: int = 100
MAX_AUTHOR: int = 20
MAX_CONTENT: int = 5000
MAX_COMMENT: int = 500
MIN_PASSWORD: int = 4

_HASH_ALGORITHM = "pbkdf2_sha256"
_HASH_ITERATIONS = 200_000
_SALT_BYTES = 16

DEFAULT_DB_PATH: Path = (
    Path(__file__).resolve().parent / "data" / "board.db"
)


class PostNotFoundError(LookupError):
    """요청한 게시글이 존재하지 않을 때 발생한다."""


# ---------------------------------------------------------------------------
# 연결 관리
# ---------------------------------------------------------------------------


def resolve_db_path(db_path: str | Path | None = None) -> Path:
    """사용할 SQLite 파일 경로를 결정한다.

    우선순위: 인자 > 환경변수 ``BOARD_DB_PATH`` > ``board/data/board.db``.
    """
    if db_path is not None:
        return Path(db_path)
    env_path = os.environ.get("BOARD_DB_PATH", "").strip()
    if env_path:
        return Path(env_path)
    return DEFAULT_DB_PATH


def _sql(sql: str) -> str:
    """Postgres 연결 래퍼에서 플레이스홀더를 변환하므로 여기서는 그대로 반환한다."""
    return sql


@contextmanager
def connect(db_path: str | Path | None = None) -> Iterator[Any]:
    """트랜잭션 단위 커넥션을 열고 정상 종료 시 커밋한다."""
    use_pg = _using_postgres(db_path)

    if use_pg:
        import psycopg2
        from psycopg2.extras import RealDictCursor

        raw = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

        class _PgConnection:
            def __init__(self, inner):
                self._inner = inner

            def execute(self, sql, params=None):
                cur = self._inner.cursor()
                if isinstance(sql, str):
                    sql = sql.replace("?", "%s")
                if params is None:
                    cur.execute(sql)
                else:
                    cur.execute(sql, params)
                return cur

            def executemany(self, sql, params_seq):
                cur = self._inner.cursor()
                if isinstance(sql, str):
                    sql = sql.replace("?", "%s")
                cur.executemany(sql, params_seq)
                return cur

            def commit(self):
                self._inner.commit()

            def rollback(self):
                self._inner.rollback()

            def close(self):
                self._inner.close()

        conn = _PgConnection(raw)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return

    path = resolve_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


SCHEMA_SQL: str = """
CREATE TABLE IF NOT EXISTS posts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    board         TEXT    NOT NULL DEFAULT 'family',
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

CREATE TABLE IF NOT EXISTS comments (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id       INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    author        TEXT    NOT NULL,
    content       TEXT    NOT NULL,
    password_hash TEXT    NOT NULL,
    created_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS post_images (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id     INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    stored_name TEXT    NOT NULL UNIQUE,
    thumb_name  TEXT    NOT NULL,
    mime        TEXT    NOT NULL,
    width       INTEGER NOT NULL,
    height      INTEGER NOT NULL,
    byte_size   INTEGER NOT NULL,
    position    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_posts_created_at ON posts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_posts_category   ON posts(category);
CREATE INDEX IF NOT EXISTS idx_comments_post_id ON comments(post_id);
CREATE INDEX IF NOT EXISTS idx_post_images_post ON post_images(post_id, position);
"""


SCHEMA_SQL_PG: str = """
CREATE TABLE IF NOT EXISTS posts (
    id            SERIAL PRIMARY KEY,
    board         TEXT    NOT NULL DEFAULT 'family',
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

CREATE TABLE IF NOT EXISTS comments (
    id            SERIAL PRIMARY KEY,
    post_id       INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    author        TEXT    NOT NULL,
    content       TEXT    NOT NULL,
    password_hash TEXT    NOT NULL,
    created_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS post_images (
    id          SERIAL PRIMARY KEY,
    post_id     INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    stored_name TEXT    NOT NULL UNIQUE,
    thumb_name  TEXT    NOT NULL,
    mime        TEXT    NOT NULL,
    width       INTEGER NOT NULL,
    height      INTEGER NOT NULL,
    byte_size   INTEGER NOT NULL,
    position    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_posts_created_at ON posts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_posts_category   ON posts(category);
CREATE INDEX IF NOT EXISTS idx_comments_post_id ON comments(post_id);
CREATE INDEX IF NOT EXISTS idx_post_images_post ON post_images(post_id, position);
"""


def init_db(db_path: str | Path | None = None) -> None:
    """스키마를 생성한다. 여러 번 호출해도 안전하다(멱등)."""
    use_pg = _using_postgres(db_path)
    with connect(db_path) as conn:
        if use_pg:
            conn.execute(SCHEMA_SQL_PG)
        else:
            conn.executescript(SCHEMA_SQL)
        _migrate_schema(conn, use_pg=use_pg)


def _migrate_schema(conn: Any, use_pg: bool = False) -> None:
    """기존 DB에 board 컬럼이 없으면 추가한다."""
    if use_pg:
        conn.execute(
            """
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='posts' AND column_name='board'
                ) THEN
                    ALTER TABLE posts ADD COLUMN board TEXT NOT NULL DEFAULT 'family';
                END IF;
            END $$;
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_posts_board ON posts(board, created_at DESC)"
        )
    else:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(posts)")}
        if "board" not in columns:
            conn.execute(
                "ALTER TABLE posts ADD COLUMN board TEXT NOT NULL DEFAULT 'family'"
            )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_posts_board ON posts(board, created_at DESC)"
        )


# ---------------------------------------------------------------------------
# 유틸리티
# ---------------------------------------------------------------------------


def now_iso() -> str:
    """현재 시각을 ISO-8601 UTC 문자열로 반환한다 (초 단위)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def hash_password(password: str) -> str:
    """비밀번호를 PBKDF2-HMAC-SHA256 으로 해싱한다.

    저장 형식: ``pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>``
    """
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _HASH_ITERATIONS
    )
    return (
        f"{_HASH_ALGORITHM}${_HASH_ITERATIONS}"
        f"${salt.hex()}${digest.hex()}"
    )


def verify_password(password: str, stored_hash: str) -> bool:
    """입력 비밀번호를 저장된 해시와 상수 시간 비교로 검증한다."""
    try:
        algorithm, iterations, salt_hex, digest_hex = stored_hash.split("$")
        if algorithm != _HASH_ALGORITHM:
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


def _validate_text(
    value: str,
    *,
    field: str,
    max_length: int,
    min_length: int = 1,
) -> str:
    cleaned = (value or "").strip()
    if len(cleaned) < min_length:
        raise ValueError(f"{field}은(는) {min_length}자 이상 입력해 주세요.")
    if len(cleaned) > max_length:
        raise ValueError(f"{field}은(는) {max_length}자 이하로 입력해 주세요.")
    return cleaned


def _validate_category(category: str) -> str:
    cleaned = (category or "").strip()
    if cleaned not in CATEGORIES:
        raise ValueError(
            f"카테고리는 {', '.join(CATEGORIES)} 중 하나여야 합니다."
        )
    return cleaned


def _validate_board(board: str) -> str:
    cleaned = (board or "").strip()
    if cleaned not in BOARDS:
        raise ValueError(
            f"게시판은 {', '.join(BOARDS.values())} 중 하나여야 합니다."
        )
    return cleaned


def board_label(board: str) -> str:
    """게시판 slug 를 보여줄 이름으로 바꾼다."""
    return BOARDS.get(board, BOARDS[DEFAULT_BOARD])


def _validate_password(password: str) -> str:
    if not isinstance(password, str) or len(password) < MIN_PASSWORD:
        raise ValueError(f"비밀번호는 {MIN_PASSWORD}자 이상이어야 합니다.")
    if len(password) > 128:
        raise ValueError("비밀번호는 128자 이하로 입력해 주세요.")
    return password


# ---------------------------------------------------------------------------
# 게시글 CRUD
# ---------------------------------------------------------------------------


def create_post(
    *,
    category: str,
    title: str,
    author: str,
    content: str,
    password: str,
    board: str = DEFAULT_BOARD,
    is_pinned: bool = False,
    db_path: str | Path | None = None,
) -> int:
    """게시글을 생성하고 새 id 를 반환한다."""
    board = _validate_board(board)
    category = _validate_category(category)
    title = _validate_text(title, field="제목", min_length=MIN_TITLE, max_length=MAX_TITLE)
    author = _validate_text(author, field="작성자", max_length=MAX_AUTHOR)
    content = _validate_text(content, field="내용", max_length=MAX_CONTENT)
    password = _validate_password(password)

    timestamp = now_iso()
    params = (
        board,
        category,
        title,
        author,
        content,
        hash_password(password),
        1 if is_pinned else 0,
        timestamp,
        timestamp,
    )
    sql = """
        INSERT INTO posts
            (board, category, title, author, content, password_hash,
             views, is_pinned, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
    """
    with connect(db_path) as conn:
        if _using_postgres(db_path):
            cursor = conn.execute(_sql(sql + " RETURNING id"), params)
            return int(cursor.fetchone()["id"])
        cursor = conn.execute(_sql(sql), params)
        return int(cursor.lastrowid)


def get_post(
    post_id: int, db_path: str | Path | None = None
) -> dict[str, Any] | None:
    """게시글 한 건을 조회한다. 없으면 ``None``."""
    with connect(db_path) as conn:
        row = conn.execute(
            _sql(
                """
                SELECT p.*,
                       (SELECT COUNT(*) FROM comments c WHERE c.post_id = p.id)
                           AS comment_count
                FROM posts p
                WHERE p.id = ?
                """
            ),
            (post_id,),
        ).fetchone()
    return dict(row) if row else None


def _build_list_query(
    query: str,
    category: str,
    board: str | None = None,
) -> tuple[str, list[Any]]:
    """검색 조건에 해당하는 WHERE 절과 바인딩 값을 만든다."""
    clauses: list[str] = []
    params: list[Any] = []

    if board is not None:
        clauses.append("p.board = ?")
        params.append(_validate_board(board))

    keyword = (query or "").strip()
    if keyword:
        escaped = (
            keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        pattern = f"%{escaped}%"
        clauses.append(
            "(p.title LIKE ? ESCAPE '\\' OR p.content LIKE ? ESCAPE '\\'"
            " OR p.author LIKE ? ESCAPE '\\')"
        )
        params.extend([pattern, pattern, pattern])

    if category and category != ALL_CATEGORY:
        clauses.append("p.category = ?")
        params.append(category)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


_ORDER_BY: dict[str, str] = {
    SORT_LATEST: "p.is_pinned DESC, p.created_at DESC, p.id DESC",
    SORT_VIEWS: "p.is_pinned DESC, p.views DESC, p.created_at DESC, p.id DESC",
    SORT_COMMENTS: (
        "p.is_pinned DESC, comment_count DESC, p.created_at DESC, p.id DESC"
    ),
}


def list_posts(
    query: str = "",
    category: str = ALL_CATEGORY,
    sort: str = SORT_LATEST,
    page: int = 1,
    page_size: int = 10,
    board: str | None = None,
    db_path: str | Path | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """게시글 목록과 전체 건수를 반환한다."""
    page = max(1, int(page))
    page_size = max(1, min(int(page_size), 100))
    order_by = _ORDER_BY.get(sort, _ORDER_BY[SORT_LATEST])
    where, params = _build_list_query(query, category, board)

    with connect(db_path) as conn:
        total_row = conn.execute(
            _sql(f"SELECT COUNT(*) AS cnt FROM posts p {where}"), params
        ).fetchone()
        total = int(total_row["cnt"]) if total_row else 0

        rows = conn.execute(
            _sql(
                f"""
                SELECT p.*,
                       (SELECT COUNT(*) FROM comments c WHERE c.post_id = p.id)
                           AS comment_count,
                       (SELECT COUNT(*) FROM post_images i WHERE i.post_id = p.id)
                           AS image_count,
                       (SELECT i.thumb_name FROM post_images i
                         WHERE i.post_id = p.id
                         ORDER BY i.position ASC, i.id ASC LIMIT 1)
                           AS thumb_name
                FROM posts p
                {where}
                ORDER BY {order_by}
                LIMIT ? OFFSET ?
                """
            ),
            [*params, page_size, (page - 1) * page_size],
        ).fetchall()

    return [dict(row) for row in rows], total


def update_post(
    post_id: int,
    *,
    password: str,
    title: str,
    content: str,
    category: str,
    db_path: str | Path | None = None,
) -> None:
    """비밀번호가 일치할 때만 게시글을 수정한다."""
    category = _validate_category(category)
    title = _validate_text(title, field="제목", min_length=MIN_TITLE, max_length=MAX_TITLE)
    content = _validate_text(content, field="내용", max_length=MAX_CONTENT)

    with connect(db_path) as conn:
        row = conn.execute(
            _sql("SELECT password_hash FROM posts WHERE id = ?"), (post_id,)
        ).fetchone()
        if row is None:
            raise PostNotFoundError("게시글을 찾을 수 없습니다.")
        if not verify_password(password, row["password_hash"]):
            raise PermissionError("비밀번호가 일치하지 않습니다.")

        conn.execute(
            _sql(
                """
                UPDATE posts
                   SET category = ?, title = ?, content = ?, updated_at = ?
                 WHERE id = ?
                """
            ),
            (category, title, content, now_iso(), post_id),
        )


def delete_post(
    post_id: int,
    *,
    password: str,
    db_path: str | Path | None = None,
) -> None:
    """비밀번호가 일치할 때만 게시글을 삭제한다(댓글 CASCADE)."""
    with connect(db_path) as conn:
        row = conn.execute(
            _sql("SELECT password_hash FROM posts WHERE id = ?"), (post_id,)
        ).fetchone()
        if row is None:
            raise PostNotFoundError("게시글을 찾을 수 없습니다.")
        if not verify_password(password, row["password_hash"]):
            raise PermissionError("비밀번호가 일치하지 않습니다.")
        conn.execute(_sql("DELETE FROM posts WHERE id = ?"), (post_id,))


def admin_delete_post(
    post_id: int, db_path: str | Path | None = None
) -> None:
    """관리자 권한으로 비밀번호 없이 게시글을 삭제한다."""
    with connect(db_path) as conn:
        cursor = conn.execute(_sql("DELETE FROM posts WHERE id = ?"), (post_id,))
        if cursor.rowcount == 0:
            raise PostNotFoundError("게시글을 찾을 수 없습니다.")


def increment_views(post_id: int, db_path: str | Path | None = None) -> None:
    """조회수를 1 증가시킨다."""
    with connect(db_path) as conn:
        conn.execute(
            _sql("UPDATE posts SET views = views + 1 WHERE id = ?"), (post_id,)
        )


def set_pinned(
    post_id: int,
    pinned: bool,
    db_path: str | Path | None = None,
) -> None:
    """게시글 상단 고정 여부를 변경한다(관리자용)."""
    with connect(db_path) as conn:
        cursor = conn.execute(
            _sql("UPDATE posts SET is_pinned = ? WHERE id = ?"),
            (1 if pinned else 0, post_id),
        )
        if cursor.rowcount == 0:
            raise PostNotFoundError("게시글을 찾을 수 없습니다.")


# ---------------------------------------------------------------------------
# 댓글
# ---------------------------------------------------------------------------


def add_comment(
    post_id: int,
    *,
    author: str,
    content: str,
    password: str,
    db_path: str | Path | None = None,
) -> int:
    """댓글을 추가하고 새 id 를 반환한다."""
    author = _validate_text(author, field="작성자", max_length=MAX_AUTHOR)
    content = _validate_text(content, field="댓글", max_length=MAX_COMMENT)
    password = _validate_password(password)

    timestamp = now_iso()
    params = (post_id, author, content, hash_password(password), timestamp)
    sql = """
        INSERT INTO comments (post_id, author, content, password_hash, created_at)
        VALUES (?, ?, ?, ?, ?)
    """
    with connect(db_path) as conn:
        exists = conn.execute(
            _sql("SELECT 1 FROM posts WHERE id = ?"), (post_id,)
        ).fetchone()
        if exists is None:
            raise PostNotFoundError("게시글을 찾을 수 없습니다.")

        if _using_postgres(db_path):
            cursor = conn.execute(_sql(sql + " RETURNING id"), params)
            return int(cursor.fetchone()["id"])
        cursor = conn.execute(_sql(sql), params)
        return int(cursor.lastrowid)


def list_comments(
    post_id: int, db_path: str | Path | None = None
) -> list[dict[str, Any]]:
    """게시글의 댓글을 시간순으로 반환한다."""
    with connect(db_path) as conn:
        rows = conn.execute(
            _sql(
                """
                SELECT id, post_id, author, content, created_at
                FROM comments
                WHERE post_id = ?
                ORDER BY created_at ASC, id ASC
                """
            ),
            (post_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def delete_comment(
    comment_id: int,
    *,
    password: str,
    db_path: str | Path | None = None,
) -> None:
    """비밀번호가 일치할 때만 댓글을 삭제한다."""
    with connect(db_path) as conn:
        row = conn.execute(
            _sql("SELECT password_hash FROM comments WHERE id = ?"), (comment_id,)
        ).fetchone()
        if row is None:
            raise PostNotFoundError("댓글을 찾을 수 없습니다.")
        if not verify_password(password, row["password_hash"]):
            raise PermissionError("비밀번호가 일치하지 않습니다.")
        conn.execute(_sql("DELETE FROM comments WHERE id = ?"), (comment_id,))


# ---------------------------------------------------------------------------
# 이미지 첨부
# ---------------------------------------------------------------------------


def add_post_images(
    post_id: int,
    images: list[dict[str, Any]],
    db_path: str | Path | None = None,
) -> None:
    """이미 업로드된 이미지 파일의 메타데이터를 게시글에 연결한다."""
    if not images:
        return
    with connect(db_path) as conn:
        exists = conn.execute(
            _sql("SELECT 1 FROM posts WHERE id = ?"), (post_id,)
        ).fetchone()
        if exists is None:
            raise PostNotFoundError("게시글을 찾을 수 없습니다.")
        start_row = conn.execute(
            _sql(
                "SELECT COALESCE(MAX(position), -1) + 1 AS next_position"
                " FROM post_images WHERE post_id = ?"
            ),
            (post_id,),
        ).fetchone()
        start = int(start_row["next_position"]) if start_row is not None else 0
        timestamp = now_iso()
        conn.executemany(
            _sql(
                """
                INSERT INTO post_images
                    (post_id, stored_name, thumb_name, mime, width, height,
                     byte_size, position, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """
            ),
            [
                (
                    post_id,
                    str(image["stored_name"]),
                    str(image["thumb_name"]),
                    str(image["mime"]),
                    int(image["width"]),
                    int(image["height"]),
                    int(image["byte_size"]),
                    start + offset,
                    timestamp,
                )
                for offset, image in enumerate(images)
            ],
        )


def list_post_images(
    post_id: int, db_path: str | Path | None = None
) -> list[dict[str, Any]]:
    """게시글에 연결된 이미지 목록을 반환한다."""
    with connect(db_path) as conn:
        rows = conn.execute(
            _sql(
                """
                SELECT id, post_id, stored_name, thumb_name, mime, width, height,
                       byte_size, position, created_at
                FROM post_images
                WHERE post_id = ?
                ORDER BY position ASC, id ASC
                """
            ),
            (post_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def delete_post_image(
    image_id: int, post_id: int, db_path: str | Path | None = None
) -> dict[str, Any] | None:
    """게시글에 연결된 이미지 메타데이터를 삭제하고 반환한다."""
    with connect(db_path) as conn:
        row = conn.execute(
            _sql("SELECT * FROM post_images WHERE id = ? AND post_id = ?"),
            (image_id, post_id),
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            _sql("DELETE FROM post_images WHERE id = ? AND post_id = ?"),
            (image_id, post_id),
        )
    return dict(row)


# ---------------------------------------------------------------------------
# 통계 / 보조
# ---------------------------------------------------------------------------


def list_categories(db_path: str | Path | None = None) -> list[tuple[str, int]]:
    """카테고리별 게시글 수를 반환한다."""
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT category, COUNT(*) AS cnt
            FROM posts
            GROUP BY category
            ORDER BY cnt DESC
            """
        ).fetchall()
    return [(str(row["category"]), int(row["cnt"])) for row in rows]


def stats(
    board: str | None = None, db_path: str | Path | None = None
) -> dict[str, int]:
    """대시보드용 요약 지표를 반환한다."""
    if board is None:
        where_posts = ""
        params: list[Any] = []
    else:
        where_posts = "WHERE p.board = ?"
        params = [_validate_board(board)]

    use_pg = _using_postgres(db_path)

    # "오늘"은 한국 시간(KST) 기준으로 센다. created_at 은 UTC ISO 문자열이다.
    if use_pg:
        date_today = (
            "(p.created_at::timestamptz AT TIME ZONE 'Asia/Seoul')::date"
            " = (now() AT TIME ZONE 'Asia/Seoul')::date"
        )
    else:
        date_today = "date(p.created_at, '+9 hours') = date('now', '+9 hours')"

    if board is None:
        where_today = f"WHERE {date_today}"
    else:
        where_today = f"WHERE p.board = ? AND {date_today}"

    today_params = [_validate_board(board)] if board is not None else []

    with connect(db_path) as conn:
        row = conn.execute(
            _sql(
                f"""
                SELECT
                    (SELECT COUNT(*) FROM posts p {where_posts}) AS total_posts,
                    (SELECT COUNT(*) FROM comments c
                       JOIN posts p ON p.id = c.post_id {where_posts})
                        AS total_comments,
                    (SELECT COUNT(*) FROM posts p {where_today}) AS posts_today,
                    (SELECT COALESCE(SUM(p.views), 0) FROM posts p {where_posts})
                        AS total_views
                """
            ),
            [*params, *params, *today_params, *params],
        ).fetchone()
    if row is None:
        return {"total_posts": 0, "total_comments": 0, "posts_today": 0, "total_views": 0}
    return {
        "total_posts": int(row["total_posts"]),
        "total_comments": int(row["total_comments"]),
        "posts_today": int(row["posts_today"]),
        "total_views": int(row["total_views"]),
    }


def all_posts_for_admin(
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """관리자 화면용 전체 게시글 목록(본문 제외)."""
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT p.id, p.board, p.category, p.title, p.author, p.views,
                   (SELECT COUNT(*) FROM comments c WHERE c.post_id = p.id)
                       AS comment_count,
                   (SELECT COUNT(*) FROM post_images i WHERE i.post_id = p.id)
                       AS image_count,
                   p.is_pinned, p.created_at
            FROM posts p
            ORDER BY p.id DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def export_all(db_path: str | Path | None = None) -> dict[str, Any]:
    """전체 데이터를 백업용 딕셔너리로 내보낸다.

    게시글·댓글·이미지 메타데이터를 모두 포함한다. 이미지 원본 파일은
    포함되지 않으므로 ``data/uploads`` 폴더는 별도로 보관해야 한다.
    """
    with connect(db_path) as conn:
        posts = [
            dict(row)
            for row in conn.execute("SELECT * FROM posts ORDER BY id").fetchall()
        ]
        comments = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM comments ORDER BY id"
            ).fetchall()
        ]
        images = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM post_images ORDER BY post_id, position, id"
            ).fetchall()
        ]

    return {
        "exported_at": now_iso(),
        "storage": "postgres" if _using_postgres(db_path) else "sqlite",
        "posts": posts,
        "comments": comments,
        "post_images": images,
    }
path: db.py