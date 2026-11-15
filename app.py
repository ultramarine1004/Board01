"""한줄게시판 - Streamlit UI.

실행:
    python -m streamlit run board/app.py

데이터는 SQLite(board/data/board.db)에 저장된다. 상세 동작과 배포 주의사항은
board/README.md 참고.
"""

from __future__ import annotations

import hmac
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import streamlit as st

# streamlit run 의 작업 디렉터리와 무관하게 db.py 를 찾을 수 있게 한다.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import db as board_db  # noqa: E402  (sys.path 설정 이후 import)
import images as board_images  # noqa: E402

APP_TITLE = "한줄게시판"
DEFAULT_ADMIN_PASSWORD = "admin123"
PAGE_SIZE_OPTIONS = (5, 10, 20)

LOGO_PATH = Path(__file__).resolve().parent / "logos" / "hayun-story-logo.svg"
BRAND_BG = "#FFF8F1"
BRAND_INK = "#1a1e1e"

# Streamlit 테마에 사이드바 배경 키가 없어 CSS 주입을 쓴다.
# 치환되는 값은 고정 상수뿐이라 사용자 입력이 HTML 로 새지 않는다.
_SIDEBAR_CSS = """
<style>
section[data-testid="stSidebar"] {
    background-color: __BG__;
    border-right: 1px solid #dcdedd;
}
section[data-testid="stSidebar"] div[data-testid="stSidebarHeader"],
section[data-testid="stSidebar"] div[data-testid="stSidebarContent"] {
    background-color: transparent;
}
section[data-testid="stSidebar"] div[data-testid="stSidebarContent"] {
    padding-left: 8px;
    padding-right: 8px;
}
section[data-testid="stSidebar"] [data-testid="stImage"] img {
    background-color: #FFF8F1;
    border: 1px solid #dcdedd;
    border-radius: 8px;
}
section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p,
section[data-testid="stSidebar"] label p {
    color: __INK__;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: -0.01em;
}
section[data-testid="stSidebar"] [data-testid="stRadioGroup"] {
    gap: 2px;
}
section[data-testid="stSidebar"] [data-testid="stRadioOption"] {
    display: flex;
    align-items: center;
    padding: 6px 8px;
    border-radius: 6px;
    color: #798686;
    transition: background-color 0.12s ease, color 0.12s ease;
}
section[data-testid="stSidebar"] [data-testid="stRadioOption"]:hover {
    background-color: #f3f5f8;
    color: __INK__;
}
section[data-testid="stSidebar"] [data-testid="stRadioOption"][data-selected="true"] {
    background-color: #f1f3f3;
    color: __INK__;
    font-weight: 600;
}
section[data-testid="stSidebar"] [data-testid="stRadioOption"] div:not(:has(p)):not(:has(input)) {
    display: none;
}
section[data-testid="stSidebar"] [data-testid="stRadioOption"] p {
    color: inherit;
    font-size: 13px;
}
section[data-testid="stSidebar"] [data-testid="stTextInputRootElement"] {
    height: 32px;
    min-height: 32px;
    background-color: #ffffff;
    border: 1px solid #dcdedd;
    border-radius: 8px;
    padding: 0 8px;
}
section[data-testid="stSidebar"] [data-testid="stTextInputRootElement"] input {
    height: 30px;
    padding: 0;
    font-size: 13px;
}
section[data-testid="stSidebar"] [data-testid="stTextInputRootElement"]:hover {
    border-color: #cfd3d3;
}
section[data-testid="stSidebar"] [data-testid="stTextInputRootElement"]:focus-within {
    border-color: __INK__;
    box-shadow: 0 0 0 3px rgba(26, 30, 30, 0.08);
}
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {
    color: #798686;
    font-size: 11px;
    line-height: 1.5;
}
section[data-testid="stSidebar"] hr {
    margin: 12px 0;
    border-top: 1px solid #dcdedd;
}
section[data-testid="stSidebar"] svg {
    color: #798686;
}
</style>
"""

