from __future__ import annotations

import math
import re
from .storage import uid

STAMP = r'(\d{1,3}):(\d{2}):(\d{2})[,.](\d{3})'
SHORT_STAMP = r'(\d{1,3}):(\d{2})[,.](\d{3})'


def seconds(text):
    fields = re.split('[:,.]', text.strip())
    if len(fields) == 3:
        fields.insert(0, '0')
    h, m, s, ms = map(int, fields)
    if m > 59 or s > 59:
        raise ValueError('자막 시각의 분·초는 0~59여야 합니다.')
    return h * 3600 + m * 60 + s + ms / 1000


def parse(data: bytes, source_duration: float):
    decoded = None
    for encoding in ('utf-8-sig', 'utf-16', 'cp949'):
        try:
            decoded = data.decode(encoding)
            break
        except UnicodeError:
            continue
    if decoded is None:
        raise ValueError('자막 인코딩을 읽을 수 없습니다. UTF-8로 저장해 주세요.')
    lines = decoded.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    cues, i = [], 0
    pattern = re.compile(r'^\s*((?:\d+:)?\d{2}:\d{2}[,.]\d{3})\s*-->\s*((?:\d+:)?\d{2}:\d{2}[,.]\d{3})(?:\s+.*)?$')
    while i < len(lines):
        if '-->' not in lines[i]:
            i += 1
            continue
        match = pattern.match(lines[i])
        if not match:
            raise ValueError(f'{i+1}행: 잘못된 SRT/VTT 타임코드입니다.')
        start, end = map(seconds, match.groups())
        text, i = [], i + 1
        while i < len(lines) and lines[i].strip():
            text.append(re.sub(r'<[^>]+>', '', lines[i]))
            i += 1
        cues.append(dict(id=uid(), start=start, end=end, text='\n'.join(text), highlight=''))
    if not cues:
        raise ValueError('시간정보가 있는 자막이 없습니다. SRT/VTT 형식을 확인하세요.')
    return validate(cues, source_duration)


def validate(cues, source_duration):
    if not isinstance(cues, list) or len(cues) > 30000:
        raise ValueError('자막 목록은 최대 30,000개까지 지원합니다.')
    result, ids = [], set()
    previous_end = -1
    for n, c in enumerate(cues):
        if not isinstance(c,dict):
            raise ValueError('자막은 시작·종료·내용이 있는 객체여야 합니다.')
        start, end = float(c['start']), float(c['end'])
        if not math.isfinite(start + end) or start < 0 or end <= start or end > source_duration + .05:
            raise ValueError(f'자막 {n+1}: 시작·종료 시간이 원본 범위에 있지 않습니다.')
        text = str(c.get('text', ''))
        if not text.strip() or len(text) > 4000:
            raise ValueError(f'자막 {n+1}: 빈 문장 또는 너무 긴 문장입니다.')
        if start < previous_end - .001:
            raise ValueError(f'자막 {n+1}: 앞 자막과 시간이 겹칩니다. 시작/종료 시간을 수정해 주세요.')
        identifier = str(c.get('id') or uid())
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',identifier):
            raise ValueError('자막 ID는 영문·숫자·밑줄·하이픈만 사용할 수 있습니다.')
        if identifier in ids:
            raise ValueError('중복 자막 ID입니다.')
        ids.add(identifier)
        item = {'id':identifier,'start':start,'end':end,'text':text,'highlight':str(c.get('highlight',''))[:500]}
        for field in ('style','highlight_style'):
            if field in c:
                from .validation import style
                if not isinstance(c[field],dict):
                    raise ValueError('문장 스타일은 객체여야 합니다.')
                cleaned = style({'subtitle':c[field]})['subtitle']
                aliases = {'background':'bg','background_opacity':'bg_opacity','outline_width':'stroke','outline_color':'stroke_color','weight':'bold'}
                keys={aliases.get(k,k) for k in c[field]}
                item[field]={k:v for k,v in cleaned.items() if k in keys}
        result.append(item)
        previous_end = end
    return result


def stamp(t):
    ms = max(0, round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'


def export(cues):
    return '\n\n'.join(f'{i+1}\n{stamp(c["start"])} --> {stamp(c["end"])}\n{c["text"]}' for i,c in enumerate(cues)) + '\n'
