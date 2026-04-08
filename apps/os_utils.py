import os
import platform
import subprocess

from data import PORT


def _get_my_tty():
    if platform.system() == 'Windows':
        return None  # Windows는 TTY 개념 없음, _close_terminal에서 WM_CLOSE 사용
    try:
        return os.ttyname(0)
    except Exception:
        return None


def _close_terminal(tty):
    """현재 터미널(Terminal / iTerm2 / cmd.exe) 창을 닫는다."""
    if platform.system() == 'Windows':
        try:
            import ctypes
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd:
                # WM_CLOSE(0x0010)를 현재 콘솔 창에 전송
                ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)
        except Exception:
            pass
        return

    # macOS — 기존 코드
    if not tty:
        return
    script = f'''
set myTTY to "{tty}"
try
    tell application "Terminal"
        repeat with w in windows
            repeat with t in tabs of w
                if tty of t is myTTY then
                    close w
                    return
                end if
            end repeat
        end repeat
    end tell
end try
try
    tell application "iTerm2"
        repeat with w in windows
            repeat with tb in tabs of w
                repeat with s in sessions of tb
                    if tty of s is myTTY then
                        tell w to close
                        return
                    end if
                end repeat
            end repeat
        end repeat
    end tell
end try
'''
    subprocess.Popen(['osascript', '-e', script])


def _close_browser_tab():
    """브라우저에서 localhost:PORT 탭을 닫는다. (macOS의 Chrome / Safari / Arc 지원)"""
    if platform.system() == 'Windows':
        # Windows에서는 메인 윈도우 제목 매칭으로 CloseMainWindow()를 호출하면
        # 해당 탭이 아닌 전체 브라우저 창(다른 탭 포함)을 닫을 수 있으므로
        # 자동 종료를 시도하지 않는다.
        return

    # macOS — 기존 osascript 코드
    script = f'''
set theURL to "http://localhost:{PORT}/"
try
    tell application "Google Chrome"
        if it is running then
            repeat with w in windows
                repeat with t in tabs of w
                    if URL of t starts with theURL then close t
                end repeat
            end repeat
        end if
    end tell
end try
try
    tell application "Safari"
        if it is running then
            repeat with w in windows
                repeat with t in tabs of w
                    if URL of t starts with theURL then close t
                end repeat
            end repeat
        end if
    end tell
end try
try
    tell application "Arc"
        if it is running then
            repeat with w in windows
                repeat with t in tabs of w
                    if URL of t starts with theURL then close t
                end repeat
            end repeat
        end if
    end tell
end try
'''
    try:
        subprocess.Popen(['osascript', '-e', script])
    except Exception:
        pass
