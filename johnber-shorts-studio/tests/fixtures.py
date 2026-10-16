"""Own deterministic audiovisual test content, never reference UI footage."""
from array import array
import math
from pathlib import Path
import subprocess
import wave

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / '.local' / 'sample-input'
OUTPUT = ROOT / '.local' / 'sample-output'


def run(args, **kw):
    return subprocess.run(args, check=True, capture_output=True, timeout=120, **kw)


def generate():
    INPUT.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    source = INPUT / '한글 공백 동기화 원본.mp4'
    audio = INPUT / 'deterministic-audio.wav'
    if not source.is_file():
        samples = array('h')
        for i in range(480000):
            t = i / 48000
            pulse = any(event <= t < event + .2 for event in (1, 3, 7, 9))
            amplitude = 0 if 4 <= t < 6 else .7 if pulse else .04
            frequency = 880 if pulse else 220
            samples.append(round(32767 * amplitude * math.sin(2 * math.pi * frequency * t)))
        with wave.open(str(audio), 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(48000)
            wav.writeframes(samples.tobytes())
        # Four corner markers and four white audiovisual pulse markers. The
        # background changes at 2s intervals; time is visible to frame reviewers.
        font = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
        filters = [
            'drawbox=x=80:y=70:w=480:h=220:color=0x153b59:t=fill:enable=between(t\\,2\\,4)',
            'drawbox=x=80:y=70:w=480:h=220:color=0x493361:t=fill:enable=between(t\\,6\\,8)',
            'drawbox=x=0:y=0:w=45:h=45:color=red:t=fill',
            'drawbox=x=595:y=0:w=45:h=45:color=lime:t=fill',
            'drawbox=x=0:y=315:w=45:h=45:color=blue:t=fill',
            'drawbox=x=595:y=315:w=45:h=45:color=yellow:t=fill',
            'drawbox=x=270:y=150:w=100:h=60:color=white:t=fill:enable=between(t\\,1\\,1.1999)+between(t\\,3\\,3.1999)+between(t\\,7\\,7.1999)+between(t\\,9\\,9.1999)',
            f"drawtext=fontfile={font}:text='SOURCE %{{pts\\:hms}}':x=120:y=260:fontsize=24:fontcolor=white",
        ]
        run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i', 'color=c=0x182433:s=640x360:r=30:d=10', '-i', str(audio), '-vf', ','.join(filters), '-c:v', 'libx264', '-preset', 'veryfast', '-threads', '2', '-crf', '16', '-c:a', 'aac', '-b:a', '192k', '-pix_fmt', 'yuv420p', '-t', '10', '-movflags', '+faststart', '-y', str(source)])
    srt = INPUT / '수동 테스트 자막.srt'
    srt.write_text('''1
00:00:00,200 --> 00:00:00,800
SOXL · TQQQ · SCHD / 3.07% / 0.1%p
1,000,000원 / 길이가 긴 한글 테스트 문장

2
00:00:01,000 --> 00:00:01,200
첫 번째 동기화 표식

3
00:00:03,000 --> 00:00:03,200
두 번째 동기화 표식

4
00:00:07,000 --> 00:00:07,200
세 번째 동기화 표식

5
00:00:09,000 --> 00:00:09,200
네 번째 동기화 표식
''', encoding='utf-8-sig')
    return source, srt


if __name__ == '__main__':
    print(generate())
