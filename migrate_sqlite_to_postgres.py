"""SQLite 데이터를 Postgres(Neon)로 복사하는 도구.

사용:
    python migrate_sqlite_to_postgres.py           # 미리보기 (쓰기 없음)
    python migrate_sqlite_to_postgres.py --apply   # 실제 이전

동작:
- 원본은 BOARD_DB_PATH(없으면 data/board.db) SQLite 파일이다.
- 대상은 DATABASE_URL / BOARD_DATABASE_URL / secrets.toml 의 DATABASE_URL 이다.
- 같은 (board, title, author, created_at) 게시글이 이미 있으면 건너뛴다(멱등).
- 댓글과 이미지 "메타데이터"도 함께 옮긴다. 이미지 원본 파일은 복사하지 않는다.
- 실패하면 전체를 롤백한다. --apply 없이는 항상 롤백한다.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

sys.path.insert(0, str(Path(__file__).resolve().parent))

import db as board_db  # noqa: E402
import images as board_images  # noqa: E402


def _read_source(
    path: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    if not path.exists():
        raise SystemExit(f"원본 SQLite 파일이 없습니다: {path}")
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        posts = [dict(row) for row in conn.execute("SELECT * FROM posts ORDER BY id")]
        comments = (
            [dict(row) for row in conn.execute("SELECT * FROM comments ORDER BY id")]
            if "comments" in tables
            else []
        )
        images = (
            [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM post_images ORDER BY post_id, position, id"
                )
            ]
            if "post_images" in tables
            else []
        )
    finally:
        conn.close()
    return posts, comments, images


def _ensure_target_schema(cur: Any) -> None:
    cur.execute(board_db.SCHEMA_SQL_PG)
    cur.execute(
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


def migrate(source: Path, *, apply: bool) -> int:
    if not board_db.DATABASE_URL:
        raise SystemExit(
            "DATABASE_URL(또는 BOARD_DATABASE_URL)이 설정되어 있지 않습니다."
        )

    posts, comments, images = _read_source(source)
    comments_by_post: dict[int, list[dict[str, Any]]] = {}
    images_by_post: dict[int, list[dict[str, Any]]] = {}
    for comment in comments:
        comments_by_post.setdefault(int(comment["post_id"]), []).append(comment)
    for image in images:
        images_by_post.setdefault(int(image["post_id"]), []).append(image)

    raw = psycopg2.connect(board_db.DATABASE_URL, cursor_factory=RealDictCursor)
    copied_posts = skipped_posts = copied_comments = copied_images = 0
    missing_files: list[str] = []

    try:
        cur = raw.cursor()
        _ensure_target_schema(cur)

        for post in posts:
            post_board = str(post.get("board") or board_db.DEFAULT_BOARD)
            cur.execute(
                """
                SELECT 1 FROM posts
                 WHERE board = %s AND title = %s AND author = %s
                   AND created_at = %s
                 LIMIT 1
                """,
                (
                    post_board,
                    post["title"],
                    post["author"],
                    post["created_at"],
                ),
            )
            if cur.fetchone() is not None:
                skipped_posts += 1
                print(f"  건너뜀 (이미 있음): [{post_board}] {post['title']}")
                continue

            cur.execute(
                """
                INSERT INTO posts
                    (board, category, title, author, content, password_hash,
                     views, is_pinned, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    post_board,
                    post["category"],
                    post["title"],
                    post["author"],
                    post["content"],
                    post["password_hash"],
                    post["views"],
                    post["is_pinned"],
                    post["created_at"],
                    post["updated_at"],
                ),
            )
            new_id = int(cur.fetchone()["id"])
            copied_posts += 1
            print(f"  복사: #{post['id']} → #{new_id}  [{post_board}] {post['title']}")

            for comment in comments_by_post.get(int(post["id"]), []):
                cur.execute(
                    """
                    INSERT INTO comments
                        (post_id, author, content, password_hash, created_at)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        new_id,
                        comment["author"],
                        comment["content"],
                        comment["password_hash"],
                        comment["created_at"],
                    ),
                )
                copied_comments += 1

            for image in images_by_post.get(int(post["id"]), []):
                cur.execute(
                    """
                    INSERT INTO post_images
                        (post_id, stored_name, thumb_name, mime, width, height,
                         byte_size, position, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        new_id,
                        image["stored_name"],
                        image["thumb_name"],
                        image["mime"],
                        image["width"],
                        image["height"],
                        image["byte_size"],
                        image["position"],
                        image["created_at"],
                    ),
                )
                copied_images += 1
                for name in (image["stored_name"], image["thumb_name"]):
                    if not (board_images.UPLOAD_DIR / str(name)).is_file():
                        missing_files.append(str(name))

        if apply:
            raw.commit()
            print("커밋했습니다.")
        else:
            raw.rollback()
            print("미리보기 모드입니다. 실제로 저장하지 않았습니다. (--apply 로 실행)")
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()

    print(
        f"게시글 {copied_posts}건 복사, {skipped_posts}건 건너뜀, "
        f"댓글 {copied_comments}건, 이미지 메타데이터 {copied_images}건"
    )
    if missing_files:
        print(
            "주의: 다음 이미지 파일이 로컬 uploads 폴더에 없습니다: "
            + ", ".join(sorted(set(missing_files)))
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help="원본 SQLite 파일 (기본: BOARD_DB_PATH 또는 data/board.db)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="실제로 대상 Postgres 에 저장한다. 없으면 미리보기만 한다.",
    )
    args = parser.parse_args()

    source = args.source or board_db.resolve_db_path()
    print(f"원본: {source}")
    print("대상: Postgres (DATABASE_URL)")
    return migrate(source, apply=args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
