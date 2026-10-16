from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import threading
from io import BytesIO
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import storage as db, subtitles, jobs, media, ai, validation

MAX_UPLOAD = int(os.environ.get('JOHNBER_MAX_UPLOAD_MB', '4096')) * 1024 * 1024
MAX_DURATION = float(os.environ.get('JOHNBER_MAX_DURATION_SECONDS', '14400'))
FRAME_LOCK = threading.Lock()


@asynccontextmanager
async def lifespan(app):
    db.DATA.mkdir(parents=True,exist_ok=True)
    jobs.initialize()
    if not db.listing('templates'):
        for name,theme in [('깊은 밤 · 강의 보존형','dark'),('페이퍼 · 자료 가독형','light'),('포커스 · 미니멀 강의형','minimal')]:
            db.write('templates',dict(id=db.uid(),name=name,version=1,style=media.default_style(theme),created_at=db.now()))
    yield
    for event in list(jobs.CANCELS.values()):
        event.set()


app = FastAPI(title='존버나드 쇼츠 스튜디오',version='0.1.0',lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware,allowed_hosts=['localhost','127.0.0.1','[::1]','testserver'])


@app.middleware('http')
async def local_origin(request: Request,call_next):
    origin = request.headers.get('origin')
    if origin and origin != 'null':
        # Exact origin (including port) prevents a malicious unrelated localhost page submitting work.
        expected = f'{request.url.scheme}://{request.headers.get("host", "")}'
        if origin != expected:
            return JSONResponse({'detail':'다른 웹사이트에서 이 로컬 앱에 접근할 수 없습니다.'},status_code=403)
    elif origin == 'null':
        return JSONResponse({'detail':'앱 주소에서 직접 열어 주세요.'},status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Frame-Options'] = 'DENY'
    return response


@app.exception_handler(ValueError)
async def bad_value(request,exc):
    return JSONResponse({'detail':str(exc)},status_code=400)


@app.exception_handler(FileNotFoundError)
async def not_found(request,exc):
    return JSONResponse({'detail':str(exc)},status_code=404)


@app.exception_handler(KeyError)
async def missing_field(request,exc):
    return JSONResponse({'detail':f'필수 항목이 없습니다: {exc.args[0]}'},status_code=400)


def get_project(identifier):
    return db.read('projects',identifier)


def check_revision(body,project):
    if body.get('revision') != project['revision']:
        raise HTTPException(409,'다른 창이나 작업이 프로젝트를 변경했습니다. 다시 열고 저장해 주세요.')


def frame_key(project,clip,time):
    return hashlib.sha256(json.dumps(['baseline-v2',project['id'],project['revision'],clip,float(time)],sort_keys=True).encode()).hexdigest()


@app.get('/api/health')
def health():
    return dict(app='Johnber Shorts Studio',schema_version=1,ffmpeg=bool(shutil.which('ffmpeg')),
                ffprobe=bool(shutil.which('ffprobe')),ai=ai.status(),
                fonts=media.font_status(),
                limits={'upload_mb':MAX_UPLOAD//1024//1024,'duration_seconds':MAX_DURATION})


@app.get('/api/projects')
def list_projects():
    return db.listing('projects')


@app.post('/api/projects')
async def create_project(file: UploadFile=File(...),title: str=Form('새 프로젝트')):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise ValueError('FFmpeg/ffprobe가 없습니다. README의 공식 설치 절차를 확인해 주세요.')
    if Path(file.filename or '').suffix.lower() not in ('.mp4','.mov','.mkv','.webm','.m4v'):
        raise ValueError('MP4, MOV, MKV, WEBM, M4V 영상 파일을 선택해 주세요.')
    tmp = db.DATA/'tmp'/(db.uid()+'.upload')
    tmp.parent.mkdir(parents=True,exist_ok=True)
    total, digest = 0, hashlib.sha256()
    try:
        with tmp.open('wb') as f:
            while block := await file.read(1024*1024):
                total += len(block)
                if total > MAX_UPLOAD:
                    raise ValueError(f'설정된 업로드 한도 {MAX_UPLOAD//1024//1024}MB를 초과했습니다.')
                digest.update(block)
                f.write(block)
        if total == 0:
            raise ValueError('빈 파일입니다.')
        try:
            info = media.probe(tmp)
        except Exception as exc:
            raise ValueError('영상을 읽을 수 없습니다. 손상되었거나 실제 영상 형식이 아닙니다.') from exc
        if info['duration'] > MAX_DURATION or info['duration'] <= 0:
            raise ValueError(f'원본 길이는 0초 초과 {MAX_DURATION:g}초 이하여야 합니다.')
        identifier = digest.hexdigest()
        source = db.DATA/'sources'/(identifier+'.media')
        source.parent.mkdir(parents=True,exist_ok=True)
        if not source.exists():
            tmp.replace(source)
        project = dict(id=db.uid(),schema_version=1,title=title[:200] or '새 프로젝트',created_at=db.now(),
                       source={**info,'asset_id':identifier,'hash':identifier,'filename':Path(file.filename).name,'size_bytes':total},
                       cues=[],original_cues=[],clips=[],transcript_engine='manual')
        project['clips'] = [validation.clip({'title':'첫 번째 쇼츠','start':0,'end':min(info['duration'],60)},info['duration'])]
        return db.save_project(project)
    finally:
        tmp.unlink(missing_ok=True)
        await file.close()


@app.post('/api/projects/import')
async def import_project(file:UploadFile=File(...)):
    data = await file.read(10*1024*1024+1)
    if len(data)>10*1024*1024:
        raise ValueError('프로젝트 JSON은 10MB 이하여야 합니다.')
    try:
        p = json.loads(data.decode('utf-8-sig'))
    except (ValueError,UnicodeError):
        raise ValueError('유효한 프로젝트 JSON이 아닙니다.')
    if p.get('schema_version') != 1:
        raise ValueError('지원하지 않는 프로젝트 버전입니다.')
    if not db.source_path(p).is_file():
        raise ValueError('이 컴퓨터에 원본 영상이 없습니다. 같은 원본을 먼저 업로드한 뒤 프로젝트를 불러와 주세요. JSON에는 영상이 포함되지 않습니다.')
    info = media.probe(db.source_path(p))
    p['source'] = {**p['source'],**info}
    p['cues'] = subtitles.validate(p.get('cues',[]),info['duration'])
    p['original_cues'] = subtitles.validate(p.get('original_cues',[]),info['duration'])
    p['clips'] = [validation.clip(c,info['duration']) for c in p.get('clips',[])]
    p['id'] = db.uid()
    p['title'] = str(p.get('title','가져온 프로젝트'))[:200]
    p['created_at'] = db.now()
    return db.save_project(p)


@app.get('/api/projects/{identifier}')
def read_project(identifier:str):
    return get_project(identifier)


@app.put('/api/projects/{identifier}')
def update_project(identifier:str,body:dict):
    with db.LOCK:
        p = get_project(identifier)
        check_revision(body,p)
        previous = copy.deepcopy(p)
        if 'title' in body:
            p['title'] = str(body['title'])[:200]
        if 'cues' in body:
            p['cues'] = subtitles.validate(body['cues'],p['source']['duration'])
        if 'clips' in body:
            if len(body['clips'])>100:
                raise ValueError('프로젝트당 클립은 최대 100개입니다.')
            p['clips'] = [validation.clip(c,p['source']['duration']) for c in body['clips']]
            if len({c['id'] for c in p['clips']}) != len(p['clips']):
                raise ValueError('클립 ID가 중복됩니다.')
        return db.save_project(p,previous)


@app.post('/api/projects/{identifier}/duplicate')
def duplicate_project(identifier:str):
    return db.duplicate(get_project(identifier))


@app.delete('/api/projects/{identifier}')
def delete_project(identifier:str):
    with db.LOCK:
        p = get_project(identifier)
        db.atomic(db.DATA/'trash'/(p['id']+'.json'),p)
        db.location('projects',identifier).unlink()
    return {'deleted':True,'source_preserved':True}


@app.get('/api/projects/{identifier}/source')
def source_video(identifier:str):
    path = db.source_path(get_project(identifier))
    return FileResponse(path,media_type='video/mp4')


@app.get('/api/projects/{identifier}/thumbnail')
def source_thumbnail(identifier:str):
    p = get_project(identifier)
    image = db.DATA/'thumbnails'/(p['source']['asset_id']+'.jpg')
    image.parent.mkdir(parents=True,exist_ok=True)
    with FRAME_LOCK:
        if not image.is_file():
            media.source_thumbnail(db.source_path(p),image)
    return FileResponse(image,media_type='image/jpeg')


@app.post('/api/projects/{identifier}/logo')
@app.post('/api/projects/{identifier}/assets')
async def image_asset(identifier:str,file:UploadFile=File(...)):
    get_project(identifier)
    raw = await file.read(20*1024*1024+1)
    if len(raw)>20*1024*1024:
        raise ValueError('이미지는 20MB 이하여야 합니다.')
    from PIL import Image, ImageOps
    try:
        with Image.open(BytesIO(raw)) as im:
            if im.width*im.height>16000000:
                raise ValueError('이미지는 최대 1600만 픽셀까지 지원합니다.')
            im = ImageOps.exif_transpose(im).convert('RGBA')
            im.thumbnail((2160,3840))
            buf = BytesIO()
            im.save(buf,format='PNG')
            data = buf.getvalue()
    except (OSError,Image.DecompressionBombError) as exc:
        raise ValueError('읽을 수 있는 PNG/JPEG/WEBP 이미지를 선택해 주세요.') from exc
    asset_id = hashlib.sha256(data).hexdigest()
    path = db.DATA/'assets'/(asset_id+'.png')
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(data)
    db.write('image_assets',dict(id=asset_id,filename=db.safe_name(file.filename),provenance='사용자 업로드',created_at=db.now()))
    return {'asset_id':asset_id,'url':f'/api/assets/{asset_id}'}


@app.get('/api/assets/{identifier}')
def serve_image_asset(identifier:str):
    path = db.DATA/'assets'/(db.valid_id(identifier)+'.png')
    if not path.is_file():
        raise FileNotFoundError('이미지가 없습니다.')
    return FileResponse(path,media_type='image/png')


@app.get('/api/projects/{identifier}/json')
def project_json(identifier:str):
    p = get_project(identifier)
    return FileResponse(db.location('projects',identifier),media_type='application/json',filename=db.safe_name(p['title'])+'.json')


@app.post('/api/projects/{identifier}/clips')
def add_clip(identifier:str,body:dict):
    with db.LOCK:
        p = get_project(identifier)
        previous = copy.deepcopy(p)
        if len(p['clips'])>=100:
            raise ValueError('클립 한도 100개를 초과했습니다.')
        p['clips'].append(validation.clip(body,p['source']['duration']))
        return db.save_project(p,previous)


@app.post('/api/projects/{identifier}/subtitles')
async def upload_subtitles(identifier:str,file:UploadFile=File(...)):
    data = await file.read(5*1024*1024+1)
    if len(data)>5*1024*1024:
        raise ValueError('자막 파일은 5MB 이하여야 합니다.')
    with db.LOCK:
        p = get_project(identifier)
        previous = copy.deepcopy(p)
        cues = subtitles.parse(data,p['source']['duration'])
        p.update(cues=cues,original_cues=copy.deepcopy(cues),transcript_engine='imported')
        return db.save_project(p,previous)


@app.get('/api/projects/{identifier}/frame')
def frame(identifier:str,clip_id:str,time:float=0,rev:str=''):
    p = get_project(identifier)
    clip = next((c for c in p['clips'] if c['id']==clip_id),None)
    if not clip:
        raise ValueError('클립을 선택하세요.')
    from .timeline import duration
    time = validation.number(time,0,duration(clip),'미리보기 시각')
    fingerprint = frame_key(p,clip,time)
    image = db.DATA/'frames'/(fingerprint+'.png')
    image.parent.mkdir(parents=True,exist_ok=True)
    with FRAME_LOCK:
        if not image.is_file():
            meta = media.preview_frame(db.source_path(p),db.resolve_clip(clip),p['cues'],image,time)
            db.atomic(image.with_suffix('.json'),meta)
    response = FileResponse(image,media_type='image/png')
    response.headers['Cache-Control'] = 'no-cache'
    if image.with_suffix('.json').is_file():
        info = json.loads(image.with_suffix('.json').read_text(encoding='utf-8'))
        response.headers['X-Johnber-Warnings'] = quote(json.dumps(info.get('warnings',[]),ensure_ascii=False))
    return response


@app.get('/api/projects/{identifier}/frame-info')
def frame_info(identifier:str,clip_id:str,time:float=0):
    p = get_project(identifier)
    c = next((c for c in p['clips'] if c['id']==clip_id),None)
    if not c:
        raise ValueError('클립을 선택하세요.')
    fingerprint = frame_key(p,c,time)
    path = db.DATA/'frames'/(fingerprint+'.json')
    if not path.is_file():
        frame(identifier,clip_id,time)
    meta = json.loads(path.read_text(encoding='utf-8'))
    return {k:v for k,v in meta.items() if k != 'path'}


@app.post('/api/projects/{identifier}/jobs')
def start_job(identifier:str,body:dict):
    return jobs.enqueue(get_project(identifier),body)


@app.post('/api/projects/{identifier}/apply-candidates')
def apply_candidates(identifier:str,body:dict):
    with db.LOCK:
        p = get_project(identifier)
        previous = copy.deepcopy(p)
        for candidate in body.get('candidates',[]):
            c = validation.clip(candidate,p['source']['duration'])
            p['clips'].append(c)
        if len(p['clips'])>100:
            raise ValueError('클립은 최대 100개입니다.')
        return db.save_project(p,previous)


@app.get('/api/jobs')
def list_jobs():
    return [jobs.public(j) for j in db.listing('jobs')]


@app.get('/api/jobs/{identifier}')
def read_job(identifier:str):
    return jobs.public(db.read('jobs',identifier))


@app.post('/api/jobs/{identifier}/cancel')
def cancel_job(identifier:str):
    return jobs.cancel(identifier)


@app.post('/api/jobs/{identifier}/retry')
def retry_job(identifier:str):
    job = db.read('jobs',identifier)
    if job['state'] not in ('failed','cancelled','interrupted'):
        raise ValueError('실패·취소·중단된 작업만 재시도할 수 있습니다.')
    return jobs.enqueue(get_project(job['project_id']),job['input']['request'])


@app.get('/api/templates')
def list_templates():
    return db.listing('templates')


@app.post('/api/templates')
def create_template(body:dict):
    return db.write('templates',dict(id=db.uid(),name=str(body.get('name','새 템플릿'))[:200],
        style=validation.style(body['style']),version=1,schema_version=1,created_at=db.now()))


@app.put('/api/templates/{identifier}')
def update_template(identifier:str,body:dict):
    with db.LOCK:
        obj = db.read('templates',identifier)
        db.atomic(db.DATA/'template_history'/identifier/f'{obj["version"]}.json',obj)
        obj.update(name=str(body.get('name',obj['name']))[:200],style=validation.style(body.get('style',obj['style'])),
                   version=obj['version']+1,updated_at=db.now())
        return db.write('templates',obj)


@app.delete('/api/templates/{identifier}')
def delete_template(identifier:str):
    db.read('templates',identifier)
    db.location('templates',identifier).unlink()
    return {'deleted':True}


@app.get('/api/artifacts/{identifier}')
def download_artifact(identifier:str):
    item = db.read('artifacts',identifier)
    path = (db.DATA/item['path']).resolve()
    if not path.is_relative_to(db.DATA) or not path.is_file():
        raise FileNotFoundError('완성된 파일을 찾을 수 없습니다.')
    return FileResponse(path,filename=item['filename'],media_type={'mp4':'video/mp4','zip':'application/zip','srt':'text/plain'}.get(item['kind'],'text/plain'))


app.mount('/static',StaticFiles(directory=Path(__file__).parent/'static'),name='static')
app.mount('/',StaticFiles(directory=Path(__file__).parent/'static',html=True),name='web')
