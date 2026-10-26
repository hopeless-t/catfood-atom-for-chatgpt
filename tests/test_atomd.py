#!/usr/bin/env python3
import json, subprocess, time, urllib.request, urllib.error
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=subprocess.Popen(['python3',str(ROOT/'atomd.py'),'--port','18766'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
try:
  for _ in range(30):
    try: json.load(urllib.request.urlopen('http://127.0.0.1:18766/health',timeout=.2));break
    except Exception: time.sleep(.05)
  def post(e):
    q=urllib.request.Request('http://127.0.0.1:18766/event',data=json.dumps(e).encode(),headers={'Content-Type':'application/json'},method='POST');urllib.request.urlopen(q).read()
  post({'kind':'net','stage':'start','category':'api','secret':'drop-me'})
  post({'kind':'net','stage':'headers','category':'api','ttfb_ms':20,'status':200})
  post({'kind':'net','stage':'end','category':'api','duration_ms':30,'status':200})
  s=json.load(urllib.request.urlopen('http://127.0.0.1:18766/snapshot'))
  assert s['network']['issued']==1 and s['network']['completed']==1
  e=json.load(urllib.request.urlopen('http://127.0.0.1:18766/events?limit=1'))['events'][0]
  assert 'secret' not in e
  print('PASS public observer')
finally:
  p.terminate();p.wait(timeout=3)
