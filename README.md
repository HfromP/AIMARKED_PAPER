# Millestone

AI 프롬프트를 체계적으로 관리하는 워크스페이스 툴.

Workspace → Project → Milestone → Idea → Task 계층으로 작업을 구조화하고,
AI를 연결해 Task별 프롬프트를 자동 생성·실행·저장합니다.

**지원 언어**: 한국어 · English · Tiếng Việt

---

## 시스템 요구사항

| 항목 | 요구사항 |
|------|----------|
| OS | macOS 10.15+ 또는 Windows 10+ |
| 인터넷 | Python 초기 설치 시 필요 |
| AI | Claude API / OpenAI / Gemini API / Claude CLI / Gemini CLI 중 하나 |

---

## 설치 및 실행

### macOS

1. `apps/run.command` 더블클릭
2. 브라우저에서 온보딩 화면이 열립니다
3. 온보딩 안내에 따라 Python 환경 설치 → AI 연결 완료

> 처음 실행 시 macOS 보안 경고가 뜰 수 있습니다.
> 시스템 환경설정 → 개인 정보 보호 및 보안 → "확인 없이 열기" 를 눌러주세요.

### Windows

1. `apps/run.bat` 더블클릭
2. 브라우저에서 온보딩 화면이 열립니다
3. 온보딩 안내에 따라 Python 환경 설치 → AI 연결 완료

---

## AI 설정

온보딩 또는 설정 페이지(⚙️)에서 AI 프로바이더를 선택합니다.

| 프로바이더 | 필요한 것 | 비고 |
|-----------|-----------|------|
| Claude API | Anthropic API 키 | [console.anthropic.com](https://console.anthropic.com) |
| OpenAI | OpenAI API 키 | [platform.openai.com](https://platform.openai.com) |
| Gemini API | Google API 키 | [aistudio.google.com](https://aistudio.google.com) |
| Claude CLI | Claude CLI 설치 | `npm install -g @anthropic-ai/claude-code` |
| Gemini CLI | Gemini CLI 설치 | `npm install -g @google/gemini-cli` |

API 타입 선택 시: 설정 페이지에서 **패키지 설치** → **API 키 입력** → 저장

---

## 데이터 구조

```
Workspace
├── name
├── description
└── projects[]
     └── Project
          ├── name
          ├── description
          ├── outputPath          결과물 저장 위치 (경로 또는 URL)
          └── milestones[]
               └── Milestone
                    ├── name
                    ├── description
                    ├── status      하위 Idea 분포에 따라 자동 산출
                    └── ideas[]
                         └── Idea
                              ├── title
                              ├── description
                              ├── status      하위 Task 분포에 따라 자동 산출
                              └── tasks[]
                                   └── Task
                                        ├── name
                                        ├── importance    1(낮음) · 2(보통) · 3(높음)
                                        ├── status        아래 Status 참고
                                        └── prompts[]
                                             └── Prompt
                                                  ├── message
                                                  └── score    1(따봉) · 0(없음) · -1(싫어요)
```

---

## Status

| 값 | 의미 |
|----|------|
| `idea` | 아이디어 단계 |
| `pending` | 대기 |
| `in_progress` | 진행 중 |
| `done` | 완료 |
| `on_hold` | 보류 |
| `error` | 오류 |

### Idea Status 산출 규칙

| 조건 | Idea Status |
|------|-------------|
| Task 없음 | `idea` |
| `error` Task가 하나라도 있음 | `error` |
| 전부 `done` | `done` |
| 전부 `on_hold` | `on_hold` |
| 전부 `idea` | `idea` |
| 전부 `pending` | `pending` |
| `done` + `on_hold` 만 섞임 | `on_hold` |
| 그 외 혼합 | `in_progress` |
