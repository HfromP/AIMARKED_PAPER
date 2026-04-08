#!/usr/bin/env python3
import logging
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

PORT = 5500
BASE_DIR = Path(__file__).parent          # apps/


def _get_user_data_dir() -> Path:
    """OS별 표준 사용자 데이터 폴더를 반환한다."""
    system = platform.system()
    if system == 'Windows':
        appdata = os.environ.get('APPDATA')
        return Path(appdata) / 'Millestone' if appdata else Path.home() / 'AppData' / 'Roaming' / 'Millestone'
    if system == 'Darwin':
        return Path.home() / 'Library' / 'Application Support' / 'Millestone'
    xdg = os.environ.get('XDG_CONFIG_HOME')
    return Path(xdg) / 'millestone' if xdg else Path.home() / '.config' / 'millestone'


def _migrate_legacy_data(user_data_dir: Path):
    """apps/ 안의 기존 데이터 파일을 user_data_dir로 복사한다 (덮어쓰기 없음)."""
    user_data_dir.mkdir(parents=True, exist_ok=True)
    for name in ('data.json', 'settings.config'):
        src, dst = BASE_DIR / name, user_data_dir / name
        if src.exists() and not dst.exists():
            shutil.copy2(src, dst)
            src.unlink()


USER_DATA_DIR = _get_user_data_dir()
_migrate_legacy_data(USER_DATA_DIR)
DATA_FILE = USER_DATA_DIR / 'data.json'
SETTINGS_FILE = USER_DATA_DIR / 'settings.config'

# subprocess.run에 text 모드 사용 시 공통 kwargs — UTF-8로 디코딩을 시도하고 실패 시 대체(replace) 처리
_TEXT_SUBPROCESS = {'text': True, 'encoding': 'utf-8', 'errors': 'replace'}

# ── 시스템 프롬프트 원자 단위 상수 ──────────────────────────────────────────
_SP_NO_QUESTION = "절대 질문하지 말고 주어진 정보로 합리적으로 추측하여 즉시 답변하세요."
_SP_TASK_ROLE = (
    "당신은 소프트웨어 개발 Task 목록 생성 도구입니다. "
    "아이디어를 받으면 다음 원칙으로 Task를 분해한다: "
    "(1) 각 Task는 Claude Code 한 세션(30분~2시간)에서 완료 가능한 크기. 예: 'XService 클래스 설계 및 구현'. "
    "(2) Task 이름에 생성되는 파일·클래스·기능을 명시. "
    "(3) 의존성 순서로 배열. "
    "importance 기준 — 3: 없으면 동작 불가, 2: 중요하나 나중에 추가 가능, 1: polish·편의 기능."
)
_SP_PROMPT_ROLE = (
    "당신은 AI 프롬프트 생성 도구입니다. "
    "당신의 역할은 오직 '다른 AI에게 전달할 프롬프트 텍스트'를 작성하는 것입니다. "
    "절대로 Task를 직접 수행하거나 결과물을 출력하지 마세요. "
    "출력은 반드시 프롬프트 텍스트 단 하나여야 합니다."
)
_SP_REFINE_ROLE = (
    "당신은 AI 프롬프트 개선 도구입니다. "
    "원본 프롬프트를 수정 지시에 따라 수정한 결과 텍스트만 출력하라. "
    "맥락 요청·상태 메시지·설명·질문·'대기 중' 같은 출력은 절대 금지. "
    "수정 원칙: "
    "(1) 기존 구조 유지 — 전체를 다시 쓰지 말고 필요한 부분만 수정한다. "
    "(2) 의도 보존 — 수정 지시가 명시하지 않은 내용은 원본 그대로 유지한다. "
    "(3) 파급 효과 추적 — 수정이 완료 기준·예시·제약 조건 등 다른 섹션과 충돌하면 해당 섹션도 함께 수정한다. "
    "(4) 충돌 해소 — 수정 지시와 기존 내용이 충돌하면 수정 지시를 우선한다. "
    "금지: 수정 지시에 없는 내용 추가 또는 삭제, 기존 용어를 동의어로 교체, 섹션 순서 변경, 언어(한국어·영어) 혼용."
)
_SP_TASK_FORMAT = (
    '반드시 [{"name":"작업명","importance":숫자}] 형식의 JSON 배열만 출력하세요. '
    'importance는 1(낮음)·2(보통)·3(높음) 중 하나의 정수. '
    'id·title·category·description 등 다른 필드 사용 금지. '
    'JSON 배열 외 텍스트 출력 금지.'
)
_SP_TEXT_ONLY   = "요청한 텍스트만 출력하세요. 설명·머리말·인사·질문 출력 금지."


