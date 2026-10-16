from __future__ import annotations

import copy
import hashlib
import json
import shutil
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import storage as db

POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix='johnber-worker')
CANCELS = {}
ACTIVE = {'queued', 'running'}


def initialize():
    for obj in db.listing('jobs'):
        if obj['state'] in ACTIVE:
            obj.update(state='interrupted', stage='서버가 재시작되었습니다. 재시도할 수 있습니다.',
                       error='SERVER_RESTART: 처리 도중 서버가 종료되었습니다.', updated_at=db.now())
            db.write('jobs', obj)


def public(job):
    return {k:v for k,v in job.items() if k not in ('input', 'fingerprint')}


def enqueue(project, request):
    kind = request.get('kind')
    if kind not in ('render','preview','recommend','transcribe','silence'):
        raise ValueError('지원하지 않는 작업입니다.')
    ids = request.get('clip_ids') or [x['id'] for x in project['clips']]
    if kind in ('render','preview','silence'):
        if not ids or any(i not in {c['id'] for c in project['clips']} for i in ids):
            raise ValueError('출력할 클립을 선택하세요.')
    settings = request.get('settings') or {}
    if any('key' in k.lower() or 'token' in k.lower() for k in settings):
        raise ValueError('API 키는 서버 환경변수에 설정해 주세요.')
    if settings.get('provider') == 'remote' and not settings.get('consent_external'):
        raise ValueError('외부 API로 음성/전사문을 전송하려면 비용·전송 동의가 필요합니다.')
    if kind == 'transcribe' and settings.get('provider') not in ('local','remote'):
        raise ValueError('전사 엔진을 선택하세요.')
    content = {'project':project, 'request':{**request, 'clip_ids':ids}}
    fingerprint = hashlib.sha256(json.dumps(content,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    with db.LOCK:
        for existing in db.listing('jobs'):
            if existing['state'] in ACTIVE and existing.get('fingerprint') == fingerprint:
                return public(existing)
        job = dict(id=db.uid(),project_id=project['id'],kind=kind,state='queued',progress=None,
                   stage='대기 중',error=None,artifacts=[],result={},created_at=db.now(),updated_at=db.now(),
                   fingerprint=fingerprint,input=copy.deepcopy(content))
        db.write('jobs',job)
        event = threading.Event()
        CANCELS[job['id']] = event
        POOL.submit(run,job['id'],event)
    return public(job)


def update(identifier, **changes):
    with db.LOCK:
        job = db.read('jobs',identifier)
        job.update(changes, updated_at=db.now())
        db.write('jobs',job)


def artifact(path, filename, kind, job, clip_id=None):
    identifier = db.uid()
    meta = dict(id=identifier,filename=filename,kind=kind,url=f'/api/artifacts/{identifier}',
                path=path.relative_to(db.DATA).as_posix(),project_id=job['project_id'],job_id=job['id'],
                clip_id=clip_id,created_at=db.now())
    db.write('artifacts',meta)
    return {k:v for k,v in meta.items() if k != 'path'}


def run(identifier, cancel):
    job = db.read('jobs',identifier)
    if cancel.is_set():
        update(identifier,state='cancelled',stage='취소됨')
        CANCELS.pop(identifier,None)
        return
    update(identifier,state='running',stage='준비 중',started_at=db.now())
    project = job['input']['project']
    request = job['input']['request']
    settings = request.get('settings',{})
    source = db.source_path(project)
    work = db.DATA / 'work' / identifier
    work.mkdir(parents=True,exist_ok=True)

    def progress(value=None,message=None):
        update(identifier,progress=value,stage=message or db.read('jobs',identifier)['stage'])

    try:
        if not source.is_file():
            raise FileNotFoundError('원본 영상이 없습니다. 프로젝트 파일만 옮긴 경우 원본도 복원해야 합니다.')
        from . import media, timeline, ai
        if job['kind'] in ('render','preview'):
            clips = [c for c in project['clips'] if c['id'] in request['clip_ids']]
            outputs = []
            paths = []
            output_dir = db.DATA / 'outputs' / identifier
            output_dir.mkdir(parents=True,exist_ok=True)
            for index,clip in enumerate(clips):
                if cancel.is_set():
                    raise InterruptedError('취소됨')
                filename = f'{db.safe_name(project["title"],40)}_{index+1:02d}_{db.safe_name(clip["title"],65)}.mp4'
                path = output_dir / filename
                temp = work / f'{index}.mp4'
                progress(index/len(clips),f'{index+1}/{len(clips)} 영상 출력 중')
                meta = media.render(source,db.resolve_clip(clip),project['cues'],temp,work/str(index),
                    lambda v,*a: progress((index+(v or 0))/len(clips),f'{index+1}/{len(clips)} 인코딩 중'),cancel)
                if cancel.is_set():
                    raise InterruptedError('취소됨')
                if not temp.is_file() or temp.stat().st_size < 500:
                    raise RuntimeError('렌더러가 유효한 MP4 파일을 만들지 못했습니다.')
                temp.replace(path)
                item = artifact(path,filename,'mp4',job,clip['id'])
                item['media'] = meta
                outputs.append(item)
                paths.append(path)
                srt_path = path.with_suffix('.srt')
                from .subtitles import export
                srt_path.write_text(export(timeline.mapped_cues(clip,project['cues'])),encoding='utf-8-sig')
                outputs.append(artifact(srt_path,srt_path.name,'srt',job,clip['id']))
                text_path = path.with_suffix('.txt')
                text_path.write_text(clip['title']+'\n\n'+ '\n'.join(c['text'] for c in timeline.mapped_cues(clip,project['cues'])),encoding='utf-8')
                outputs.append(artifact(text_path,text_path.name,'txt',job,clip['id']))
                update(identifier,artifacts=outputs)
            if len(paths)>1:
                zip_path = output_dir / (db.safe_name(project['title'],60)+'_쇼츠.zip')
                with zipfile.ZipFile(zip_path,'w',compression=zipfile.ZIP_STORED) as archive:
                    for path in paths:
                        archive.write(path,path.name)
                outputs.append(artifact(zip_path,zip_path.name,'zip',job))
            update(identifier,artifacts=outputs,result={'revision':project['revision']},progress=1)
        elif job['kind'] == 'silence':
            clip = next(c for c in project['clips'] if c['id']==request['clip_ids'][0])
            progress(None,'무음 구간 감지 중 · 원본은 변경하지 않습니다')
            ranges = media.silence_ranges(source,clip['start'],clip['end'],
                threshold=float(settings.get('threshold',-35)),min_duration=float(settings.get('min_duration',.5)),
                padding=float(settings.get('padding',.12)),cancel=cancel)
            update(identifier,result={'ranges':ranges,'clip_id':clip['id']})
        elif job['kind'] == 'recommend':
            progress(None,'전사문에서 구간 후보 분석 중')
            candidates = ai.recommend(project['cues'],project['source']['duration'],db.DATA/'cache',settings,progress,cancel)
            update(identifier,result={'candidates':candidates})
        elif job['kind'] == 'transcribe':
            cues = ai.transcribe(source,db.DATA/'cache',settings,progress,cancel)
            if cancel.is_set():
                raise InterruptedError('취소됨')
            from .subtitles import validate
            cues = validate(cues,project['source']['duration'])
            with db.LOCK:
                current = db.read('projects',project['id'])
                if current['cues'] != project['cues']:
                    update(identifier,result={'cues':cues,'applied':False,
                        'message':'전사는 완료됐지만 자막을 편집한 내용이 있어 자동 적용하지 않았습니다. 결과를 확인하고 직접 적용해 주세요.'})
                else:
                    previous = copy.deepcopy(current)
                    current['cues'] = cues
                    current['original_cues'] = copy.deepcopy(cues)
                    current['transcript_engine'] = settings.get('provider')
                    db.save_project(current,previous)
                    update(identifier,result={'cues_count':len(cues),'applied':True})
        if cancel.is_set():
            raise InterruptedError('취소됨')
        update(identifier,state='succeeded',progress=1,stage='완료',finished_at=db.now())
    except Exception as exc:
        cancelled = cancel.is_set() or isinstance(exc,InterruptedError) or type(exc).__name__=='CancelledError'
        error = None if cancelled else f'{type(exc).__name__}: {str(exc)[:2400]}'
        # Do not persist secrets even if a provider/library includes one in an exception.
        import os
        key = os.environ.get('JOHNBER_API_KEY')
        if key and error:
            error = error.replace(key,'[REDACTED]')
        update(identifier,state='cancelled' if cancelled else 'failed',stage='취소됨' if cancelled else '실패 · 원인을 확인하고 재시도하세요',
               error=error,finished_at=db.now())
    finally:
        shutil.rmtree(work,ignore_errors=True)
        CANCELS.pop(identifier,None)


def cancel(identifier):
    with db.LOCK:
        job = db.read('jobs',identifier)
        if job['state'] in ACTIVE:
            event = CANCELS.get(identifier)
            if event:
                event.set()
            if job['state']=='queued':
                update(identifier,state='cancelled',stage='대기 작업 취소됨')
            else:
                update(identifier,stage='취소 요청 · 처리 프로세스를 종료하는 중')
    return public(db.read('jobs',identifier))
