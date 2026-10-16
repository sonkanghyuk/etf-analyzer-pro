from __future__ import annotations

import copy
import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get('JOHNBER_DATA_DIR', ROOT / '.local' / 'data')).resolve()
LOCK = threading.RLock()


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return uuid.uuid4().hex


def valid_id(value):
    if not re.fullmatch(r'[a-f0-9]{32,64}', str(value)):
        raise ValueError('유효하지 않은 파일 식별자입니다.')
    return str(value)


def location(kind, identifier, suffix='.json'):
    return DATA / kind / (valid_id(identifier) + suffix)


def atomic(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uid() + '.tmp')
    try:
        with temp.open('w', encoding='utf-8') as f:
            json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def read(kind, identifier):
    p = location(kind, identifier)
    if not p.is_file():
        raise FileNotFoundError('항목을 찾을 수 없습니다.')
    return json.loads(p.read_text(encoding='utf-8'))


def write(kind, obj):
    with LOCK:
        atomic(location(kind, obj['id']), obj)
    return obj


def listing(kind):
    folder = DATA / kind
    if not folder.exists():
        return []
    with LOCK:
        return sorted([json.loads(p.read_text(encoding='utf-8')) for p in folder.glob('*.json')],
                      key=lambda x: x.get('updated_at', x.get('created_at', '')), reverse=True)


def source_path(project):
    return DATA / 'sources' / (valid_id(project['source']['asset_id']) + '.media')


def resolve_clip(clip):
    """Only this boundary turns internal asset IDs into trusted renderer paths."""
    result = copy.deepcopy(clip)
    style = result.get('style', {})
    for target, field in ((style.get('logo', {}), 'image_path'), (style, 'background_image_path')):
        target.pop(field, None)
    logo = style.get('logo', {})
    if logo.get('asset_id'):
        path = DATA / 'assets' / (valid_id(logo['asset_id']) + '.png')
        if not path.is_file():
            raise FileNotFoundError('로고 이미지가 없습니다. 다시 등록해 주세요.')
        logo['image_path'] = str(path)
    if style.get('background_asset_id'):
        path = DATA / 'assets' / (valid_id(style['background_asset_id']) + '.png')
        if not path.is_file():
            raise FileNotFoundError('배경 이미지가 없습니다. 다시 등록해 주세요.')
        style['background_image_path'] = str(path)
    return result


def snapshot(project):
    revision = project.get('revision', 0)
    atomic(DATA / 'history' / project['id'] / f'{revision:08d}.json', project)


def save_project(project, previous=None):
    if previous is not None:
        snapshot(previous)
    project['updated_at'] = now()
    project['revision'] = (previous or {}).get('revision', 0) + 1
    return write('projects', project)


def duplicate(project):
    result = copy.deepcopy(project)
    result.update(id=uid(), title=project['title'] + ' 복사', created_at=now(), revision=0)
    return save_project(result)


def safe_name(name, maximum=65):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(name)).strip(' .')[:maximum]
    if not name:
        name = '쇼츠'
    if name.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}:
        name = '_' + name
    return name
