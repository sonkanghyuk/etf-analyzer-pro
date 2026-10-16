"""Actual upload/preview/export of user image assets and untrusted project boundaries."""
import copy
from io import BytesIO
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image
from studio import app as web, storage as db
from tests.fixtures import generate, OUTPUT
from tests.test_integration import decode_frame


class AssetBoundaryTests(unittest.TestCase):
    def test_safe_logo_and_background_roundtrip_to_real_mp4(self):
        source,_=generate()
        with tempfile.TemporaryDirectory(prefix='johnber-assets-') as temporary, patch.object(db,'DATA',Path(temporary)):
            with TestClient(web.app) as c:
                with source.open('rb') as f:
                    r=c.post('/api/projects',data={'title':'이미지 에셋 검수'},files={'file':('자체 제작 원본.mp4',f,'video/mp4')})
                self.assertEqual(r.status_code,200,r.text)
                p=r.json()
                ids=[]
                for color in ('#ff00ff','#244466'):
                    buf=BytesIO()
                    Image.new('RGB',(200,80),color).save(buf,format='PNG')
                    r=c.post(f'/api/projects/{p["id"]}/assets',files={'file':('사용자 이미지.png',buf.getvalue(),'image/png')})
                    self.assertEqual(r.status_code,200,r.text)
                    ids.append(r.json()['asset_id'])
                clip=p['clips'][0]
                clip['end']=1.5
                clip['style']['logo'].update(asset_id=ids[0],image_path='/etc/passwd',x=100,y=1750,w=200,h=80,text='')
                clip['style']['background_asset_id']=ids[1]
                r=c.put(f'/api/projects/{p["id"]}',json=p)
                self.assertEqual(r.status_code,200,r.text)
                p=r.json()
                self.assertNotIn('image_path',p['clips'][0]['style']['logo'])
                r=c.get(f'/api/projects/{p["id"]}/frame',params={'clip_id':clip['id'],'time':.4})
                self.assertEqual(r.status_code,200,r.text if r.status_code!=200 else '')
                preview=Image.open(BytesIO(r.content)).convert('RGB')
                self.assertEqual(preview.getpixel((150,1790)),(255,0,255))
                self.assertEqual(preview.getpixel((10,10)),(36,68,102))
                r=c.get(f'/api/projects/{p["id"]}/frame-info',params={'clip_id':clip['id'],'time':.4})
                self.assertEqual(r.status_code,200,r.text)
                self.assertIn('warnings',r.json())
                job=c.post(f'/api/projects/{p["id"]}/jobs',json={'kind':'render','clip_ids':[clip['id']]}).json()
                for _ in range(400):
                    job=c.get(f'/api/jobs/{job["id"]}').json()
                    if job['state'] not in ('queued','running'):
                        break
                    time.sleep(.1)
                self.assertEqual(job['state'],'succeeded',job.get('error'))
                item=next(a for a in job['artifacts'] if a['kind']=='mp4')
                path=OUTPUT/'user-assets-verified.mp4'
                path.write_bytes(c.get(item['url']).content)
                final=decode_frame(path,.4)
                for actual,expected in ((final.getpixel((150,1790)),(255,0,255)),(final.getpixel((10,10)),(36,68,102))):
                    self.assertLess(max(abs(a-b) for a,b in zip(actual,expected)),12)
                # Source/internal paths and HTML attributes cannot be smuggled through project JSON.
                bad=copy.deepcopy(p)
                bad['clips'][0]['id']='\"><script>alert(1)</script>'
                self.assertEqual(c.put(f'/api/projects/{p["id"]}',json=bad).status_code,400)
                bad=copy.deepcopy(p)
                bad['cues']=[{'id':'\" onclick=alert(1)','start':0,'end':1,'text':'untrusted input'}]
                self.assertEqual(c.put(f'/api/projects/{p["id"]}',json=bad).status_code,400)
                r=c.get('/api/assets/..%2F..%2Fetc%2Fpasswd')
                self.assertIn(r.status_code,(400,404))
                self.assertEqual(c.post(f'/api/projects/{p["id"]}/jobs',headers={'Origin':'https://bad.example'},json={'kind':'render'}).status_code,403)


if __name__=='__main__':
    unittest.main()
