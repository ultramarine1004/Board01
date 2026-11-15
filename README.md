# 우리가족 게시판 (Streamlit + SQLite/Neon)

Python 만으로 띄우는 가족 게시판입니다. Streamlit UI, SQLite 또는
Postgres(Neon) 저장소, 비밀번호 기반 수정·삭제, 댓글, 검색, 페이지네이션,
사진 첨부, 관리자 모드를 포함합니다.

게시판은 세 개로 나뉘며 사이드바에서 고릅니다. 검색·정렬·페이지당 게시글은
목록 상단에서 조정합니다.

| 게시판 키 | 표시 이름 | 사진 첨부 |
| --- | --- | --- |
| `family` | 우리 가족 게시판 | O |
| `tips` | 알아두면 좋은 정보 | X |
| `study` | 공지사항 | X |

## 빠른 시작

```powershell
cd board
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

python -m streamlit run app.py
```

브라우저가 `http://localhost:8501` 로 열립니다.
샘플 데이터를 넣고 싶다면 실행 전에:

```powershell
python seed.py
```

`seed.py` 는 현재 설정된 저장소에 넣습니다. `DATABASE_URL`(또는
`.streamlit/secrets.toml` 의 `DATABASE_URL`)이 있으면 **Neon(Postgres)** 에,
없으면 로컬 `data/board.db` 에 저장합니다.

## 저장소 선택 (SQLite ↔ Neon)

우선순위는 다음과 같습니다.

1. `BOARD_DB_PATH` 환경변수 → 항상 SQLite 파일
2. `BOARD_DATABASE_URL` / `DATABASE_URL` 환경변수 → Postgres
3. `.streamlit/secrets.toml` 의 `DATABASE_URL` → Postgres
4. 위가 모두 없으면 `data/board.db` (SQLite)

```powershell
# Neon(Postgres) 사용: secrets.toml 또는 환경변수
$env:DATABASE_URL = "postgresql://...:...@...neon.tech/...?sslmode=require"

# 로컬 SQLite 를 강제로 사용 (DATABASE_URL 이 있어도)
$env:BOARD_DB_PATH = "data/board.db"
```

> 기존 로컬 `board.db` 의 글은 Neon 으로 **자동 이전되지 않습니다.**
> 저장소를 바꾸면 새 저장소는 비어 있는 상태로 시작합니다.
> 관리자 → **JSON 백업** 으로 데이터를 내려받아 보관하세요.

### SQLite → Neon 데이터 이전

기존 로컬 글을 Neon 으로 옮기려면 이전 스크립트를 사용합니다.
기본은 **미리보기(쓰기 없음)** 이며, 결과를 확인한 뒤 `--apply` 로 실행하세요.

```powershell
# 1) 미리보기: 어떤 글이 복사/건너뜀 되는지 확인 (실제 저장 안 함)
python migrate_sqlite_to_postgres.py --source data/board.db

# 2) 실제 이전
python migrate_sqlite_to_postgres.py --source data/board.db --apply
```

- 대상은 `DATABASE_URL`(환경변수 또는 `secrets.toml`)의 Postgres 입니다.
- 같은 `(board, title, author, created_at)` 게시글은 건너뛰므로 여러 번 실행해도
  중복이 생기지 않습니다(멱등).
- 댓글과 이미지 **메타데이터**도 함께 옮기지만, 이미지 원본 파일은 복사하지
  않습니다. `data/uploads/` 폴더를 서버에 함께 올리거나 객체 저장소로 옮기세요.

## 기능

| 영역 | 내용 |
| --- | --- |
| 게시판 | 3개 게시판(우리 가족 게시판 / 알아두면 좋은 정보 / 공지사항), 사이드바에서 선택 |
| 목록 | 검색(제목·내용·작성자)·정렬(최신/조회/댓글)·페이지당 게시글, `새글` 버튼, 페이지네이션, 상단 고정 |
| 상세 | 조회수(세션당 1회), 댓글 목록·작성·삭제, 수정/삭제 진입 |
| 작성 | 카테고리 4종(자유/질문/정보/공지), 제목·작성자·비밀번호·본문 검증 |
| 사진 | `family` 게시판만, 게시글당 10장·장당 5MB, 긴 변 1920px 축소, EXIF(촬영 위치) 제거, 썸네일 생성 |
| 보안 | 비밀번호는 PBKDF2-HMAC-SHA256(200,000회, 16바이트 salt) 해시로만 저장, 모든 SQL 파라미터 바인딩 |
| 관리자 | 비밀번호 로그인, 전체 게시글 표, 비밀번호 없이 삭제(확인 체크), 상단 고정 토글, SQLite/JSON 백업 |
| 시간 | 저장은 UTC, 화면 표시와 "오늘" 통계는 KST 기준 |

