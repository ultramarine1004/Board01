# 우리가족 게시판 (Streamlit + SQLite)

Python 만으로 5분 안에 띄우는 최소 게시판입니다. Streamlit UI, SQLite 저장소,
비밀번호 기반 수정·삭제, 댓글, 검색, 페이지네이션, 관리자 모드를 포함합니다.
게시판은 `우리 가족 사진` · `알아주면 좋은 정보팁` · `공부합시다` 세 개로 나뉘며,
사이드바에서 게시판만 고르고 검색·정렬·페이지당 게시글은 목록 상단에서 조정합니다.

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

## 기능

| 영역 | 내용 |
| --- | --- |
| 게시판 | 3개 게시판(우리 가족 사진 / 알아주면 좋은 정보팁 / 공부합시다), 사이드바에서 선택 |
| 목록 | 상단에 검색(제목·내용·작성자)·정렬(최신/조회/댓글)·페이지당 게시글, 우측 상단 `새글` 버튼, 페이지네이션, 상단 고정 |
| 상세 | 조회수(세션당 1회), 댓글 목록·작성·삭제, 수정/삭제 진입 |
| 작성 | 카테고리 4종(자유/질문/정보/공지), 제목·작성자·비밀번호·본문 검증, 현재 게시판으로 저장 |
| 보안 | 비밀번호는 PBKDF2-HMAC-SHA256(200,000회, 16바이트 salt) 해시로만 저장, 모든 SQL 파라미터 바인딩 |
| 관리자 | 비밀번호 로그인, 게시판 포함 전체 목록, 비밀번호 없이 삭제, 상단 고정 토글, SQLite 백업 다운로드 |

레이아웃: 본문은 화면 왼쪽 절반(사이드바 제외 폭의 50%)만 사용하고, 남는 오른쪽
영역은 사이드바와 같은 크림색(`#FFF8F1`)으로 채웁니다.

기존 DB(`board.db`)는 첫 실행 시 `posts.board` 컬럼이 자동 추가되며, 기존 글은
`우리 가족 사진` 게시판으로 들어갑니다.

## 설정

관리자 비밀번호는 `.streamlit/secrets.toml` 에서 설정합니다(없으면 `admin123`).

```toml
# board/.streamlit/secrets.toml  (git 에 커밋하지 마세요)
admin_password = "여기에-강한-비밀번호"
```

DB 경로를 바꾸려면 환경변수를 사용합니다.

```powershell
$env:BOARD_DB_PATH = "D:\data\board.db"
```

기본 경로는 `board/data/board.db` 입니다.

## 테스트

```powershell
python -m pytest tests -q
```

## 배포 시 반드시 알아야 할 것

무료 호스팅(Streamlit Community Cloud, Render, Hugging Face 등)은 **컨테이너
파일 시스템이 휘발성**입니다. 즉 `board.db` 에 쌓은 글이 재시작·재배포 시 사라질 수
있습니다. Streamlit 공식 문서도 "Community Cloud 앱은 로컬 파일 저장의 영속성을
보장하지 않는다"고 명시합니다.

완화 방법 3단계:

1. **관리자 → 데이터 백업** 에서 `board.db` 를 주기적으로 내려받아 보관합니다.
2. 글이 중요해지면 무료 Postgres(Neon, Supabase)로 이전합니다. `db.py` 의
   `connect()` 만 교체하면 UI 코드는 그대로 쓸 수 있게 설계했습니다.
3. 상시 운영이 필요하면 유료 볼륨/유료 플랜으로 이동합니다.

## 배포 (Streamlit Community Cloud)

1. 이 폴더(`board/`)를 GitHub 저장소에 push 합니다.
2. <https://share.streamlit.io> 에서 GitHub 로그인 → **New app**.
3. Repository / Branch / **Main file path** 를 `app.py` 로 지정합니다
   (저장소 루트가 `board/` 인 경우). `requirements.txt` 도 같은 폴더에 있어야 합니다.
4. **Advanced settings → Secrets** 에 `admin_password = "..."` 를 붙여넣습니다.
5. **Deploy**. 이후 `git push` 마다 자동 재배포됩니다.

자세한 무료 호스팅 비교는 `docs/board-hosting-report.md`, 제품 기획은
`docs/board-service-plan.md` 를 참고하세요.

## 구조

```
board/
  app.py                 # Streamlit UI (진입점)
  db.py                  # SQLite 데이터 접근 계층 (streamlit 비의존)
  seed.py                # 샘플 데이터
  requirements.txt
  .streamlit/config.toml # 테마/서버 설정
  logos/hayun-story-logo.svg  # 사이드바 로고 (배포 시 함께 push)
  data/board.db          # 런타임 생성 (git 제외)
  tests/test_db.py       # DAL 단위 테스트 (26)
  tests/test_app_smoke.py# AppTest 화면 시나리오 테스트 (9)
```
