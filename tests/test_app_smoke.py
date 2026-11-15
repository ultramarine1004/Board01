"""app.py 를 실제로 실행해 보는 스모크 테스트 (Streamlit AppTest).

실행:
    python -m pytest board/tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

BOARD_DIR = Path(__file__).resolve().parents[1]
APP_PATH = BOARD_DIR / "app.py"
sys.path.insert(0, str(BOARD_DIR))

import db as board_db

BOARD_LABELS = [board_db.BOARDS[slug] for slug in board_db.BOARDS]
TEST_ADMIN_PASSWORD = "test-admin-1234"


@pytest.fixture()
def at(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    monkeypatch.setenv("BOARD_DB_PATH", str(tmp_path / "smoke.db"))
    app = AppTest.from_file(str(APP_PATH), default_timeout=60)
    # 개발자 PC의 secrets.toml 과 무관하게 항상 같은 비밀번호로 테스트한다.
    app.secrets["admin_password"] = TEST_ADMIN_PASSWORD
    app.run()
    return app


def _click(app: AppTest, label: str) -> None:
    button = next(item for item in app.button if item.label == label or item.label.startswith(label + "  ·"))
    button.click().run()


def _input(app: AppTest, label: str):
    return next(item for item in app.text_input if item.label == label)


def _input_by_key(app: AppTest, key: str):
    return app.text_input(key=key)


def test_app_boots_without_exception(at: AppTest) -> None:
    assert not at.exception
    assert at.radio[0].options == BOARD_LABELS
    assert at.session_state["board"] == board_db.DEFAULT_BOARD
    assert any("아직 게시글이 없습니다" in info.value for info in at.info)


def test_write_flow_creates_post_and_opens_detail(at: AppTest) -> None:
    _click(at, "새글")
    assert at.session_state["route"] == "write"

    _input(at, "제목").set_value("스모크 제목")
    _input(at, "작성자").set_value("테스터")
    _input(at, "비밀번호").set_value("1234")
    at.text_area[0].set_value("본문입니다.")
    _click(at, "등록하기")

    assert at.session_state["route"] == "detail"
    post_id = int(at.session_state["post_id"])
    post = board_db.get_post(post_id)
    assert post is not None
    assert post["title"] == "스모크 제목"
    assert post["board"] == board_db.DEFAULT_BOARD
    assert post["views"] == 1
    assert any("스모크 제목" in element.value for element in at.markdown)


def test_validation_error_is_shown(at: AppTest) -> None:
    _click(at, "새글")
    _input(at, "제목").set_value("가")
    _input(at, "작성자").set_value("테스터")
    _input(at, "비밀번호").set_value("1234")
    at.text_area[0].set_value("본문입니다.")
    _click(at, "등록하기")

    assert at.session_state["route"] == "write"
    assert any("제목" in error.value for error in at.error)


def test_search_and_detail_navigation(at: AppTest) -> None:
    board_db.create_post(
        category="정보",
        title="검색될 글",
        author="작성자",
        content="내용",
        password="1234",
    )
    board_db.create_post(
        category="자유",
        title="다른 글",
        author="작성자",
        content="내용",
        password="1234",
    )
    at.run()

    _input(at, "검색").set_value("검색될").run()
    assert any("검색 결과 1건" in caption.value for caption in at.caption)

    _click(at, "검색될 글")
    assert at.session_state["route"] == "detail"
    post = board_db.get_post(int(at.session_state["post_id"]))
    assert post is not None and post["title"] == "검색될 글"


def test_admin_login_and_delete(at: AppTest) -> None:
    post_id = board_db.create_post(
        category="공지",
        title="삭제될 글",
        author="운영자",
        content="내용",
        password="1234",
    )
    at.run()

    _click(at, "⚙️ 관리자")
    _input(at, "관리자 비밀번호").set_value(TEST_ADMIN_PASSWORD)
    _click(at, "로그인")

    assert at.session_state["admin_authed"] is True
    rendered = " ".join(element.value for element in at.markdown)
    in_table = "삭제될 글" in rendered or (
        len(at.dataframe) > 0 and "삭제될 글" in str(at.dataframe[0].value)
    )
    assert in_table

    at.checkbox(key=f"admin_del_ok_{post_id}").check().run()
    _click(at, "삭제")
    assert board_db.get_post(post_id) is None


def test_sidebar_holds_only_board_selector(at: AppTest) -> None:
    assert [item.label for item in at.sidebar.radio] == ["게시판"]
    assert [item.label for item in at.sidebar.button] == ["⚙️ 관리자"]
    assert not at.sidebar.text_input
    assert not at.sidebar.selectbox

    assert [item.label for item in at.text_input] == ["검색"]
    assert [item.label for item in at.selectbox] == ["정렬", "페이지당"]


def test_board_switch_shows_only_selected_board(at: AppTest) -> None:
    board_db.create_post(
        board="family",
        category="자유",
        title="가족 글",
        author="가족",
        content="내용",
        password="1234",
    )
    board_db.create_post(
        board="study",
        category="정보",
        title="공부 글",
        author="학생",
        content="내용",
        password="1234",
    )
    at.run()

    labels = [button.label for button in at.button]
    assert any(label.startswith("가족 글") for label in labels)
    assert not any(label.startswith("공부 글") for label in labels)

    at.radio[0].set_value(board_db.BOARDS["study"]).run()

    assert at.session_state["board"] == "study"
    labels = [button.label for button in at.button]
    assert any(label.startswith("공부 글") for label in labels)
    assert not any(label.startswith("가족 글") for label in labels)


def test_new_post_goes_to_selected_board(at: AppTest) -> None:
    at.radio[0].set_value(board_db.BOARDS["study"]).run()
    _click(at, "새글")

    _input(at, "제목").set_value("공부 게시판 새 글")
    _input(at, "작성자").set_value("학생")
    _input(at, "비밀번호").set_value("1234")
    at.text_area[0].set_value("본문입니다.")
    _click(at, "등록하기")

    post = board_db.get_post(int(at.session_state["post_id"]))
    assert post is not None
    assert post["board"] == "study"


def test_board_switch_clears_search_box(at: AppTest) -> None:
    at.text_input(key="list_search").set_value("가족").run()
    assert at.session_state["list_search"] == "가족"

    at.radio[0].set_value(board_db.BOARDS["study"]).run()

    assert at.session_state["list_search"] == ""
    assert at.text_input(key="list_search").value == ""


def test_comment_form_adds_comment(at: AppTest) -> None:
    post_id = board_db.create_post(
        category="자유",
        title="댓글 테스트",
        author="작성자",
        content="내용",
        password="1234",
    )
    at.session_state["route"] = "detail"
    at.session_state["post_id"] = post_id
    at.run()

    _input_by_key(at, f"c_author_{post_id}").set_value("댓글러")
    _input_by_key(at, f"c_pw_{post_id}").set_value("1234")
    at.text_area[0].set_value("좋은 글이네요")
    _click(at, "댓글 등록")

    comments = board_db.list_comments(post_id)
    assert len(comments) == 1
    assert comments[0]["content"] == "좋은 글이네요"
