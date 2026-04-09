# GITRELEASE — GitHub 릴리즈 절차

> 향후 Claude Code 스킬로 변환 예정.
> 파일 목록은 프로젝트별 `GITRELEASE_LIST.md`에서 관리.

---

## Inputs (스킬 파라미터 후보)

| 파라미터 | 설명 | 예시 |
|---|---|---|
| `VERSION` | 릴리즈 버전 | `1.0.7` |
| `REPO` | GitHub 저장소 (`owner/repo`) | `HfromP/AIMARKED_PAPER` |
| `ZIP_ROOT` | zip 내부 루트 폴더명 | `Millestone` |
| `RELEASE_NOTES` | 릴리즈 노트 본문 (마크다운) | 아래 형식 참조 |
| 파일 목록 | include / exclude | `GITRELEASE_LIST.md` 참조 |

---

## Steps

### Step 1. 사전 확인

```bash
# 최근 태그 확인
git tag --sort=-version:refname | head -5

# 이전 릴리즈 이후 커밋 목록
git log v{PREV_VERSION}..develop --oneline

# 미커밋 변경 없는지 확인
git status
```

---

### Step 2. zip 생성

`GITRELEASE_LIST.md`의 include/exclude 목록을 기준으로 구성.

```bash
TMPDIR=$(mktemp -d)
ZIPROOT="$TMPDIR/{ZIP_ROOT}"
mkdir -p "$ZIPROOT/..."   # GITRELEASE_LIST.md 참조

# 파일 복사 (include 목록 기반)
cp <file> "$ZIPROOT/..."

# zip 생성
cd "$TMPDIR"
zip -r "{ZIP_ROOT}_v{VERSION}.zip" {ZIP_ROOT}
```

---

### Step 3. 태그 생성 & push

```bash
git tag -a v{VERSION} -m "v{VERSION}: 한 줄 요약"
git push origin v{VERSION}
```

---

### Step 4. GitHub 토큰 획득

```bash
TOKEN=$(security find-generic-password -s "gh:github.com" -w | base64 -d)
```

> `gh` CLI가 설치되어 있다면 대신 사용 가능.
> 토큰을 변수에 저장하고 이후 Step에서 재사용.

---

### Step 5. GitHub API — 릴리즈 생성

```python
import json, urllib.request

payload = json.dumps({
    "tag_name": "v{VERSION}",
    "name": "v{VERSION}",
    "body": RELEASE_NOTES,
    "draft": False,
    "prerelease": False
}).encode("utf-8")

req = urllib.request.Request(
    "https://api.github.com/repos/{REPO}/releases",
    data=payload,
    headers={
        "Authorization": f"token {TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/vnd.github.v3+json"
    },
    method="POST"
)
with urllib.request.urlopen(req) as resp:
    r = json.load(resp)
    release_id = r["id"]
```

> **422 에러 (릴리즈 이미 존재) 처리:**
> ```python
> # GET으로 기존 릴리즈 ID 조회
> req = urllib.request.Request(
>     "https://api.github.com/repos/{REPO}/releases/tags/v{VERSION}",
>     headers={"Authorization": f"token {TOKEN}", ...}
> )
> with urllib.request.urlopen(req) as resp:
>     release_id = json.load(resp)["id"]
> ```

---

### Step 6. GitHub API — zip asset 업로드

```python
with open("{ZIP_ROOT}_v{VERSION}.zip", "rb") as f:
    data = f.read()

upload_url = f"https://uploads.github.com/repos/{REPO}/releases/{release_id}/assets?name={ZIP_ROOT}_v{VERSION}.zip"

req = urllib.request.Request(
    upload_url,
    data=data,
    headers={
        "Authorization": f"token {TOKEN}",
        "Content-Type": "application/zip",
        "Accept": "application/vnd.github.v3+json"
    },
    method="POST"
)
with urllib.request.urlopen(req) as resp:
    r = json.load(resp)
    print("Download URL:", r["browser_download_url"])
```

---

### Step 7. GitHub API — 릴리즈 노트 수정 (선택)

```python
payload = json.dumps({"body": RELEASE_NOTES}).encode("utf-8")

req = urllib.request.Request(
    f"https://api.github.com/repos/{REPO}/releases/{release_id}",
    data=payload,
    headers={
        "Authorization": f"token {TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/vnd.github.v3+json"
    },
    method="PATCH"
)
with urllib.request.urlopen(req) as resp:
    r = json.load(resp)
    print("Release URL:", r["html_url"])
```

> **curl 대신 Python urllib을 사용하는 이유:**
> 릴리즈 노트에 줄바꿈·특수문자 포함 시 curl `-d` 처리에서 제어 문자 오류 발생.

---

## 릴리즈 노트 권장 형식

```markdown
## What's Changed

### UI 개선
- ...

### 버그 수정
- ...
```

---

## 릴리즈 확인

```
https://github.com/{REPO}/releases/tag/v{VERSION}
```
