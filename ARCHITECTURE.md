# ARCHITECTURE MAP
> AI 에이전트용 프로젝트 나침반. 구현 디테일 없이 역할과 인터페이스만 기술.
> 파일을 무작정 열지 말고 이 문서를 먼저 읽고 필요한 파일 1~2개만 타겟해서 접근할 것.

---

## 프로젝트 개요
- **이름**: AIMARKED_PAPER (Millestone)
- **형태**: 순수 HTML/CSS/JS 프론트엔드 (빌드 도구 없음)
- **진입점**: `main.html` — 앱의 유일한 HTML 파일

---

## 파일 구조 & 역할

```
/
├── apps/
│   ├── main.html               # SPA 진입점. 렌더링 전담, fetch로 Python API 호출
│   │                           #   로드 시 /api/system-status 확인 → ai_connected:false 이면 넛지 배너 표시
│   ├── onboarding.html         # 온보딩 페이지. Python 설치 → AI 연결 순서 안내
│   │                           #   언어 선택 (ko/en/vi), Step1: Python 설치, Step2: AI 설정
│   │                           #   main.html에서 ai_connected:false 시 redirect 진입
│   ├── settings.html           # 설정 페이지. 좌: 4개 아이콘 / 우: 나가기(X) → main.html
│   │                           #   AI 프로바이더별 패키지 설치 버튼 포함
│   ├── server.py               # HTTP 서버 진입점: 정적 파일 서빙(port 5500) + REST API 라우팅
│   │                           #   GET  /api/workspaces           → data.json 반환
│   │                           #   PUT  /api/workspaces           → data.json 저장
│   │                           #   GET  /api/settings             → settings.config 반환
│   │                           #   PUT  /api/settings             → settings.config 저장 (부분 병합)
│   │                           #   GET  /api/system-status        → python_installed, ai_connected, os 반환
│   │                           #   POST /api/install-python       → install_python 스크립트 실행
│   │                           #   POST /api/install-package      → pip install (provider별 패키지)
│   │                           #   POST /api/ideas/{id}/run       → call_ai() → tasks 생성
│   │                           #   import: data.py, ai.py, os_utils.py
│   ├── data.py                 # 데이터 레이어: 경로 상수(BASE_DIR, PORT, DATA_FILE, SETTINGS_FILE)
│   │                           #   read_data/write_data, read_settings/write_settings
│   │                           #   find_idea_context, find_task, find_task_context 등 탐색 헬퍼
│   ├── ai.py                   # AI 레이어: 6개 provider 분기(call_ai), 시스템 프롬프트 상수
│   │                           #   extract_json, _validate_*, _call_ai_with_retry
│   │                           #   CLAUDE_BIN 탐색, _ensure_packages
│   │                           #   import: data.py (read_settings, _TEXT_SUBPROCESS)
│   ├── os_utils.py             # OS/플랫폼 유틸: 터미널·브라우저 탭 닫기 (_close_terminal, _close_browser_tab)
│   │                           #   _get_my_tty (macOS/Linux TTY 탐색)
│   │                           #   import: data.py (PORT)
│   ├── data.json               # 데이터 영속 파일 (workspaces 배열)
│   └── settings.config         # 앱 설정 (JSON): language, theme, ai_provider, api_keys{openai,anthropic,gemini}, ollama_model
├── ARCHITECTURE.md             # (이 파일) 프로젝트 구조 나침반 — AI 전용
├── CLAUDE.md                   # Claude Code 행동 규칙 및 제약 조건
├── README.md                   # 프로젝트 소개
├── install_python.command      # [macOS] Python 로컬 설치 스크립트 (더블클릭 실행)
│                               #   → apps/dependencies/local_python/ 에 Python 설치
│                               #   → apps/system.config 생성 (Python 경로 기록)
├── run.command                 # [macOS] 서버 실행 스크립트 (더블클릭 실행)
│                               #   → apps/system.config 읽어 server.py 실행
├── apps/Installations/
│   └── install_python.bat      # [Windows] Python 로컬 설치 스크립트 (더블클릭 실행)
│                               #   → astral-sh/python-build-standalone 다운로드
│                               #   → apps/dependencies/local_python/ 에 Python 설치
│                               #   → apps/system.config 생성 (Python 경로 기록)
├── apps/run.bat                # [Windows] 서버 실행 스크립트 (더블클릭 실행)
│                               #   → apps/system.config 읽어 server.py 실행
└── local_python/               # (install_python.command 실행 후 생성) 로컬 Python 런타임
```

## 실행 방법
```
python3 apps/server.py
# → http://localhost:5500/main.html
```

---

## 현재 구현된 UI 모듈 (main.html 내부)

| 모듈 | 위치 | 역할 |
|------|------|------|
| `<nav>` | main.html | 상단 네비게이션 바 (좌: 로고 / 우: 아이콘) |
| `#theme-toggle` | nav 우측 | 다크/라이트 모드 토글 (달↔태양 아이콘) |
| `#settings-btn` | nav 우측 | settings.html 이동 |
| `.dark` class | body | 다크모드 상태 클래스 |
| `#ws-grid` / `#proj-grid` / `#milestone-grid` / `#idea-grid` | main | 계층 탐색 카드 그리드 |
| `btn-run` | idea 카드 | POST /api/ideas/{id}/run 호출 → Task 자동 생성 |
| `#ai-nudge-banner` | nav 하단 | AI 미연결 시 넛지 배너 (onboarding.html 링크) |
| onboarding.html | 별도 페이지 | Step1: Python 설치, Step2: AI 설정, 언어 선택 |

---

## 확장 예정 영역 (파일 추가 시 이 문서 업데이트)

새 파일이 추가될 때마다 아래 템플릿으로 이 문서에 등록:
```
| 파일명 | 역할 한 줄 요약 | 주요 export/인터페이스 |
```

---

## AI 작업 지침

- **탐색 순서**: 이 문서 → 해당 모듈 파일 (최대 2개)
- **금지**: 전체 파일 스캔, 불필요한 다중 파일 Read
- **수정 전**: 영향받는 모듈을 이 문서에서 먼저 확인