# 사이드바(300px)와 본문(1024px)을 합친 1324px 프레임을 화면 가운데에 고정 배치한다.
# 본문 폭은 브라우저 폭과 무관하게 1024px 로 유지되고, 프레임 바깥의 남는 영역은
# 캔버스와 같은 크림색이라 좌우 여백이 자연스럽게 배경으로 이어진다.
_LAYOUT_CSS = """
<style>
:root {
    --board-sidebar-width: 300px;
    --board-main-width: 1024px;
    --board-frame-width: 1324px;
}
[data-testid="stApp"],
[data-testid="stAppViewContainer"] {
    background-color: __BG__;
}
header[data-testid="stHeader"] {
    background: transparent;
}
section[data-testid="stSidebar"] {
    margin-left: max(0px, calc((100vw - var(--board-frame-width)) / 2));
}
section[data-testid="stSidebar"][data-collapsed="true"] {
    margin-left: 0;
}
section[data-testid="stSidebar"][data-collapsed="true"] ~ * main[data-testid="stMain"] {
    margin-left: auto;
}
main[data-testid="stMain"] {
    flex: 0 0 var(--board-main-width);
    width: var(--board-main-width);
    background-color: #ffffff;
    border-right: 1px solid #dcdedd;
    margin-right: auto;
}
main[data-testid="stMain"] div[data-testid="stMainBlockContainer"] {
    width: 100%;
    max-width: 100%;
    padding: 72px 32px 120px;
}
</style>
"""

_DANGEROUS_SCHEMES = re.compile(
    r"(javascript|vbscript|data)\s*:", re.IGNORECASE
)
_MARKDOWN_SPECIALS = re.compile(r"([\\`*_{}\[\]()#+\-.!|>])")


# ---------------------------------------------------------------------------
# 공통 유틸
# ---------------------------------------------------------------------------