def build_system_prompt(*parts):
    """여러 시스템 프롬프트 조각을 공백으로 합쳐 하나의 문자열로 반환한다."""
    return " ".join(p.strip() for p in parts if p and p.strip())


_CLI_CONTEXT_FILENAMES = {
    'claude_cli': 'CLAUDE.md',
    'gemini_cli': 'GEMINI.md',
}


def _write_cli_context(provider: str, system_prompt: str | None, directory: str):
    """요청별 격리 디렉토리에 CLI 컨텍스트 파일을 생성한다."""
    filename = _CLI_CONTEXT_FILENAMES.get(provider)
    if not filename or not system_prompt:
        return
    (Path(directory) / filename).write_text(system_prompt, encoding='utf-8')


def _find_claude_bin() -> Path:
    """OS에 무관하게 claude CLI 실행 파일 경로를 탐색한다."""
    # 1순위: PATH 전체 탐색 (가장 범용적)
    found = shutil.which('claude')
    if found:
        return Path(found)
    # 2순위: macOS 기본 설치 경로
    if platform.system() == 'Darwin':
        p = Path.home() / '.local' / 'bin' / 'claude'
        if p.exists():
            return p
    # 3순위: Windows — npm global 설치 경로 (claude CLI가 npm 패키지인 경우)
    if platform.system() == 'Windows':
        appdata_roots = [
            Path(value)
            for value in (os.environ.get('APPDATA'), os.environ.get('LOCALAPPDATA'))
            if value
        ]
        for root in appdata_roots:
            for candidate in [
                root / 'npm' / 'claude.cmd',
                root / 'npm' / 'claude',
            ]:
                if candidate.exists():
                    return candidate
    # fallback: PATH에 의존
    return Path('claude')


CLAUDE_BIN = _find_claude_bin()
_server_instance = None
_ai_session_history: list = []


def read_data():
    if not DATA_FILE.exists():
        return {'workspaces': []}
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def write_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def read_settings():
    if not SETTINGS_FILE.exists():
        return {'language': 'ko', 'theme': 'light', 'ai_provider': 'claude_cli', 'api_keys': {'openai': '', 'anthropic': '', 'gemini': ''}, 'ollama_model': 'llama3.2'}
    with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    data.setdefault('language', 'ko')
    data.setdefault('ollama_model', 'llama3.2')
    return data


def write_settings(settings):
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


def call_ai(prompt, timeout=120, system_prompt=None):
    """settings.config의 ai_provider에 따라 AI 호출. 텍스트 응답 반환."""
    settings = read_settings()
    provider = settings.get('ai_provider', 'claude_cli')
    keys = settings.get('api_keys', {})

    if provider == 'openai':
        try:
            import openai
        except ImportError:
            raise RuntimeError('openai 패키지가 설치되지 않았습니다. 서버를 재시작해주세요.')
        api_key = keys.get('openai', '').strip()
        if not api_key:
            raise ValueError('OpenAI API 키가 설정되지 않았습니다.')
        client = openai.OpenAI(api_key=api_key, timeout=timeout)
        messages = []
        if system_prompt:
            messages.append({'role': 'system', 'content': system_prompt})
        messages.append({'role': 'user', 'content': prompt})
        resp = client.chat.completions.create(model='gpt-4o', messages=messages, temperature=0)
        return resp.choices[0].message.content.strip()

    elif provider == 'claude_api':
        try:
            import anthropic
        except ImportError:
            raise RuntimeError('anthropic 패키지가 설치되지 않았습니다. 서버를 재시작해주세요.')
        api_key = keys.get('anthropic', '').strip()
        if not api_key:
            raise ValueError('Anthropic API 키가 설정되지 않았습니다.')
        client = anthropic.Anthropic(api_key=api_key, timeout=timeout)
        kwargs = dict(model='claude-sonnet-4-6', max_tokens=4096, temperature=0,
                      messages=[{'role': 'user', 'content': prompt}])
        if system_prompt:
            kwargs['system'] = system_prompt
        msg = client.messages.create(**kwargs)
        return msg.content[0].text.strip()

    elif provider == 'gemini':
        try:
            import google.generativeai as genai
        except ImportError:
            raise RuntimeError('google-generativeai 패키지가 설치되지 않았습니다. 서버를 재시작해주세요.')
        api_key = keys.get('gemini', '').strip()
        if not api_key:
            raise ValueError('Gemini API 키가 설정되지 않았습니다.')
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.0-flash',
                                      system_instruction=system_prompt or None)
        resp = model.generate_content(prompt, generation_config={'temperature': 0})
        return resp.text.strip()

    elif provider == 'gemini_cli':
        with tempfile.TemporaryDirectory() as tmp_dir:
            _write_cli_context('gemini_cli', system_prompt, tmp_dir)
            result = subprocess.run(
                ['gemini', '-p', prompt],
                capture_output=True, stdin=subprocess.DEVNULL, **_TEXT_SUBPROCESS, timeout=timeout, cwd=tmp_dir
            )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or 'Gemini CLI 오류')
        return result.stdout.strip()

    elif provider == 'ollama_cli':
        ollama_model = settings.get('ollama_model', '').strip() or 'llama3.2'
        effective = f"[System]\n{system_prompt}\n\n{prompt}" if system_prompt else prompt
        result = subprocess.run(
            ['ollama', 'run', ollama_model],
            input=effective,
            capture_output=True, **_TEXT_SUBPROCESS, timeout=timeout
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or 'Ollama CLI 오류')
        return result.stdout.strip()

    else:  # claude_cli (default)
        with tempfile.TemporaryDirectory() as tmp_dir:
            _write_cli_context('claude_cli', system_prompt, tmp_dir)
            cmd = [str(CLAUDE_BIN), '--print']
            cmd.append(prompt)
            result = subprocess.run(
                cmd,
                capture_output=True, stdin=subprocess.DEVNULL, **_TEXT_SUBPROCESS, timeout=timeout,
                cwd=tmp_dir
            )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or 'Claude CLI 오류')
        return result.stdout.strip()


