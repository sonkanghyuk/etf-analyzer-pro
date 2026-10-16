from __future__ import annotations

import copy
import math
import re
from .storage import uid
from .media import default_style


def number(value, low, high, label):
    try:
        value = float(value)
    except (ValueError,TypeError,OverflowError) as exc:
        raise ValueError(f'{label}: 숫자를 입력하세요.') from exc
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{label}: {low}~{high} 범위의 숫자를 입력하세요.')
    return value


def style(value):
    base = default_style()
    if not isinstance(value, dict):
        raise ValueError('스타일 형식이 올바르지 않습니다.')
    aliases = {'background':'bg','background_opacity':'bg_opacity','outline_width':'stroke','outline_color':'stroke_color','weight':'bold'}
    for key, obj in value.items():
        if key == 'background':
            if not re.fullmatch(r'#[0-9a-fA-F]{6}', str(obj)):
                raise ValueError('배경색은 #RRGGBB 형식이어야 합니다.')
            base[key] = obj
        elif key in ('video', 'title', 'subtitle', 'highlight', 'logo') and isinstance(obj, dict):
            target = base.setdefault(key, {})
            for field, val in obj.items():
                if field == 'weight':
                    val = str(val) in ('bold','700','800','900')
                field = aliases.get(field,field)
                if field in ('x','y'):
                    target[field] = number(val, -1920, 3840, field)
                elif field in ('w','h','width','height'):
                    target[field] = number(val, 1, 3840, field)
                elif field in ('size','font_size'):
                    target[field] = number(val, 10, 220, field)
                elif field == 'letter_spacing':
                    target[field] = number(val, -5, 40, field)
                elif field == 'stroke':
                    target[field] = number(val, 0, 20, field)
                elif field in ('padding','radius','shadow'):
                    target[field] = number(val, 0, 100, field)
                elif field in ('bg_opacity','opacity'):
                    target[field] = number(val, 0, 1, field)
                elif field == 'line_height':
                    target[field] = number(val, .6, 3, field)
                elif field in ('color','bg','stroke_color','shadow_color'):
                    if not re.fullmatch(r'#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?', str(val)):
                        raise ValueError(f'{field}: 유효한 색상을 입력하세요.')
                    target[field] = val
                elif field in ('bold','enabled'):
                    target[field] = bool(val)
                elif field == 'align' and val in ('left','center','right'):
                    target[field] = val
                elif field == 'fit' and val in ('contain','cover'):
                    target[field] = val
                elif field == 'font' and val in ('sans','serif'):
                    target[field] = val
                elif field == 'text':
                    target[field] = str(val)[:1000]
                elif field == 'asset_id' and key == 'logo':
                    from .storage import valid_id
                    target[field] = valid_id(val) if val else None
        elif key == 'theme' and obj in ('dark','light','minimal'):
            base[key] = obj
        elif key == 'background_asset_id':
            from .storage import valid_id
            base[key] = valid_id(obj) if obj else None
        elif key == 'background_image_fit' and obj in ('contain','cover'):
            base[key] = obj
    return base


def clip(value, source_duration):
    if not isinstance(value,dict):
        raise ValueError('클립은 객체 형식이어야 합니다.')
    start = number(value.get('start', 0), 0, source_duration, '시작')
    end = number(value.get('end', source_duration), 0, source_duration, '종료')
    if end <= start + .05:
        raise ValueError('종료 시각은 시작보다 최소 0.05초 뒤여야 합니다.')
    cuts = []
    if not isinstance(value.get('cuts',[]),list) or len(value.get('cuts',[]))>10000:
        raise ValueError('삭제 목록의 형식 또는 개수를 확인하세요.')
    for item in value.get('cuts', []):
        if not isinstance(item,dict):
            raise ValueError('삭제 구간의 시작·종료 시각을 확인하세요.')
        a = number(item['start'], start, end, '삭제 시작')
        b = number(item['end'], start, end, '삭제 종료')
        if b <= a:
            raise ValueError('삭제 구간의 종료가 시작보다 뒤여야 합니다.')
        cuts.append({'start': a, 'end': b})
    identifier = str(value.get('id') or uid())
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',identifier):
        raise ValueError('클립 ID 형식이 올바르지 않습니다.')
    result = dict(id=identifier, title=str(value.get('title') or '새 클립')[:1000],
                  start=start, end=end, speed=number(value.get('speed', 1), .5, 2, '배속'),
                  cuts=cuts, style=style(value.get('style', {})),
                  subtitles_enabled=bool(value.get('subtitles_enabled', True)))
    from .timeline import duration
    if duration(result) < .05:
        raise ValueError('삭제 후 남는 영상 구간이 없습니다.')
    for k in ('template_id', 'template_version'):
        if k in value:
            result[k] = copy.deepcopy(value[k])
    return result
