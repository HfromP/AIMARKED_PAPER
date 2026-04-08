import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from data import read_settings, _TEXT_SUBPROCESS

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
_SP_TEXT_ONLY = "요청한 텍스트만 출력하세요. 설명·머리말·인사·질문 출력 금지."


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
        cmd = [str(CLAUDE_BIN), '--print', '--output-format', 'text']
        if system_prompt:
            cmd += ['--system-prompt', system_prompt]
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True, **_TEXT_SUBPROCESS, timeout=timeout,
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
