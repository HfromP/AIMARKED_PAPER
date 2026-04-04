#!/usr/bin/env python3
import json
import os
import re
import signal
import subprocess
import threading
import time
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

PORT = 5500
BASE_DIR = Path(__file__).parent          # apps/
DATA_FILE = BASE_DIR / 'data.json'
CLAUDE_BIN = Path.home() / '.local' / 'bin' / 'claude'
_server_instance = None
_last_heartbeat = None
HEARTBEAT_TIMEOUT = 10  # 초: 마지막 heartbeat 후 이 시간이 지나면 종료
STARTUP_GRACE = 25      # 초: 서버 시작 직후 watchdog 대기 시간


def read_data():
    if not DATA_FILE.exists():
        return {'workspaces': []}
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def write_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def extract_json(text):
    """CLI 응답에서 JSON 배열 추출. 코드블록 안팎 모두 처리."""
    # ```json ... ``` 블록 우선 시도
    m = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    # 첫 번째 [ ... ] 추출
    m = re.search(r'(\[.*\])', text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    raise ValueError('JSON 배열을 찾을 수 없습니다.')


def find_idea(data, idea_id):
    """data 구조에서 idea_id에 해당하는 idea dict 반환."""
    for ws in data.get('workspaces', []):
        for proj in ws.get('projects', []):
            for ms in proj.get('milestones', []):
                for idea in ms.get('ideas', []):
                    if idea.get('id') == idea_id:
                        return idea
    return None


def find_task(data, task_id):
    """data 구조에서 task_id에 해당하는 (idea, task) 반환."""
    for ws in data.get('workspaces', []):
        for proj in ws.get('projects', []):
            for ms in proj.get('milestones', []):
                for idea in ms.get('ideas', []):
                    for task in idea.get('tasks', []):
                        if task.get('id') == task_id:
                            return idea, task
    return None, None


def find_task_context(data, task_id):
    """data 구조에서 task_id에 해당하는 (workspace, project, idea, task) 반환."""
    for ws in data.get('workspaces', []):
        for proj in ws.get('projects', []):
            for ms in proj.get('milestones', []):
                for idea in ms.get('ideas', []):
                    for task in idea.get('tasks', []):
                        if task.get('id') == task_id:
                            return ws, proj, idea, task
    return None, None, None, None


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def log_message(self, format, *args):
        print(f'[{self.address_string()}] {format % args}')

    # ── 공통 헬퍼 ──────────────────────────────────────────

    def _send_json(self, status, obj):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get('Content-Length', 0))
        return self.rfile.read(length)

    # ── 라우팅 ─────────────────────────────────────────────

    def do_GET(self):
        if self.path == '/api/workspaces':
            self._handle_get_workspaces()
        elif self.path == '/api/claude-check':
            self._handle_claude_check()
        elif self.path == '/api/gemini-check':
            self._handle_gemini_check()
        elif self.path == '/api/browse-folder':
            self._handle_browse_folder()
        else:
            super().do_GET()

    def do_PUT(self):
        if self.path == '/api/workspaces':
            self._handle_put_workspaces()
        else:
            self._send_json(404, {'error': 'Not found'})

    def do_POST(self):
        m = re.fullmatch(r'/api/ideas/([^/]+)/run', self.path)
        if m:
            self._handle_run_idea(m.group(1))
            return
        m = re.fullmatch(r'/api/tasks/([^/]+)/prompt', self.path)
        if m:
            self._handle_task_prompt(m.group(1))
            return
        m = re.fullmatch(r'/api/tasks/([^/]+)/execute', self.path)
        if m:
            self._handle_task_execute(m.group(1))
            return
        if self.path == '/api/reveal-folder':
            self._handle_reveal_folder()
            return
        if self.path == '/api/classify-message':
            self._handle_classify_message()
            return
        if self.path == '/api/refine-prompt':
            self._handle_refine_prompt()
            return
        if self.path == '/api/shutdown':
            self._handle_shutdown()
            return
        if self.path == '/api/heartbeat':
            self._handle_heartbeat()
            return
        self._send_json(404, {'error': 'Not found'})

    # ── 핸들러 구현 ────────────────────────────────────────

    def _handle_shutdown(self):
        self._send_json(200, {'ok': True})
        threading.Thread(target=_server_instance.shutdown, daemon=True).start()

    def _handle_heartbeat(self):
        global _last_heartbeat
        _last_heartbeat = time.time()
        self._send_json(200, {'ok': True})

    def _handle_browse_folder(self):
        try:
            result = subprocess.run(
                ['osascript', '-e', 'POSIX path of (choose folder)'],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode == 0:
                path = result.stdout.strip()
                self._send_json(200, {'ok': True, 'path': path})
            else:
                # 취소한 경우 returncode != 0
                self._send_json(200, {'ok': False, 'cancelled': True})
        except subprocess.TimeoutExpired:
            self._send_json(200, {'ok': False, 'error': '응답 시간 초과'})
        except Exception as e:
            self._send_json(500, {'error': str(e)})

    def _handle_gemini_check(self):
        try:
            result = subprocess.run(
                ['gemini', '--version'],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                version = result.stdout.strip() or result.stderr.strip()
                self._send_json(200, {'ok': True, 'version': version})
            else:
                self._send_json(200, {'ok': False, 'error': result.stderr.strip()})
        except FileNotFoundError:
            self._send_json(200, {'ok': False, 'error': 'Gemini CLI를 찾을 수 없습니다'})
        except subprocess.TimeoutExpired:
            self._send_json(200, {'ok': False, 'error': '응답 시간 초과'})
        except Exception as e:
            self._send_json(200, {'ok': False, 'error': str(e)})

    def _handle_claude_check(self):
        try:
            result = subprocess.run(
                [str(CLAUDE_BIN), '--version'],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                version = result.stdout.strip() or result.stderr.strip()
                self._send_json(200, {'ok': True, 'version': version})
            else:
                self._send_json(200, {'ok': False, 'error': result.stderr.strip()})
        except FileNotFoundError:
            self._send_json(200, {'ok': False, 'error': 'Claude CLI를 찾을 수 없습니다'})
        except subprocess.TimeoutExpired:
            self._send_json(200, {'ok': False, 'error': '응답 시간 초과'})
        except Exception as e:
            self._send_json(200, {'ok': False, 'error': str(e)})

    def _handle_get_workspaces(self):
        self._send_json(200, read_data())

    def _handle_put_workspaces(self):
        try:
            body = self._read_body()
            incoming = json.loads(body)
            write_data(incoming)
            self._send_json(200, {'ok': True})
        except Exception as e:
            self._send_json(500, {'error': str(e)})

    def _handle_run_idea(self, idea_id):
        try:
            data = read_data()
            idea = find_idea(data, idea_id)
            if idea is None:
                self._send_json(404, {'error': f'idea {idea_id} not found'})
                return

            parts = []
            files = idea.get('files', [])
            if files:
                file_section = "\n\n".join(
                    f"[참고 파일: {f.get('name', '')}]\n{f.get('content', '')}"
                    for f in files[:3]
                )
                parts.append(f"다음 파일들을 참고해서 Task를 구성해줘:\n\n{file_section}")

            parts.append(
                f"아이디어 제목: {idea.get('title', '')}\n"
                f"아이디어 설명: {idea.get('description', '')}\n\n"
                "위 아이디어를 구현하기 위한 구체적인 Task 목록을 JSON 배열로만 응답해줘.\n"
                "다른 설명 없이 JSON 배열만 출력해줘.\n"
                '각 Task는 {"name": "...", "importance": 1|2|3} 형태야. (1=낮음, 2=보통, 3=높음)'
            )
            prompt = "\n\n".join(parts)

            result = subprocess.run(
                [str(CLAUDE_BIN), '--print', '--output-format', 'text', prompt],
                capture_output=True, text=True, timeout=120
            )

            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or 'Claude CLI 오류')

            tasks = extract_json(result.stdout)

            # 기존 tasks에 추가 (id는 JS가 없으므로 timestamp 기반 생성)
            import time
            for i, t in enumerate(tasks):
                t['id'] = f'task_{int(time.time() * 1000)}_{i}'
                t['status'] = 'idea'
                t['prompts'] = []

            idea.setdefault('tasks', []).extend(tasks)
            write_data(data)
            self._send_json(200, idea)

        except subprocess.TimeoutExpired:
            self._send_json(500, {'error': 'Claude CLI 응답 시간 초과'})
        except Exception as e:
            self._send_json(500, {'error': str(e)})

    def _handle_task_prompt(self, task_id):
        try:
            body = json.loads(self._read_body()) if int(self.headers.get('Content-Length', 0)) else {}
            system_prompt = body.get('systemPrompt', '').strip()
            history = body.get('conversationHistory', [])

            data = read_data()
            idea, task = find_task(data, task_id)
            if task is None:
                self._send_json(404, {'error': f'task {task_id} not found'})
                return

            parts = []
            if system_prompt:
                parts.append(system_prompt)
            if history:
                parts.append("[이전 프롬프트 히스토리]\n" +
                             "\n".join(f"{i+1}. {h}" for i, h in enumerate(history)))
            parts.append(
                f"아이디어: {idea.get('title', '')}\n"
                f"아이디어 설명: {idea.get('description', '')}\n"
                f"Task 이름: {task.get('name', '')}\n\n"
                "위 Task를 수행하기 위한 가장 효과적인 AI 프롬프트를 하나 생성해줘.\n"
                "프롬프트 텍스트만 출력하고 다른 설명은 하지 마."
            )
            prompt = "\n\n".join(parts)

            result = subprocess.run(
                [str(CLAUDE_BIN), '--print', '--output-format', 'text', prompt],
                capture_output=True, text=True, timeout=60
            )

            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or 'Claude CLI 오류')

            self._send_json(200, {'ok': True, 'prompt': result.stdout.strip()})

        except subprocess.TimeoutExpired:
            self._send_json(500, {'error': 'Claude CLI 응답 시간 초과'})
        except Exception as e:
            self._send_json(500, {'error': str(e)})

    def _handle_task_execute(self, task_id):
        import time as _time
        try:
            body = json.loads(self._read_body())
            prompt_text = body.get('prompt', '')

            data = read_data()
            ws, proj, idea, task = find_task_context(data, task_id)
            if task is None:
                self._send_json(404, {'error': f'task {task_id} not found'})
                return

            # 파일명 안전 변환
            def safe_name(s, max_len=30):
                s = re.sub(r'[^\w\s가-힣-]', '', s).strip()
                return re.sub(r'\s+', '_', s)[:max_len] or 'untitled'

            output_path = proj.get('outputPath', '').strip()
            updated_output_path = None
            if not output_path:
                output_path = str(
                    BASE_DIR / 'default_directory'
                    / safe_name(ws.get('name', 'workspace'))
                    / safe_name(proj.get('name', 'project'))
                )
                proj['outputPath'] = output_path
                write_data(data)
                updated_output_path = output_path

            # Claude CLI 실행
            result = subprocess.run(
                [str(CLAUDE_BIN), '--print', '--output-format', 'text', prompt_text],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or 'Claude CLI 오류')

            content = result.stdout.strip()

            idea_dir   = safe_name(idea.get('title', 'idea'))
            task_dir   = safe_name(task.get('name', 'task'))
            timestamp  = _time.strftime('%Y%m%d_%H%M%S')
            first_line = content.split('\n')[0][:40].strip()
            short_title = safe_name(first_line) or 'result'
            filename = f'{timestamp}_{short_title}.md'

            folder_path = Path(output_path) / idea_dir / task_dir
            folder_path.mkdir(parents=True, exist_ok=True)
            file_path = folder_path / filename

            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(f'# {task.get("name", "")}\n\n')
                f.write(f'## 프롬프트\n\n{prompt_text}\n\n')
                f.write(f'## 결과\n\n{content}\n')

            resp = {
                'ok': True,
                'filePath': str(file_path),
                'folderPath': str(folder_path),
                'fileName': filename,
                'projectId': proj.get('id', ''),
            }
            if updated_output_path:
                resp['updatedOutputPath'] = updated_output_path
            self._send_json(200, resp)

        except subprocess.TimeoutExpired:
            self._send_json(500, {'error': 'Claude CLI 응답 시간 초과'})
        except Exception as e:
            self._send_json(500, {'error': str(e)})

    def _handle_reveal_folder(self):
        try:
            body = json.loads(self._read_body())
            folder_path = body.get('path', '')
            subprocess.run(['open', folder_path], timeout=5)
            self._send_json(200, {'ok': True})
        except Exception as e:
            self._send_json(500, {'error': str(e)})

    def _handle_refine_prompt(self):
        try:
            body = json.loads(self._read_body())
            instruction = body.get('instruction', '').strip()
            original = body.get('originalPrompt', '').strip()
            if not instruction or not original:
                self._send_json(400, {'error': '지시 또는 원본 프롬프트가 없습니다.'})
                return

            system_prompt = body.get('systemPrompt', '').strip()
            history = body.get('conversationHistory', [])

            parts = []
            if system_prompt:
                parts.append(system_prompt)
            if history:
                parts.append("[대화 히스토리]\n" +
                             "\n".join(f"{i+1}. {h}" for i, h in enumerate(history)))
            parts.append(
                "다음 프롬프트를 주어진 지시에 따라 수정해줘.\n"
                "수정된 프롬프트만 출력하고 다른 설명은 하지 마.\n\n"
                f"원본 프롬프트:\n{original}\n\n"
                f"수정 지시: {instruction}"
            )
            prompt = "\n\n".join(parts)

            result = subprocess.run(
                [str(CLAUDE_BIN), '--print', '--output-format', 'text', prompt],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or 'Claude CLI 오류')

            self._send_json(200, {'ok': True, 'refinedPrompt': result.stdout.strip()})

        except subprocess.TimeoutExpired:
            self._send_json(500, {'error': 'Claude CLI 응답 시간 초과'})
        except Exception as e:
            self._send_json(500, {'error': str(e)})

    def _handle_classify_message(self):
        try:
            body = json.loads(self._read_body())
            message = body.get('message', '').strip()
            if not message:
                self._send_json(200, {'isAdjustment': False})
                return

            prompt = (
                "다음 메시지가 \"AI 프롬프트를 수정하거나 조정하는 요청\"인지 판단해줘.\n"
                "프롬프트 수정 요청 예: \"더 간결하게\", \"한국어로 바꿔줘\", \"기술적 용어를 줄여줘\", "
                "\"다른 관점에서 재작성\", \"더 자세히\", \"예시 추가\"\n"
                "프롬프트 수정 요청이 아닌 예: \"오늘 날씨?\", \"피자 레시피\", \"주식 정보\", "
                "\"코드 짜줘\", \"회의록 작성해줘\"\n\n"
                f"메시지: \"{message}\"\n\n"
                "\"yes\" 또는 \"no\"만 답해."
            )

            result = subprocess.run(
                [str(CLAUDE_BIN), '--print', '--output-format', 'text', prompt],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or 'Claude CLI 오류')

            answer = result.stdout.strip().lower()
            self._send_json(200, {'isAdjustment': answer.startswith('yes')})

        except subprocess.TimeoutExpired:
            self._send_json(500, {'error': 'Claude CLI 응답 시간 초과'})
        except Exception as e:
            self._send_json(500, {'error': str(e)})


def _watchdog():
    """heartbeat가 HEARTBEAT_TIMEOUT 초 이상 없으면 서버 종료."""
    print(f'[watchdog] 시작 (grace {STARTUP_GRACE}s 대기 중...)')
    time.sleep(STARTUP_GRACE)
    print('[watchdog] 감시 시작')
    while True:
        time.sleep(3)
        if _last_heartbeat is None:
            print('[watchdog] heartbeat 아직 미수신')
            continue
        elapsed = time.time() - _last_heartbeat
        print(f'[watchdog] 마지막 heartbeat {elapsed:.1f}s 전')
        if elapsed > HEARTBEAT_TIMEOUT:
            print('[watchdog] 페이지 닫힘 감지 → 서버 종료')
            threading.Thread(target=_server_instance.shutdown, daemon=True).start()
            return


def _get_my_tty():
    try:
        return os.ttyname(0)
    except Exception:
        return None


def _close_terminal(tty):
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


if __name__ == '__main__':
    os.chdir(BASE_DIR)
    my_tty = _get_my_tty()
    _server_instance = HTTPServer(('', PORT), Handler)
    url = f'http://localhost:{PORT}/main.html'
    print(f'Millestone server running at {url}')
    webbrowser.open(url)
    threading.Thread(target=_watchdog, daemon=True).start()
    try:
        _server_instance.serve_forever()
    except KeyboardInterrupt:
        pass
    print('Server stopped.')
    _close_terminal(my_tty)  # Python 종료 직전 → 팝업 없이 창 닫힘
    os._exit(0)
