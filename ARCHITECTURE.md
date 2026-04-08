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
│   ├── server.py               # HTTP 서버: 정적 파일 서빙(port 5500) + REST API + AI 브리지
│   │                           #   GET  /api/workspaces           → data.json 반환
│   │                           #   PUT  /api/workspaces           → data.json 저장
│   │                           #   GET  /api/settings             → settings.config 반환
│   │                           #   PUT  /api/settings             → settings.config 저장 (부분 병합)
│   │                           #   GET  /api/system-status        → python_installed, ai_connected, os 반환
│   │                           #   POST /api/install-python       → install_python 스크립트 실행
│   │                           #   POST /api/install-package      → pip install (provider별 패키지)
│   │                           #   POST /api/ideas/{id}/run       → call_ai() → tasks 생성
│   │                           #   GET  /api/ideas/{id}/prompt    → AI 호출 없이 프롬프트 텍스트만 반환
│   │                           #   call_ai(): ai_provider에 따라 OpenAI/Anthropic API/Gemini API/Claude CLI/Gemini CLI/Ollama CLI 분기
│   ├── data.json               # 데이터 영속 파일 (workspaces 배열)
│   └── settings.config         # 앱 설정 (JSON): language, theme, ai_provider, api_keys{openai,anthropic,gemini}, ollama_model
│       # data.json 스키마: workspaces[].color, projects[].color, milestones[].color, ideas[].color (색상 태그)
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
| `#breadcrumb` | nav 하단 | 현재 계층 경로 표시 (클릭으로 상위 이동) |
| `#ws-grid` / `#proj-grid` / `#milestone-grid` / `#idea-grid` | main | 계층 탐색 카드 그리드 (드래그앤드롭 정렬 지원) |
| `btn-run` | idea 카드 | POST /api/ideas/{id}/run 호출 → Task 자동 생성 |
| `btn-preview` | idea 카드 | GET /api/ideas/{id}/prompt → AI 프롬프트 미리보기 모달 |
| `#prompt-preview-modal` | main.html | AI에 전달될 시스템/유저 프롬프트 텍스트 표시 |
| `#ai-nudge-banner` | nav 하단 | AI 미연결 시 넛지 배너 (onboarding.html 링크) |
| 색상 태그 `.color-dot-btn` | 카드 헤더 | 카드별 프리셋 색상 태그 (좌측 보더 색상 반영) |
| 진행률 바 `.progress-bar-track` | 카드 하단 | done 태스크 비율 기반 진행률 시각화 |
| 인라인 이름 편집 | 카드 이름 더블클릭 | 모달 없이 이름 직접 편집 |
| Undo 토스트 | 삭제 직후 | 3초 지연 삭제 + 취소 버튼 |
| 키보드 단축키 | 전역 keydown | Esc: 뒤로가기, N: 새 항목 추가 |
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