def _ensure_packages():
    """백그라운드에서 AI API 패키지 설치."""
    for pkg in ['openai', 'anthropic', 'google-generativeai']:
        try:
            subprocess.check_call(
                [sys.executable, '-m', 'pip', 'install', pkg, '-q'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except Exception:
            pass


def extract_json(text):
    """CLI 응답에서 JSON 배열 추출. 코드블록 안팎 모두 처리."""
    def _list_from(parsed):
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            list_fields = [(k, v) for k, v in parsed.items() if isinstance(v, list)]
            if len(list_fields) == 1:
                return list_fields[0][1]
        return None

    decoder = json.JSONDecoder()

    # 1. ```json ... ``` 블록 우선 시도 (raw_decode로 중첩 객체 처리)
    m = re.search(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL)
    if m:
        try:
            obj, _ = decoder.raw_decode(m.group(1).strip())
            result = _list_from(obj)
            if result is not None:
                return result
        except (json.JSONDecodeError, ValueError):
            pass

    # 2. 텍스트에서 첫 번째 유효한 [ ... ] 또는 { ... } 탐색
    for i, c in enumerate(text):
        if c in ('[', '{'):
            try:
                obj, _ = decoder.raw_decode(text, i)
                result = _list_from(obj)
                if result is not None:
                    return result
            except json.JSONDecodeError:
                pass

    raise ValueError(f'JSON 배열을 찾을 수 없습니다.\nAI 응답:\n{text}')


def _validate_task_json(text):
    """(ok, reason) 반환. Task JSON 형식·필드를 검증한다."""
    try:
        tasks = extract_json(text)
        for t in tasks:
            if 'name' not in t:
                return False, f"'name' 필드 없음: {t}"
            if t.get('importance') not in (1, 2, 3):
                return False, f"importance 값 오류: {t.get('importance')!r} (1·2·3만 허용)"
        return True, ""
    except ValueError as e:
        return False, str(e)


def _validate_prompt_text(text):
    """(ok, reason) 반환. 질문형·빈 응답·맥락 요청형 응답을 감지한다."""
    stripped = (text or "").strip()
    if len(stripped) < 10:
        return False, f"응답이 너무 짧음: {stripped!r}"
    if stripped.endswith('?') or stripped.endswith('？'):
        return False, f"질문형 응답 감지: {stripped[:120]}"
    _context_request_endings = ('주세요', '바랍니다', 'please', 'provide')
    _stripped_for_ending = stripped.rstrip('.。！!')
    if any(_stripped_for_ending.lower().endswith(e) for e in _context_request_endings):
        return False, f"맥락 요청형 응답 감지: {stripped[:120]}"
    return True, ""


def _validate_refine_text(text, original_prompt=None):
    """refine-prompt 전용 검증. 빈 응답, 순수 질문, 원본 그대로 반환을 거른다.
    정제된 프롬프트는 '주세요'로 끝나도 정상이므로 맥락 요청 체크를 하지 않는다."""
    stripped = (text or "").strip()
    if len(stripped) < 3:
        return False, f"응답이 너무 짧음: {stripped!r}"
    if stripped.endswith('?') or stripped.endswith('？'):
        return False, f"질문형 응답 감지: {stripped[:120]}"
    if original_prompt and stripped == original_prompt.strip():
        return False, "원본과 동일 — 수정이 이뤄지지 않음"
    return True, ""


def _call_ai_with_retry(prompt, system_prompt=None, timeout=120,
                        validate=None, max_retries=2, log_fn=None):
    """AI 호출 + 검증 + 재시도.

    validate: (text) → (ok: bool, reason: str)
    log_fn:   (attempt: int, response: str, ok: bool|None, reason: str|None) → None
              응답을 받는 즉시 호출됨 (validate 전).
    성공 시 응답 텍스트 반환.
    전부 실패 시 ValueError (각 시도 요약 포함).
    """
    original_prompt = prompt
    log = []
    for attempt in range(max_retries + 1):
        response = call_ai(prompt, timeout=timeout, system_prompt=system_prompt)
        if validate is None:
            if log_fn:
                log_fn(attempt + 1, response, True, None)
            return response
        ok, reason = validate(response)
        if log_fn:
            log_fn(attempt + 1, response, ok, reason)
        log.append(
            f"[시도 {attempt + 1}] 사유: {reason or '없음'}\n"
            f"AI 응답: {response[:300]}"
        )
        if ok:
            return response
        if attempt < max_retries:
            prompt = (
                f"이전 응답이 형식 오류였습니다.\n"
                f"오류 사유: {reason}\n"
                f"이전 응답(참고): {response[:200]}\n\n"
                + original_prompt
            )
    raise ValueError("형식 오류 — 재시도 후에도 실패\n\n" + "\n\n".join(log))


def find_idea_context(data, idea_id):
    """data 구조에서 idea_id에 해당하는 (workspace, project, milestone, idea) 반환."""
    for ws in data.get('workspaces', []):
        for proj in ws.get('projects', []):
            for ms in proj.get('milestones', []):
                for idea in ms.get('ideas', []):
                    if idea.get('id') == idea_id:
                        return ws, proj, ms, idea
    return None, None, None, None


def find_idea(data, idea_id):
    """data 구조에서 idea_id에 해당하는 idea dict 반환."""
    _, _, _, idea = find_idea_context(data, idea_id)
    return idea


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


def _build_idea_prompts(ws, proj, ms, idea):
    """idea 컨텍스트에서 (system_prompt, user_prompt) 튜플을 조립해 반환한다."""
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
    user_prompt = "\n\n".join(parts)

    user_sp = build_system_prompt(
        (ws or {}).get('systemPrompt', ''),
        (proj or {}).get('systemPrompt', ''),
        (ms or {}).get('systemPrompt', ''),
        idea.get('systemPrompt', ''),
    )
    system_prompt = build_system_prompt(_SP_TASK_ROLE, _SP_NO_QUESTION, _SP_TASK_FORMAT, user_sp)
    return system_prompt, user_prompt


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
            m = re.fullmatch(r'/api/ideas/([^/]+)/prompt', self.path)
            if m:
                self._handle_get_idea_prompt(m.group(1))
                return
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

    def _handle_get_idea_prompt(self, idea_id):
        """AI 호출 없이 idea에 대한 프롬프트 텍스트만 반환한다."""
        try:
            data = read_data()
            ws, proj, ms, idea = find_idea_context(data, idea_id)
            if idea is None:
                self._send_json(404, {'error': f'idea {idea_id} not found'})
                return

            system_prompt, user_prompt = _build_idea_prompts(ws, proj, ms, idea)
            self._send_json(200, {'systemPrompt': system_prompt, 'userPrompt': user_prompt})
        except Exception as e:
            self._send_json(500, {'error': str(e)})

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

            sp, prompt = _build_idea_prompts(ws, proj, ms, idea)
            response_text = _call_ai_with_retry(
                prompt, system_prompt=sp, timeout=120,
                validate=_validate_task_json, max_retries=2
            )
            log_path = BASE_DIR / 'ai_debug.log'
            with open(log_path, 'a', encoding='utf-8') as lf:
                import datetime
                lf.write(f'\n=== {datetime.datetime.now().isoformat()} ===\n')
                lf.write(f'[PROMPT]\n{prompt}\n\n[RESPONSE]\n{response_text}\n')
            tasks = extract_json(response_text)
            with open(log_path, 'a', encoding='utf-8') as lf:
                lf.write(f'[PARSED OK] {json.dumps(tasks, ensure_ascii=False)}\n')

            # 기존 tasks에 추가 (id는 JS가 없으므로 timestamp 기반 생성)
            import time
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
                capture_output=True, stdin=subprocess.DEVNULL, **_TEXT_SUBPROCESS, timeout=120
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

            import datetime
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
