#!/bin/bash
# run.command
# system.config를 읽어서 server.py를 실행합니다.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/system.config"

echo "=============================="
echo "  Millestone 서버 시작"
echo "=============================="

# system.config에서 로컬 Python 경로 읽기
PYTHON_BIN=""
if [ -f "$CONFIG_FILE" ]; then
    PYTHON_BIN=$(grep '^PYTHON_BIN=' "$CONFIG_FILE" | cut -d'=' -f2-)
fi

# 로컬 Python 없으면 시스템 Python으로 폴백
if [ -z "$PYTHON_BIN" ] || [ ! -f "$PYTHON_BIN" ]; then
    PYTHON_BIN=$(which python3 2>/dev/null || which python 2>/dev/null)
    if [ -z "$PYTHON_BIN" ]; then
        echo "[오류] Python을 찾을 수 없습니다. Python 3를 설치해주세요."
        read -p "창을 닫으려면 Enter 키를 누르세요..."
        exit 1
    fi
    echo "[안내] 로컬 Python 환경이 없습니다. 시스템 Python으로 서버를 시작합니다."
    echo "       브라우저에서 온보딩 화면을 통해 환경을 설치해주세요."
    echo ""
fi

SERVER_PY="$SCRIPT_DIR/server.py"

if [ ! -f "$SERVER_PY" ]; then
    echo "[오류] server.py 파일을 찾을 수 없습니다: $SERVER_PY"
    read -p "창을 닫으려면 Enter 키를 누르세요..."
    exit 1
fi

echo "Python : $PYTHON_BIN"
echo "서버   : $SERVER_PY"
echo ""
echo "서버 주소: http://localhost:5500/main.html"
echo "종료하려면 Ctrl+C 를 누르세요."
echo "=============================="
echo ""

"$PYTHON_BIN" "$SERVER_PY"
