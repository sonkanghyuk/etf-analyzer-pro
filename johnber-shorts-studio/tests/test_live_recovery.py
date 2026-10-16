"""Opt-in actual local server crash/restart test (kills ONLY its own process group).

JOHNBER_LIVE_TESTS=1 python -m unittest tests.test_live_recovery -v
Linux/macOS process-group crash injection; never sends user media or external API.
"""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import unittest

import httpx
from tests.fixtures import generate, OUTPUT


@unittest.skipUnless(os.environ.get('JOHNBER_LIVE_TESTS')=='1' and os.name=='posix',
                     'Actual process crash injection is opt-in and POSIX only')
class LiveRecoveryTests(unittest.TestCase):
    def test_crash_restart_restore_and_retry(self):
        source,srt = generate()
        root = Path(__file__).resolve().parents[1]
        data = root/'.local'/'recovery-test-data'
        data.mkdir(parents=True,exist_ok=True)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0))
            port=sock.getsockname()[1]
        base=f'http://127.0.0.1:{port}'
        env={**os.environ,'JOHNBER_PORT':str(port),'JOHNBER_DATA_DIR':str(data),'JOHNBER_API_KEY':''}
        log=(OUTPUT/'live-recovery-server.log').open('wb')
        child=None

        def start():
            p=subprocess.Popen([sys.executable,'-u','run.py'],cwd=root,env=env,stdout=log,stderr=log,start_new_session=True)
            for _ in range(100):
                if p.poll() is not None:
                    self.fail('Local test server exited before readiness')
                try:
                    if httpx.get(base+'/api/health',trust_env=False,timeout=.5).status_code==200:
                        return p
                except httpx.HTTPError:
                    pass
                time.sleep(.1)
            self.fail('Local test server did not become ready')

        def request(method,url,**kwargs):
            with httpx.Client(base_url=base,trust_env=False,timeout=30) as client:
                r=client.request(method,url,**kwargs)
            self.assertEqual(r.status_code,200,r.text)
            return r

        try:
            child=start()
            with source.open('rb') as f:
                p=request('POST','/api/projects',data={'title':'실제 재시작 검수'},files={'file':(source.name,f,'video/mp4')}).json()
            p['clips'][0].update(title='서버 종료 후 복원',end=10)
            p=request('PUT',f'/api/projects/{p["id"]}',json=p).json()
            job=request('POST',f'/api/projects/{p["id"]}/jobs',json={'kind':'render','clip_ids':[p['clips'][0]['id']]}).json()
            for _ in range(100):
                job=request('GET',f'/api/jobs/{job["id"]}').json()
                if job['state']=='running':
                    break
                time.sleep(.05)
            self.assertEqual(job['state'],'running')
            os.killpg(child.pid,signal.SIGKILL)
            child.wait(timeout=10)
            child=start()
            restored=request('GET',f'/api/projects/{p["id"]}').json()
            self.assertEqual(restored['clips'][0]['title'],'서버 종료 후 복원')
            job=request('GET',f'/api/jobs/{job["id"]}').json()
            self.assertEqual(job['state'],'interrupted')
            retry=request('POST',f'/api/jobs/{job["id"]}/retry').json()
            for _ in range(600):
                retry=request('GET',f'/api/jobs/{retry["id"]}').json()
                if retry['state'] not in ('queued','running'):
                    break
                time.sleep(.1)
            self.assertEqual(retry['state'],'succeeded',retry.get('error'))
            media=[a for a in retry['artifacts'] if a['kind']=='mp4']
            self.assertEqual(len(media),1)
            self.assertGreater(len(request('GET',media[0]['url']).content),10000)
            (OUTPUT/'live-recovery-result.json').write_text(json.dumps({'project_id':p['id'],'interrupted_job':job['id'],
                'retry_job':retry['id'],'state':retry['state'],'source_hash':restored['source']['hash'],
                'method':'Killed only test process group, restarted actual Uvicorn, retrieved project/job, retried actual MP4'},ensure_ascii=False,indent=2),encoding='utf-8')
        finally:
            if child and child.poll() is None:
                os.killpg(child.pid,signal.SIGTERM)
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid,signal.SIGKILL)
                    child.wait(timeout=5)
            log.close()


if __name__=='__main__':
    unittest.main()
