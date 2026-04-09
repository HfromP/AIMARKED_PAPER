# GITRELEASE_LIST — Millestone 릴리즈 파일 목록

> 이 파일은 프로젝트 전용 설정입니다.
> 릴리즈 시 `GITRELEASE.md`의 Step 2에서 이 파일을 참조하여 zip을 구성합니다.
> **다음 릴리즈 때 포함/제외 목록이 바뀌었다면 이 파일만 수정하세요.**

---

## 프로젝트 설정

| 키 | 값 |
|---|---|
| `REPO` | `HfromP/AIMARKED_PAPER` |
| `ZIP_ROOT` | `Millestone` |

---

## Include (포함 파일)

```
LICENSE
README.md
apps/main.html
apps/onboarding.html
apps/settings.html
apps/server.py
apps/config.py
apps/data.py
apps/ai.py
apps/os_utils.py
apps/run.command
apps/run.bat
apps/Installations/install_python.command
apps/Installations/install_python.bat
```

---

## Exclude (제외 파일 / 디렉토리)

```
ARCHITECTURE.md
CLAUDE.md
GITRELEASE.md
GITRELEASE_LIST.md
.claude/
.claudeignore
.gitignore
.DS_Store
apps/data.json
apps/settings.config
apps/system.config
apps/dependencies/
apps/__pycache__/
```

---

_마지막 업데이트: v1.0.8_