def _init_state() -> None:
    defaults: dict[str, Any] = {
        "board": board_db.DEFAULT_BOARD,
        "route": "list",
        "post_id": None,
        "viewed": set(),
        "admin_authed": False,
        "page": 1,
        "flash": None,
        "filter_sig": "",
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def _go(route: str, post_id: int | None = None) -> None:
    st.session_state.route = route
    st.session_state.post_id = post_id
    st.rerun()


def _flash(message: str, icon: str = "✅") -> None:
    st.session_state.flash = (message, icon)


def _render_flash() -> None:
    flash = st.session_state.flash
    if flash:
        message, icon = flash
        st.toast(message, icon=icon)
        st.session_state.flash = None


def _fmt_time(iso_text: str) -> str:
    """ISO-8601 UTC 문자열을 로컬 시간(YYYY-MM-DD HH:MM)으로 변환한다."""
    try:
        parsed = datetime.fromisoformat(iso_text)
    except (TypeError, ValueError):
        return str(iso_text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M")


def _escape_markdown(text: str) -> str:
    """제목 등 한 줄 텍스트에서 마크다운 서식을 무력화한다."""
    return _MARKDOWN_SPECIALS.sub(r"\\\1", str(text))


def _sanitize_markdown(text: str) -> str:
    """사용자 본문에서 위험한 URL 스킴만 제거한다(나머지 마크다운은 허용)."""
    return _DANGEROUS_SCHEMES.sub(r"\1：", str(text))


def _admin_password() -> str:
    """secrets.toml 의 admin_password 를 읽는다. 없으면 기본값."""
    try:
        value = st.secrets.get("admin_password", DEFAULT_ADMIN_PASSWORD)
    except (FileNotFoundError, KeyError, AttributeError, RuntimeError):
        return DEFAULT_ADMIN_PASSWORD
    return str(value) if value else DEFAULT_ADMIN_PASSWORD


def _total_pages(total: int, page_size: int) -> int:
    return max(1, math.ceil(total / page_size)) if total else 1


def _render_table(rows: list[dict[str, Any]]) -> None:
    """관리자 표를 렌더링한다.

    st.dataframe 은 pyarrow 를 요구한다. pyarrow 가 없는/차단된 환경
    (예: 사내 애플리케이션 제어 정책)에서는 마크다운 표로 대체한다.
    """
    try:
        st.dataframe(rows, hide_index=True, width="stretch")
    except ImportError:
        st.markdown(_table_to_markdown(rows))


def _table_to_markdown(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    columns = list(rows[0])
    header = "| " + " | ".join(columns) + " |"
    divider = "| " + " | ".join("---" for _ in columns) + " |"
    body = [
        "| " + " | ".join(_table_cell(row[column]) for column in columns) + " |"
        for row in rows
    ]
    return "\n".join([header, divider, *body])


def _table_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _image_file_names(rows: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for row in rows:
        names.append(str(row["stored_name"]))
        names.append(str(row["thumb_name"]))
    return names


# ---------------------------------------------------------------------------
# 사이드바
# ---------------------------------------------------------------------------


def _apply_branding() -> None:
    st.markdown(
        (_SIDEBAR_CSS + _LAYOUT_CSS)
        .replace("__BG__", BRAND_BG)
        .replace("__INK__", BRAND_INK),
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <style>
        @font-face {
            font-family: 'NanumSquareNeo';
            src: url('https://cdn.jsdelivr.net/gh/projectnoonnu/noonfonts_11-01@1.0/NanumSquareNeoTTF-bRg.woff2') format('woff2');
            font-weight: 300;
            font-style: normal;
            font-display: swap;
        }
        @font-face {
            font-family: 'NanumSquareNeo';
            src: url('https://cdn.jsdelivr.net/gh/projectnoonnu/noonfonts_11-01@1.0/NanumSquareNeoTTF-aLt.woff2') format('woff2');
            font-weight: 400;
            font-style: normal;
            font-display: swap;
        }
        @font-face {
            font-family: 'NanumSquareNeo';
            src: url('https://cdn.jsdelivr.net/gh/projectnoonnu/noonfonts_11-01@1.0/NanumSquareNeoTTF-cBd.woff2') format('woff2');
            font-weight: 700;
            font-style: normal;
            font-display: swap;
        }
        html, body, [class*="css"] {
            font-family: 'NanumSquareNeo', 'Nanum Square Neo', sans-serif !important;
        }
        main img {
            max-width: 100% !important;
            height: auto !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    if LOGO_PATH.exists():
        st.sidebar.image(str(LOGO_PATH), width="stretch")
    else:
        st.sidebar.markdown(f"## 📌 {APP_TITLE}")


def _render_sidebar() -> str:
    with st.sidebar:
        slugs = list(board_db.BOARDS)
        labels = [board_db.BOARDS[slug] for slug in slugs]
        current = st.session_state.board
        index = slugs.index(current) if current in slugs else 0

        choice = st.radio(
            "게시판", labels, index=index, label_visibility="collapsed"
        )
        chosen = slugs[labels.index(choice)]
        if chosen != current:
            st.session_state.board = chosen
            st.session_state.page = 1
            st.session_state.route = "list"
            st.session_state.post_id = None
            st.rerun()

        st.divider()
        st.markdown(
            "<div style='min-height:40vh;'></div>", unsafe_allow_html=True
        )
        if st.button("⚙️ 관리자", key="nav_admin", width="stretch"):
            st.session_state.route = "admin"
            st.session_state.post_id = None
            st.rerun()

    return str(st.session_state.board)


# ---------------------------------------------------------------------------
# 목록 화면
# ---------------------------------------------------------------------------


def render_list(board_slug: str) -> None:
    st.markdown(
        """
        <style>
        button[kind="tertiary"],
        button[kind="tertiary"] * {
            color: #000000 !important;
            font-family: 'NanumSquareNeo', 'Nanum Square Neo', sans-serif !important;
            font-size: 16px !important;
            font-weight: 500 !important;
            text-align: left !important;
            justify-content: flex-start !important;
            align-items: center !important;
        }
        button[kind="tertiary"] {
            width: 100% !important;
            padding-left: 0 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    title_column, action_column = st.columns([3, 1], vertical_alignment="center")
    title_column.markdown(f"### {board_db.board_label(board_slug)}")
    with action_column:
        if st.button("새글", type="primary", width="stretch", key="new_post"):
            _go("write")

    search_column, sort_column, size_column = st.columns(
        [2.2, 1, 1], vertical_alignment="bottom"
    )
    keyword = search_column.text_input(
        "검색", placeholder="제목 · 내용 · 작성자", key="list_search"
    )
    sort_label = sort_column.selectbox(
        "정렬", tuple(board_db.SORT_OPTIONS.keys()), key="list_sort"
    )
    page_size = int(
        size_column.selectbox(
            "페이지당", PAGE_SIZE_OPTIONS, index=1, key="list_page_size"
        )
    )

    signature = f"{board_slug}|{keyword}|{sort_label}|{page_size}"
    if signature != st.session_state.filter_sig:
        st.session_state.filter_sig = signature
        st.session_state.page = 1

    summary = board_db.stats(board_slug)
    st.caption(
        f"게시글 {summary['total_posts']:,}건"
        f" · 댓글 {summary['total_comments']:,}개"
        f" · 오늘 {summary['posts_today']:,}건"
    )

    posts, total = board_db.list_posts(
        query=keyword,
        sort=board_db.SORT_OPTIONS[sort_label],
        page=int(st.session_state.page),
        page_size=page_size,
        board=board_slug,
    )
    total_pages = _total_pages(total, page_size)
    if int(st.session_state.page) > total_pages:
        st.session_state.page = total_pages
        st.rerun()

    if keyword.strip():
        st.caption(f"'{keyword.strip()}' 검색 결과 {total:,}건")
    else:
        st.caption(f"총 {total:,}건 · {st.session_state.page}/{total_pages} 페이지")

    if not posts:
        if keyword.strip():
            st.info("조건에 맞는 게시글이 없습니다. 검색어를 조정해 보세요.")
        else:
            st.info("이 게시판에는 아직 게시글이 없습니다. '새글'로 첫 글을 남겨 보세요.")
        return

    for post in posts:
        with st.container(border=True):
            thumb_name = str(post.get("thumb_name") or "")
            if thumb_name and board_images.exists(thumb_name):
                thumb_column, body_column = st.columns(
                    [1, 9], vertical_alignment="center"
                )
                thumb_column.image(
                    str(board_images.resolve(thumb_name)), width=40
                )
            else:
                body_column = st.container()
            title_label = ("📌 " if post["is_pinned"] else "") + str(post["title"])
            meta_text = (
                f"{post['author']} / {_fmt_time(post['created_at'])} / 조회 {post['views']}"
            )
            title_col, meta_col = body_column.columns([7, 3], vertical_alignment="center")
            if title_col.button(
                title_label,
                key=f"open_{post['id']}",
                type="tertiary",
                width="stretch",
                help="게시글 열기",
            ):
                _go("detail", int(post["id"]))
            meta_col.markdown(
                f"<div style='text-align:right;color:#4a4a4a;font-size:13px;"
                f"font-family:NanumSquareNeo,sans-serif;white-space:nowrap;'>"
                f"{meta_text}</div>",
                unsafe_allow_html=True,
            )

    _render_pagination(total_pages)


def _render_pagination(total_pages: int) -> None:
    if total_pages <= 1:
        return

    current = int(st.session_state.page)
    window = 2
    start = max(1, current - window)
    end = min(total_pages, current + window)
    page_numbers = list(range(start, end + 1))

    columns = st.columns(len(page_numbers) + 2)
    if columns[0].button("← 이전", disabled=current <= 1, width="stretch"):
        st.session_state.page = max(1, current - 1)
        st.rerun()
    for offset, number in enumerate(page_numbers, start=1):
        label = f"{number}" if number != current else f"**{number}**"
        if columns[offset].button(
            label, key=f"page_{number}", width="stretch",
            type="primary" if number == current else "secondary",
        ):
            st.session_state.page = number
            st.rerun()
    if columns[-1].button(
        "다음 →", disabled=current >= total_pages, width="stretch"
    ):
        st.session_state.page = min(total_pages, current + 1)
        st.rerun()


# ---------------------------------------------------------------------------
# 상세 화면
# ---------------------------------------------------------------------------


def render_detail() -> None:
    post_id = st.session_state.post_id
    post = board_db.get_post(int(post_id)) if post_id else None

    if post is None:
        st.warning("게시글을 찾을 수 없습니다. 이미 삭제되었을 수 있습니다.")
        if st.button("← 목록으로"):
            _go("list")
        return

    post_board = str(post["board"] or board_db.DEFAULT_BOARD)
    if post_board not in board_db.BOARDS:
        post_board = board_db.DEFAULT_BOARD
    st.session_state.board = post_board

    viewed: set[int] = st.session_state.viewed
    if int(post_id) not in viewed:
        board_db.increment_views(int(post_id))
        viewed.add(int(post_id))
        post["views"] = int(post["views"]) + 1

    st.caption(
        f"{board_db.board_label(post_board)}  ·  {post['category']}"
        f"  ·  {_fmt_time(post['created_at'])}"
        f"  ·  조회 {post['views']}"
    )
    top_bar = st.columns([6, 1, 1, 1], vertical_alignment="center")
    with top_bar[1]:
        if st.button("목록", key=f"detail_back_{post_id}", width="stretch"):
            _go("list")
    with top_bar[2]:
        if st.button("✏️ 수정", key=f"detail_edit_{post_id}", width="stretch"):
            _go("edit", int(post_id))
    with top_bar[3]:
        with st.popover("🗑️ 삭제", width="stretch"):
            _render_delete_post_form(int(post_id))
    st.markdown(f"#### {_escape_markdown(post['title'])}")
    st.caption(f"작성자 {post['author']}")
    st.divider()
    st.markdown(_sanitize_markdown(post["content"]))

    for image in board_db.list_post_images(int(post_id)):
        stored_name = str(image["stored_name"])
        if board_images.exists(stored_name):
            st.image(str(board_images.resolve(stored_name)), width="content")

    if post["updated_at"] != post["created_at"]:
        st.caption(f"수정됨 · {_fmt_time(post['updated_at'])}")

    st.divider()
    _render_comments(int(post_id))


def _render_delete_post_form(post_id: int) -> None:
    with st.form(f"delete_post_{post_id}"):
        st.caption("삭제하려면 작성 시 입력한 비밀번호가 필요합니다.")
        password = st.text_input("비밀번호", type="password", key=f"del_pw_{post_id}")
        confirmed = st.checkbox("삭제에 동의합니다", key=f"del_ok_{post_id}")
        if st.form_submit_button("삭제", type="primary", width="stretch"):
            if not confirmed:
                st.error("삭제 동의에 체크해 주세요.")
                return
            attached = board_db.list_post_images(post_id)
            try:
                board_db.delete_post(post_id, password=password)
            except PermissionError as error:
                st.error(str(error))
            except board_db.PostNotFoundError as error:
                st.error(str(error))
            else:
                board_images.delete_files(_image_file_names(attached))
                _flash("게시글을 삭제했습니다.", "🗑️")
                _go("list")


def _render_comments(post_id: int) -> None:
    comments = board_db.list_comments(post_id)
    st.markdown(f"#### 댓글 {len(comments)}")

    if not comments:
        st.caption("첫 댓글을 남겨 보세요.")
    for comment in comments:
        with st.container(border=True):
            st.caption(f"{comment['author']} · {_fmt_time(comment['created_at'])}")
            st.markdown(_sanitize_markdown(comment["content"]))
            with st.expander("댓글 삭제"):
                with st.form(f"delete_comment_{comment['id']}"):
                    password = st.text_input(
                        "비밀번호",
                        type="password",
                        key=f"cdel_pw_{comment['id']}",
                    )
                    if st.form_submit_button("삭제"):
                        try:
                            board_db.delete_comment(
                                int(comment["id"]), password=password
                            )
                        except (PermissionError, board_db.PostNotFoundError) as error:
                            st.error(str(error))
                        else:
                            _flash("댓글을 삭제했습니다.", "🗑️")
                            st.rerun()

    with st.form(f"add_comment_{post_id}", clear_on_submit=True):
        st.markdown("**댓글 작성**")
        name_column, password_column = st.columns(2)
        author = name_column.text_input(
            "작성자", max_chars=board_db.MAX_AUTHOR, key=f"c_author_{post_id}"
        )
        password = password_column.text_input(
            "비밀번호",
            type="password",
            help="댓글 삭제 시 필요합니다.",
            key=f"c_pw_{post_id}",
        )
        content = st.text_area(
            "댓글 내용",
            max_chars=board_db.MAX_COMMENT,
            height=100,
            key=f"c_content_{post_id}",
        )
        submitted = st.form_submit_button("댓글 등록", type="primary")
        if submitted:
            try:
                board_db.add_comment(
                    post_id,
                    author=author,
                    content=content,
                    password=password,
                )
            except ValueError as error:
                st.error(str(error))
            except board_db.PostNotFoundError as error:
                st.error(str(error))
            else:
                _flash("댓글을 등록했습니다.")
                st.rerun()


# ---------------------------------------------------------------------------
# 작성 / 수정 화면
# ---------------------------------------------------------------------------


def render_write() -> None:
    is_edit = st.session_state.route == "edit"
    post: dict[str, Any] | None = None
    if is_edit:
        post_id = st.session_state.post_id
        post = board_db.get_post(int(post_id)) if post_id else None
        if post is None:
            st.warning("수정할 게시글을 찾을 수 없습니다.")
            if st.button("← 목록으로"):
                _go("list")
            return

    target_board = (
        str(post["board"])
        if post and str(post["board"]) in board_db.BOARDS
        else str(st.session_state.board)
    )

    st.markdown(f"### {'✏️ 게시글 수정' if is_edit else '✍️ 새 글 작성'}")
    st.caption(f"게시판 · {board_db.board_label(target_board)}")
    st.caption("비밀번호는 수정·삭제 시에만 사용되며, 해시로만 저장됩니다.")

    category_index = (
        board_db.CATEGORIES.index(post["category"])
        if post and post["category"] in board_db.CATEGORIES
        else 0
    )

    with st.form("post_form"):
        category = st.selectbox(
            "카테고리", board_db.CATEGORIES, index=category_index
        )
        title = st.text_input(
            "제목",
            value=post["title"] if post else "",
            max_chars=board_db.MAX_TITLE,
            placeholder=f"{board_db.MIN_TITLE}자 이상 입력",
        )
        name_column, password_column = st.columns(2)
        author = name_column.text_input(
            "작성자",
            value=post["author"] if post else "",
            max_chars=board_db.MAX_AUTHOR,
        )
        password = password_column.text_input(
            "비밀번호",
            type="password",
            help="수정·삭제 시 필요합니다. 4자 이상.",
        )
        content = st.text_area(
            "내용",
            value=post["content"] if post else "",
            max_chars=board_db.MAX_CONTENT,
            height=320,
            placeholder="마크다운 문법을 사용할 수 있습니다.",
        )
        st.caption(f"{len(content)} / {board_db.MAX_CONTENT}자")

        attached_images = (
            board_db.list_post_images(int(post["id"])) if is_edit and post else []
        )
        images_allowed = board_images.is_enabled(target_board)
        remove_image_ids: set[int] = set()
        if images_allowed and attached_images:
            st.caption("등록된 사진 · 삭제할 사진은 체크해 주세요.")
            for image in attached_images:
                thumb_name = str(image["thumb_name"])
                image_column, check_column = st.columns(
                    [3, 1], vertical_alignment="center"
                )
                if board_images.exists(thumb_name):
                    image_column.image(
                        str(board_images.resolve(thumb_name)), width=96
                    )
                else:
                    image_column.caption("파일을 찾을 수 없습니다.")
                if check_column.checkbox("삭제", key=f"rm_image_{image['id']}"):
                    remove_image_ids.add(int(image["id"]))
        if images_allowed:
            uploaded_files = st.file_uploader(
                "사진",
                type=list(board_images.ACCEPTED_TYPES),
                accept_multiple_files=True,
                key="post_images",
                help=(
                    f"게시글당 {board_images.MAX_IMAGES_PER_POST}장,"
                    " 장당 5MB 까지 올릴 수 있습니다."
                ),
            )
            st.caption("긴 변 1920px 로 자동 축소되고 촬영 위치 정보는 제거됩니다.")
        else:
            uploaded_files = []

        button_columns = st.columns([1, 1, 3])
        submitted = button_columns[0].form_submit_button(
            "수정 완료" if is_edit else "등록하기",
            type="primary",
            width="stretch",
        )
        cancelled = button_columns[1].form_submit_button(
            "취소", width="stretch"
        )

    if cancelled:
        if is_edit and post:
            _go("detail", int(post["id"]))
        else:
            _go("list")

    if submitted:
        remaining = max(0, len(attached_images) - len(remove_image_ids))
        try:
            board_images.validate(uploaded_files, existing_count=remaining)
        except board_images.ImageValidationError as error:
            st.error(str(error))
            return
        try:
            if is_edit and post:
                post_id = int(post["id"])
                board_db.update_post(
                    post_id,
                    password=password,
                    title=title,
                    content=content,
                    category=category,
                )
                for image_id in remove_image_ids:
                    removed = board_db.delete_post_image(image_id, post_id)
                    if removed:
                        board_images.delete_files(_image_file_names([removed]))
                board_db.add_post_images(
                    post_id, board_images.save_uploads(uploaded_files)
                )
                _flash("게시글을 수정했습니다.")
                _go("detail", post_id)
            else:
                saved = board_images.save_uploads(uploaded_files)
                new_id: int | None = None
                try:
                    new_id = board_db.create_post(
                        board=target_board,
                        category=category,
                        title=title,
                        author=author,
                        content=content,
                        password=password,
                    )
                    board_db.add_post_images(new_id, saved)
                except Exception:
                    if new_id is not None:
                        board_db.admin_delete_post(new_id)
                    board_images.delete_files(_image_file_names(saved))
                    raise
                _flash("게시글을 등록했습니다.")
                _go("detail", new_id)
        except (ValueError, PermissionError, board_db.PostNotFoundError) as error:
            st.error(str(error))


# ---------------------------------------------------------------------------
# 관리자 화면
# ---------------------------------------------------------------------------


def render_admin() -> None:
    st.markdown("### ⚙️ 관리자")
    if st.button("← 목록으로", key="admin_back"):
        _go("list")

    if not st.session_state.admin_authed:
        st.caption("관리자 비밀번호를 입력해 주세요.")
        with st.form("admin_login"):
            password = st.text_input("관리자 비밀번호", type="password")
            submitted = st.form_submit_button("로그인", type="primary")
            if submitted:
                if hmac.compare_digest(password, _admin_password()):
                    st.session_state.admin_authed = True
                    st.rerun()
                else:
                    st.error("비밀번호가 일치하지 않습니다.")
        st.caption(
            "로컬 기본값은 admin123 입니다. 배포 시 .streamlit/secrets.toml 의 "
            "admin_password 를 반드시 변경하세요."
        )
        return

    st.success("관리자 모드로 로그인했습니다.")
    if st.button("로그아웃"):
        st.session_state.admin_authed = False
        st.rerun()

    summary = board_db.stats()
    metric_columns = st.columns(3)
    metric_columns[0].metric("전체 게시글", f"{summary['total_posts']:,}건")
    metric_columns[1].metric("전체 댓글", f"{summary['total_comments']:,}개")
    metric_columns[2].metric("누적 조회", f"{summary['total_views']:,}회")

    db_path = board_db.resolve_db_path()
    st.markdown("#### 데이터 백업")
    st.caption(
        "무료 호스팅은 서버가 재시작되면 파일이 사라질 수 있습니다. "
        "주기적으로 백업 파일을 내려받아 보관하세요."
    )
    if db_path.exists():
        st.download_button(
            "SQLite 백업 다운로드",
            data=db_path.read_bytes(),
            file_name=f"board-backup-{datetime.now().strftime('%Y%m%d-%H%M')}.db",
            mime="application/octet-stream",
        )
    else:
        st.info("아직 데이터베이스 파일이 없습니다.")

    posts = board_db.all_posts_for_admin()
    st.markdown("#### 게시글 관리")
    if not posts:
        st.info("등록된 게시글이 없습니다.")
        return

    table_rows = [
        {
            "ID": post["id"],
            "게시판": board_db.board_label(str(post["board"])),
            "카테고리": post["category"],
            "제목": post["title"],
            "작성자": post["author"],
            "조회": post["views"],
            "댓글": post["comment_count"],
            "고정": "📌" if post["is_pinned"] else "",
            "작성일": _fmt_time(post["created_at"]),
        }
        for post in posts
    ]
    _render_table(table_rows)

    st.markdown("#### 개별 작업")
    titles = {
        int(post["id"]): f"[{board_db.board_label(str(post['board']))}] {post['title']}"
        for post in posts
    }
    selected_id = int(
        st.selectbox(
            "게시글 선택",
            options=list(titles),
            format_func=lambda post_id: f"#{post_id} · {titles[post_id]}",
            key="admin_selected_post",
        )
    )
    selected = next(post for post in posts if int(post["id"]) == selected_id)
    pin_column, open_column, delete_column = st.columns(3)
    pin_label = "📌 고정 해제" if selected["is_pinned"] else "📌 상단 고정"
    if pin_column.button(pin_label, width="stretch"):
        board_db.set_pinned(selected_id, not bool(selected["is_pinned"]))
        _flash("고정 상태를 변경했습니다.", "📌")
        st.rerun()
    if open_column.button("열기", width="stretch"):
        _go("detail", selected_id)
    if delete_column.button("삭제", type="primary", width="stretch"):
        attached = board_db.list_post_images(selected_id)
        try:
            board_db.admin_delete_post(selected_id)
        except board_db.PostNotFoundError as error:
            st.error(str(error))
        else:
            board_images.delete_files(_image_file_names(attached))
            _flash("게시글을 삭제했습니다.", "🗑️")
            st.rerun()


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------


def main() -> None:
    st.set_page_config(
        page_title=APP_TITLE,
        page_icon="📌",
        layout="wide",
    )
    board_db.init_db()
    _init_state()
    _render_flash()
    _apply_branding()

    board_slug = _render_sidebar()

    route = st.session_state.route
    if route == "detail":
        render_detail()
    elif route in ("write", "edit"):
        render_write()
    elif route == "admin":
        render_admin()
    else:
        st.session_state.route = "list"
        render_list(board_slug)


main()
