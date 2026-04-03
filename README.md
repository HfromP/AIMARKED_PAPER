# Millestone

AI 프롬프트를 체계적으로 관리하는 워크스페이스 툴.

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
          ├── outputPath        결과물 저장 위치 (경로 또는 URL)
          └── ideas[]
               └── Idea
                    ├── title
                    ├── description
                    ├── status    하위 Task 분포에 따라 자동 산출
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

Idea의 status는 하위 Task 목록을 기준으로 자동 계산됩니다.

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
