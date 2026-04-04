#!/bin/bash
# run.command
# system.config를 읽어서 server.py를 실행합니다.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/system.config"

echo "=============================="
echo "  Millestone 서버 시작"
echo "=============================="

# system.config 존재 확인
if [ ! -f "$CONFIG_FILE" ]; then
    echo "[오류] system.config 파일이 없습니다."
    echo "먼저 install_python.command 를 실행하세요."
    echo ""
    read -p "창을 닫으려면 Enter 키를 누르세요..."
    exit 1
fi

# system.config 읽기 (공백 경로 대응: grep으로 값만 추출)
PYTHON_BIN=$(grep '^PYTHON_BIN=' "$CONFIG_FILE" | cut -d'=' -f2-)

# Python 실행 파일 확인
if [ -z "$PYTHON_BIN" ] || [ ! -f "$PYTHON_BIN" ]; then
    echo "[오류] Python 실행 파일을 찾을 수 없습니다: $PYTHON_BIN"
    echo "install_python.command 를 다시 실행하세요."
    echo ""
    read -p "창을 닫으려면 Enter 키를 누르세요..."
    exit 1
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