레이아웃: 사이드바 300px + 본문 최대 1024px 프레임을 화면 가운데에 배치합니다.
화면이 좁으면 본문 폭이 줄어들고, 프레임 바깥 영역은 크림색(`#FFF8F1`)입니다.

기존 SQLite DB(`board.db`)는 첫 실행 시 `posts.board` 컬럼이 자동 추가되며,
기존 글은 `우리 가족 게시판` 게시판으로 들어갑니다.

## 사진 저장 위치

사진 원본과 썸네일은 DB 가 아니라 `data/uploads/` 폴더에 저장됩니다.
DB 에는 파일 이름·크기·해상도 같은 메타데이터만 들어갑니다.

무료 호스팅(Streamlit Community Cloud, Render 등)의 파일 시스템은
**휘발성**이므로, 재시작하면 업로드한 사진 파일이 사라질 수 있습니다.
사진을 오래 보관하려면 S3 호환 객체 저장소(예: Neon Object Storage)로
옮기는 것을 권장합니다.

## 설정

관리자 비밀번호는 `.streamlit/secrets.toml` 에서 설정합니다(없으면 `admin123`).

```toml
# board/.streamlit/secrets.toml  (git 에 커밋하지 마세요)
admin_password = "여기에-강한-비밀번호"
DATABASE_URL = "postgresql://...:...@...neon.tech/...?sslmode=require"
```

기본값 `admin123` 을 그대로 쓰면 관리자 화면에 경고가 표시됩니다.
배포 전에 반드시 변경하세요. 비밀번호는 한글도 사용할 수 있습니다.

DB 경로를 바꾸려면 환경변수를 사용합니다.

```powershell
$env:BOARD_DB_PATH = "D:\data\board.db"
```

기본 SQLite 경로는 `board/data/board.db` 입니다.

## 테스트

```powershell
python -m pytest tests -q
```

현재 테스트: `test_db.py` 31개, `test_images.py` 12개,
`test_app_smoke.py` 10개 (총 53개).

## 백업과 배포

관리자 화면에서 내려받을 수 있는 백업:

- **JSON 백업**: 게시글·댓글·이미지 메타데이터 전체(비밀번호 해시 포함).
  SQLite/Neon 어느 모드에서도 사용할 수 있습니다.
- **SQLite 백업**: SQLite 모드에서만 표시됩니다. Neon 모드에서는 실제
  데이터가 아닌 로컬 파일이므로 버튼을 숨깁니다.

Neon(Postgres) 데이터는 Neon 콘솔의 백업/복원 기능이나 `pg_dump` 로도
보관할 수 있습니다. 사진 원본 파일은 JSON 백업에 포함되지 않으므로
`data/uploads/` 또는 객체 저장소를 별도로 백업해야 합니다.

### Streamlit Community Cloud

1. 이 폴더(`board/`)를 GitHub 저장소에 push 합니다.
2. <https://share.streamlit.io> 에서 GitHub 로그인 → **New app**.
3. Repository / Branch / **Main file path** 를 `app.py` 로 지정합니다
   (저장소 루트가 `board/` 인 경우). `requirements.txt` 도 같은 폴더에 있어야 합니다.
4. **Advanced settings → Secrets** 에 `admin_password` 와 `DATABASE_URL` 을 붙여넣습니다.
5. **Deploy**. 이후 `git push` 마다 자동 재배포됩니다.

무료 호스팅은 컨테이너 파일 시스템이 휘발성입니다. Neon 을 쓰면 게시글은
유지되지만, `data/uploads/` 의 사진 파일은 재배포 시 사라질 수 있습니다.

## 구조

```
board/
  app.py                  # Streamlit UI (진입점)
  db.py                   # SQLite/Postgres 데이터 접근 계층 (streamlit 비의존)
  images.py               # 사진 검증·재인코딩·썸네일 (streamlit 비의존)
  seed.py                 # 샘플 데이터
  migrate_sqlite_to_postgres.py  # SQLite → Neon 이전 (기본 미리보기)
  requirements.txt
  .streamlit/config.toml  # 테마/서버 설정
  logos/                  # 사이드바 로고
  data/board.db           # SQLite 런타임 생성 (git 제외)
  data/uploads/           # 사진 원본/썸네일 (git 제외)
  tests/test_db.py        # DAL 단위 테스트 (31)
  tests/test_images.py    # 사진 처리 단위 테스트 (12)
  tests/test_app_smoke.py # AppTest 화면 시나리오 테스트 (10)
```
