#!/bin/bash
# install_python.command
# apps/dependencies/local_python/ 에 Python을 설치합니다.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# install_python.command 위치: apps/Installations/
# PYTHON_DIR → apps/dependencies/local_python
# SERVER_DIR → apps/
PYTHON_DIR="$(cd "$SCRIPT_DIR/../dependencies" && pwd)/local_python"
SERVER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG_FILE="$SERVER_DIR/system.config"

echo "=============================="
echo "  Python 로컬 설치 시작"
echo "=============================="
echo "설치 경로: $PYTHON_DIR"
echo ""

# 이미 설치되어 있으면 스킵
if [ -f "$PYTHON_DIR/bin/python3" ]; then
    echo "[이미 설치됨] $PYTHON_DIR/bin/python3"
    printf 'PYTHON_BIN=%s\nSERVER_DIR=%s\n' "$PYTHON_DIR/bin/python3" "$SERVER_DIR" > "$CONFIG_FILE"
    echo ""
    echo "system.config 업데이트 완료: $CONFIG_FILE"
    echo ""
    read -p "계속하려면 Enter 키를 누르세요..."
    exit 0
fi

# CPU 아키텍처 감지
ARCH=$(uname -m)
if [ "$ARCH" = "arm64" ]; then
    PY_ARCH="aarch64-apple-darwin"
else
    PY_ARCH="x86_64-apple-darwin"
fi

echo "[1/4] 최신 Python 버전 확인 중..."

RELEASE_URL=$(curl -s "https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest" \
    | grep "browser_download_url" \
    | grep "${PY_ARCH}-install_only.tar.gz" \
    | grep "cpython-3.12" \
    | head -1 \
    | cut -d '"' -f 4)

if [ -z "$RELEASE_URL" ]; then
    echo "[오류] 다운로드 URL을 찾을 수 없습니다. 네트워크 연결을 확인하세요."
    read -p "계속하려면 Enter 키를 누르세요..."
    exit 1
fi

FILENAME=$(basename "$RELEASE_URL")
echo "  → $FILENAME"
echo ""

echo "[2/4] 다운로드 중..."
TMPFILE="$SCRIPT_DIR/$FILENAME"
curl -L -o "$TMPFILE" "$RELEASE_URL"

if [ $? -ne 0 ]; then
    echo "[오류] 다운로드 실패"
    read -p "계속하려면 Enter 키를 누르세요..."
    exit 1
fi
echo ""

echo "[3/4] 압축 해제 중..."
mkdir -p "$PYTHON_DIR"
tar -xzf "$TMPFILE" -C "$PYTHON_DIR" --strip-components=1
rm -f "$TMPFILE"

if [ ! -f "$PYTHON_DIR/bin/python3" ]; then
    echo "[오류] Python 실행 파일을 찾을 수 없습니다."
    read -p "계속하려면 Enter 키를 누르세요..."
    exit 1
fi

PYTHON_BIN="$PYTHON_DIR/bin/python3"
echo "  → Python 설치 위치: $PYTHON_BIN"
echo ""

echo "[4/4] system.config 생성 중..."
printf 'PYTHON_BIN=%s\nSERVER_DIR=%s\n' "$PYTHON_BIN" "$SERVER_DIR" > "$CONFIG_FILE"

echo "  → $CONFIG_FILE 생성 완료"
echo ""

echo "=============================="
"$PYTHON_BIN" --version
echo "설치 완료!"
echo "=============================="
echo ""
echo "이제 run.command 를 더블클릭해서 서버를 시작하세요."
echo ""
read -p "창을 닫으려면 Enter 키를 누르세요..."
