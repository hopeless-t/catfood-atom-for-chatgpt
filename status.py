#!/usr/bin/env python3
import json, urllib.request
s=json.load(urllib.request.urlopen('http://127.0.0.1:8766/snapshot',timeout=1));n=s['network'];i=s['interaction'];r=s['render']
print('CATFOOD Atom for ChatGPT')
print('requests:',n['issued'],'issued /',n['completed'],'completed; peak',n['max_requests_1s'],'/s; max active',n['max_active'])
print('TTFB:',n['avg_ttfb_ms'],'ms; HTTP 429:',n['status_counts'].get('429',0))
print('input:',i['max_duration_ms'],'ms; queue:',i['max_input_delay_ms'],'ms')
print('render:',r['mutations'],'DOM updates;',r['long_task_ms'],'ms long tasks; max gap',r['max_gap_ms'],'ms')
for f in s['findings']: print('-',f['severity'],f['id'],f['detail'])
