import json
import os
import platform
import shutil
from pathlib import Path

from config import PORT  # noqa: F401 — re-exported for backward compatibility

BASE_DIR = Path(__file__).parent          # apps/

# subprocess.run에 text 모드 사용 시 공통 kwargs — UTF-8로 디코딩을 시도하고 실패 시 대체(replace) 처리
_TEXT_SUBPROCESS = {'text': True, 'encoding': 'utf-8', 'errors': 'replace'}


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
