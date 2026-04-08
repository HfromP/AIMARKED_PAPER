#!/usr/bin/env python3
import datetime
import json
import os
import platform
import re
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from data import (
    BASE_DIR, PORT, _TEXT_SUBPROCESS,
    read_data, write_data, read_settings, write_settings,
    find_idea_context, find_task, find_task_context,
)
from ai import (
    CLAUDE_BIN, build_system_prompt, call_ai, _ensure_packages,
    extract_json, _validate_task_json, _validate_prompt_text,
    _validate_refine_text, _call_ai_with_retry,
    _SP_TASK_ROLE, _SP_NO_QUESTION, _SP_TASK_FORMAT,
    _SP_PROMPT_ROLE, _SP_TEXT_ONLY, _SP_REFINE_ROLE,
)
from os_utils import _get_my_tty, _close_browser_tab, _close_terminal

_server_instance = None
_ai_session_history: list = []


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
        elif self.path == '/api/settings':
            self._handle_get_settings()
        elif self.path == '/api/system-status':
            self._handle_system_status()
        elif self.path == '/api/claude-check':
            self._handle_claude_check()
        elif self.path == '/api/gemini-check':
            self._handle_gemini_check()
        elif self.path == '/api/ollama-check':
            self._handle_ollama_check()
        elif self.path == '/api/browse-folder':
            self._handle_browse_folder()
        else:
            super().do_GET()

    def do_PUT(self):
        if self.path == '/api/workspaces':
            self._handle_put_workspaces()
        elif self.path == '/api/settings':
            self._handle_put_settings()
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
        if self.path == '/api/install-python':
            self._handle_install_python()
            return
        if self.path == '/api/install-package':
            self._handle_install_package()
            return
        if self.path == '/api/reveal-folder':
            self._handle_reveal_folder()
            return
        if self.path == '/api/open-log':
            self._handle_open_log()
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
        if self.path == '/api/reset-session':
            self._handle_reset_session()
            return
        self._send_json(404, {'error': 'Not found'})

    # ── 핸들러 구현 ────────────────────────────────────────

    def _handle_system_status(self):
        import platform
        system_config = BASE_DIR / 'system.config'
        python_installed = False
        if system_config.exists():
            for line in system_config.read_text(encoding='utf-8').splitlines():
                if line.startswith('PYTHON_BIN='):
                    python_bin = line[len('PYTHON_BIN='):]
                    python_installed = Path(python_bin).exists()
                    break

        settings = read_settings()
        provider = settings.get('ai_provider', '')
        keys = settings.get('api_keys', {})
        if provider in ('claude_cli', 'gemini_cli', 'ollama_cli'):
            ai_connected = True
        elif provider == 'claude_api' and keys.get('anthropic', '').strip():
            ai_connected = True
        elif provider == 'openai' and keys.get('openai', '').strip():
            ai_connected = True
        elif provider == 'gemini' and keys.get('gemini', '').strip():
            ai_connected = True
        else:
            ai_connected = False

        self._send_json(200, {
            'python_installed': python_installed,
            'ai_connected': ai_connected,
            'ai_provider': provider,
            'os': platform.system(),
        })

    def _handle_install_python(self):
        import platform
        try:
            if platform.system() == 'Windows':
                script = BASE_DIR / 'Installations' / 'install_python.bat'
                cmd = [str(script)]
            else:
                script = BASE_DIR / 'Installations' / 'install_python.command'
                cmd = ['bash', str(script)]

            if not script.exists():
                self._send_json(200, {'success': False, 'message': f'설치 스크립트를 찾을 수 없습니다: {script}'})
                return

            result = subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                capture_output=True, **_TEXT_SUBPROCESS, timeout=300
            )
            if result.returncode == 0:
                self._send_json(200, {'success': True, 'message': result.stdout.strip()})
            else:
                self._send_json(200, {'success': False, 'message': result.stderr.strip() or result.stdout.strip()})
        except subprocess.TimeoutExpired:
            self._send_json(200, {'success': False, 'message': '설치 시간이 초과되었습니다 (5분). 네트워크를 확인해주세요.'})
        except Exception as e:
            self._send_json(500, {'error': str(e)})

    def _handle_install_package(self):
        try:
            body = json.loads(self._read_body())
            provider = body.get('provider', '')
            pkg_map = {
                'anthropic': 'anthropic',
                'openai': 'openai',
                'gemini': 'google-generativeai',
            }
            pkg = pkg_map.get(provider)
            if not pkg:
                self._send_json(400, {'error': '알 수 없는 provider입니다.'})
                return

            result = subprocess.run(
                [sys.executable, '-m', 'pip', 'install', pkg],
                capture_output=True, **_TEXT_SUBPROCESS, timeout=120
            )
            if result.returncode == 0:
                self._send_json(200, {'success': True, 'message': f'{pkg} 설치 완료'})
            else:
                self._send_json(200, {'success': False, 'message': result.stderr.strip()})
        except subprocess.TimeoutExpired:
            self._send_json(200, {'success': False, 'message': '설치 시간이 초과되었습니다.'})
        except Exception as e:
            self._send_json(500, {'error': str(e)})

    def _handle_shutdown(self):
        self._send_json(200, {'ok': True})
        def _delayed_shutdown():
            time.sleep(0.5)  # 응답이 클라이언트에 완전히 전달된 뒤 종료
            _server_instance.shutdown()
        threading.Thread(target=_delayed_shutdown, daemon=True).start()

    def _handle_reset_session(self):
        global _ai_session_history
        _ai_session_history.clear()
        settings = read_settings()
        provider = settings.get('ai_provider', 'claude_cli')
        self._send_json(200, {'success': True, 'provider': provider})

    def _handle_browse_folder(self):
        try:
            system = platform.system()

            if system == 'Windows':
                # PowerShell FolderBrowserDialog 사용
                # UTF-8 출력 강제 설정 후 경로 선택
                ps_script = (
                    "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8;"
                    "$OutputEncoding = [System.Text.Encoding]::UTF8;"
                    "Add-Type -AssemblyName System.Windows.Forms;"
                    "$d = New-Object System.Windows.Forms.FolderBrowserDialog;"
                    "$d.ShowNewFolderButton = $true;"
                    "if ($d.ShowDialog() -eq 'OK') { Write-Output $d.SelectedPath }"
                )
                result = subprocess.run(
                    ['powershell', '-NoProfile', '-NonInteractive', '-Command', ps_script],
                    capture_output=True, **_TEXT_SUBPROCESS, timeout=60
                )
                path = result.stdout.strip()
                if path:
                    self._send_json(200, {'ok': True, 'path': path})
                elif result.returncode != 0:
                    self._send_json(500, {'error': f'PowerShell error (code {result.returncode}): {result.stderr.strip()}'})
                else:
                    self._send_json(200, {'ok': False, 'cancelled': True})

            elif system == 'Darwin':
                # 기존 macOS 코드
                result = subprocess.run(
                    ['osascript', '-e', 'POSIX path of (choose folder)'],
                    capture_output=True, **_TEXT_SUBPROCESS, timeout=60
                )
                if result.returncode == 0:
                    path = result.stdout.strip()
                    self._send_json(200, {'ok': True, 'path': path})
                else:
                    self._send_json(200, {'ok': False, 'cancelled': True})

            else:
                # Linux — zenity 사용 (설치 필요)
                result = subprocess.run(
                    ['zenity', '--file-selection', '--directory'],
                    capture_output=True, **_TEXT_SUBPROCESS, timeout=60
                )
                if result.returncode == 0:
                    self._send_json(200, {'ok': True, 'path': result.stdout.strip()})
                else:
                    self._send_json(200, {'ok': False, 'cancelled': True})

        except subprocess.TimeoutExpired:
            self._send_json(200, {'ok': False, 'error': '응답 시간 초과'})
        except Exception as e:
            self._send_json(500, {'error': str(e)})

    def _handle_gemini_check(self):
        try:
            result = subprocess.run(
                ['gemini', '--version'],
                capture_output=True, **_TEXT_SUBPROCESS, timeout=10
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

    def _handle_ollama_check(self):
        try:
            result = subprocess.run(
                ['ollama', '--version'],
                capture_output=True, **_TEXT_SUBPROCESS, timeout=10
            )
            if result.returncode == 0:
                version = result.stdout.strip() or result.stderr.strip()
                self._send_json(200, {'ok': True, 'version': version})
            else:
                self._send_json(200, {'ok': False, 'error': result.stderr.strip()})
        except FileNotFoundError:
            self._send_json(200, {'ok': False, 'error': 'Ollama CLI를 찾을 수 없습니다'})
        except subprocess.TimeoutExpired:
            self._send_json(200, {'ok': False, 'error': '응답 시간 초과'})
        except Exception as e:
            self._send_json(200, {'ok': False, 'error': str(e)})

    def _handle_claude_check(self):
        try:
            result = subprocess.run(
                [str(CLAUDE_BIN), '--version'],
                capture_output=True, **_TEXT_SUBPROCESS, timeout=10
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

    def _handle_get_settings(self):
        self._send_json(200, read_settings())

    def _handle_put_settings(self):
        try:
            body = self._read_body()
            incoming = json.loads(body)
            current = read_settings()
            # 부분 병합: api_keys는 내부 딕셔너리 단위로 병합
            if 'api_keys' in incoming and 'api_keys' in current:
                current['api_keys'].update(incoming.pop('api_keys'))
            current.update(incoming)
            write_settings(current)
            self._send_json(200, {'ok': True})
        except Exception as e:
            self._send_json(500, {'error': str(e)})

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
            ws, proj, ms, idea = find_idea_context(data, idea_id)
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
                "위 아이디어의 구현 Task 목록을 출력해줘."
            )
            prompt = "\n\n".join(parts)

            user_sp = build_system_prompt(
                (ws or {}).get('systemPrompt', ''),
                (proj or {}).get('systemPrompt', ''),
                (ms or {}).get('systemPrompt', ''),
                idea.get('systemPrompt', ''),
            )
            sp = build_system_prompt(_SP_TASK_ROLE, _SP_NO_QUESTION, _SP_TASK_FORMAT, user_sp)
            response_text = _call_ai_with_retry(
                prompt, system_prompt=sp, timeout=120,
                validate=_validate_task_json, max_retries=2
            )
            log_path = BASE_DIR / 'ai_debug.log'
            with open(log_path, 'a', encoding='utf-8') as lf:
                lf.write(f'\n=== {datetime.datetime.now().isoformat()} ===\n')
                lf.write(f'[PROMPT]\n{prompt}\n\n[RESPONSE]\n{response_text}\n')
            tasks = extract_json(response_text)
            with open(log_path, 'a', encoding='utf-8') as lf:
                lf.write(f'[PARSED OK] {json.dumps(tasks, ensure_ascii=False)}\n')

            # 기존 tasks에 추가 (id는 JS가 없으므로 timestamp 기반 생성)
            for i, t in enumerate(tasks):
                t['id'] = f'task_{int(time.time() * 1000)}_{i}'
                t['status'] = 'idea'
                t['prompts'] = []

            idea['tasks'] = tasks
            write_data(data)
            self._send_json(200, idea)

        except Exception as e:
            self._send_json(500, {'error': str(e)})

    def _handle_task_prompt(self, task_id):
        try:
            body = json.loads(self._read_body()) if int(self.headers.get('Content-Length', 0)) else {}
            user_sp = body.get('systemPrompt', '').strip()
            history = body.get('conversationHistory', [])

            data = read_data()
            idea, task = find_task(data, task_id)
            if task is None:
                self._send_json(404, {'error': f'task {task_id} not found'})
                return

            parts = []
            if history:
                parts.append("[이전 프롬프트 히스토리]\n" +
                             "\n".join(f"{i+1}. {h}" for i, h in enumerate(history)))
            task_desc = task.get('description', '').strip()
            parts.append(
                f"아이디어: {idea.get('title', '')}\n"
                f"아이디어 설명: {idea.get('description', '')}\n"
                f"Task 이름: {task.get('name', '')}\n"
                + (f"Task 세부 설명: {task_desc}\n" if task_desc else "") +
                "\n위 Task를 수행하기 위해 다른 AI(Claude Code)에게 전달할 프롬프트를 작성해줘.\n"
                "아래 구조를 반드시 따를 것:\n\n"
                "## Task: [Task 이름]\n\n"
                "[Task의 목적 1~2문장]\n\n"
                "### 구현할 것\n"
                "- [결과물]: [구체적인 스펙]\n\n"
                "### 제약 조건\n"
                "- [기존 코드/패턴과의 연결, 네이밍, 파일 위치 등]\n\n"
                "### 완료 기준\n"
                "- [ ] [검증 가능한 기준]\n\n"
                "---\n"
                "계획을 먼저 작성하고 승인 후 구현해줘.\n\n"
                "규칙: Task를 직접 실행하지 말고 프롬프트 텍스트만 출력할 것."
            )
            prompt = "\n\n".join(parts)
            sp = build_system_prompt(_SP_PROMPT_ROLE, _SP_NO_QUESTION, _SP_TEXT_ONLY, user_sp)

            result = _call_ai_with_retry(
                prompt, system_prompt=sp, timeout=60,
                validate=_validate_prompt_text, max_retries=1
            )
            self._send_json(200, {'ok': True, 'prompt': result})

        except Exception as e:
            self._send_json(500, {'error': str(e)})

    def _handle_task_execute(self, task_id):
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
                capture_output=True, stdin=subprocess.DEVNULL, **_TEXT_SUBPROCESS, timeout=120
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or 'Claude CLI 오류')

            content = result.stdout.strip()

            idea_dir   = safe_name(idea.get('title', 'idea'))
            task_dir   = safe_name(task.get('name', 'task'))
            timestamp  = time.strftime('%Y%m%d_%H%M%S')
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
            if not folder_path:
                self._send_json(400, {'error': '경로가 없습니다.'})
                return

            system = platform.system()
            if system == 'Windows':
                os.startfile(folder_path)
            elif system == 'Darwin':
                try:
                    subprocess.run(
                        ['open', folder_path],
                        timeout=5,
                        check=True,
                        capture_output=True,
                        **_TEXT_SUBPROCESS
                    )
                except FileNotFoundError:
                    self._send_json(500, {'error': "'open' command not found on PATH"})
                    return
                except subprocess.CalledProcessError as e:
                    error_detail = (e.stderr or e.stdout or '').strip() or 'open command failed'
                    self._send_json(500, {'error': f"'open' failed with exit code {e.returncode}: {error_detail}"})
                    return
            else:
                try:
                    subprocess.run(
                        ['xdg-open', folder_path],
                        timeout=5,
                        check=True,
                        capture_output=True,
                        **_TEXT_SUBPROCESS
                    )
                except FileNotFoundError:
                    self._send_json(500, {'error': "'xdg-open' command not found on PATH"})
                    return
                except subprocess.CalledProcessError as e:
                    error_detail = (e.stderr or e.stdout or '').strip() or 'xdg-open command failed'
                    self._send_json(500, {'error': f"'xdg-open' failed with exit code {e.returncode}: {error_detail}"})
                    return

            self._send_json(200, {'ok': True})
        except FileNotFoundError:
            self._send_json(500, {'error': f'경로를 찾을 수 없습니다: {folder_path}'})
        except Exception as e:
            self._send_json(500, {'error': str(e)})

    def _handle_open_log(self):
        log_path = BASE_DIR / 'ai_debug.log'
        if not log_path.exists():
            self._send_json(404, {'error': 'AI 로그 파일이 없습니다. 아직 AI를 사용하지 않았거나 로그가 생성되지 않았습니다.'})
            return
        try:
            system = platform.system()
            if system == 'Windows':
                os.startfile(str(log_path))
            elif system == 'Darwin':
                subprocess.run(['open', str(log_path)], timeout=5, check=True,
                               capture_output=True, **_TEXT_SUBPROCESS)
            else:
                subprocess.run(['xdg-open', str(log_path)], timeout=5, check=True,
                               capture_output=True, **_TEXT_SUBPROCESS)
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

            user_sp = body.get('systemPrompt', '').strip()
            history = body.get('conversationHistory', [])

            parts = []
            history_to_show = history[:-1] if history and history[-1] == original else history
            if history_to_show:
                parts.append("[대화 히스토리]\n" +
                             "\n".join(f"{i+1}. {h}" for i, h in enumerate(history_to_show)))
            parts.append(
                f"<original_prompt>\n{original}\n</original_prompt>\n\n"
                f"<instruction>\n{instruction}\n"
                f"(수정 지시가 영향을 주는 모든 섹션을 일관되게 반영할 것)\n</instruction>\n\n"
                f"위 instruction에 따라 original_prompt를 수정하세요.\n"
                f"수정된 프롬프트만 출력하세요. 설명·주석·XML 태그 출력 금지."
            )
            prompt = "\n\n".join(parts)
            sp = build_system_prompt(_SP_REFINE_ROLE, _SP_NO_QUESTION, _SP_TEXT_ONLY, user_sp)

            log_path = BASE_DIR / 'ai_debug.log'
            with open(log_path, 'a', encoding='utf-8') as lf:
                lf.write(f'\n=== REFINE {datetime.datetime.now().isoformat()} ===\n')
                lf.write(f'[SYSTEM]\n{sp}\n')
                lf.write(f'[PROMPT]\n{prompt}\n')

            def _log_attempt(attempt, response, ok, reason):
                with open(log_path, 'a', encoding='utf-8') as lf:
                    lf.write(f'[시도 {attempt}] ok={ok} | 사유={reason or "없음"}\n')
                    lf.write(f'[응답]\n{response}\n')

            result = _call_ai_with_retry(
                prompt, system_prompt=sp, timeout=60,
                validate=lambda t: _validate_refine_text(t, original), max_retries=1,
                log_fn=_log_attempt
            )

            self._send_json(200, {'ok': True, 'refinedPrompt': result})

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
                capture_output=True, stdin=subprocess.DEVNULL, **_TEXT_SUBPROCESS, timeout=30
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or 'Claude CLI 오류')

            answer = result.stdout.strip().lower()
            self._send_json(200, {'isAdjustment': answer.startswith('yes')})

        except subprocess.TimeoutExpired:
            self._send_json(500, {'error': 'Claude CLI 응답 시간 초과'})
        except Exception as e:
            self._send_json(500, {'error': str(e)})


if __name__ == '__main__':
    os.chdir(BASE_DIR)
    my_tty = _get_my_tty()
    threading.Thread(target=_ensure_packages, daemon=True).start()
    _server_instance = ThreadingHTTPServer(('', PORT), Handler)
    url = f'http://localhost:{PORT}/main.html'
    print(f'Millestone server running at {url}')
    webbrowser.open(url)
    try:
        _server_instance.serve_forever()
    except KeyboardInterrupt:
        pass
    print('Server stopped.')
    _close_browser_tab()
    _close_terminal(my_tty)
    os._exit(0)
