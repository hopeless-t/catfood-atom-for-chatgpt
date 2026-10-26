#!/usr/bin/env python3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
h=(ROOT/'extension/analysis.html').read_text()
j=(ROOT/'extension/analysis.js').read_text()
p=(ROOT/'extension/popup.html').read_text()
pj=(ROOT/'extension/popup.js').read_text()
readme=(ROOT/'README.md').read_text()
for term in ('TTFB-like proxy','Request burst','Interaction latency','Max frame gap','DOM mutations','Long Task','Jank','HTTP 429'):
    assert term in h or term in j, term
for phrase in ('Plain meaning:','What is slowing ChatGPT right now?','Recent event timeline','Glossary'):
    assert phrase in h, phrase
assert 'Open Analysis' in p
assert 'chrome.runtime.getURL("analysis.html")' in pj
assert 'Not enough data yet.' in j
assert 'technical term visible' in readme
assert 'Conversation content is not collected.' in p
print('PASS analysis UI technical-term + plain-language boundary')
