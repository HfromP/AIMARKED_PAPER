#!/usr/bin/env python3
import json
import os
import re
import subprocess
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

PORT = 5500
BASE_DIR = Path(__file__).parent          # apps/
DATA_FILE = BASE_DIR / 'data.json'
CLAUDE_BIN = Path.home() / '.local' / 'bin' / 'claude'


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
        else:
            self._send_json(404, {'error': 'Not found'})

    # ── 핸들러 구현 ────────────────────────────────────────

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

            prompt = (
                f"아이디어 제목: {idea.get('title', '')}\n"
                f"아이디어 설명: {idea.get('description', '')}\n\n"
                "위 아이디어를 구현하기 위한 구체적인 Task 목록을 JSON 배열로만 응답해줘.\n"
                "다른 설명 없이 JSON 배열만 출력해줘.\n"
                '각 Task는 {"name": "...", "importance": 1|2|3} 형태야. (1=낮음, 2=보통, 3=높음)'
            )

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


if __name__ == '__main__':
    os.chdir(BASE_DIR)
    server = HTTPServer(('', PORT), Handler)
    print(f'Millestone server running at http://localhost:{PORT}/main.html')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nServer stopped.')
