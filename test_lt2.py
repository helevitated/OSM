import json
import urllib.request
import urllib.parse
import re

text = "put it over there with there things"
url = "https://api.languagetool.org/v2/check"
data = urllib.parse.urlencode({'language': 'en-US', 'text': text}).encode('utf-8')
req = urllib.request.Request(url, data=data)
req.add_header('User-Agent', 'g2p_cli_shavian_tool/1.0')
with urllib.request.urlopen(req) as response:
    res = json.loads(response.read().decode('utf-8'))
    for m in res.get('matches', []):
        print(f"Match: {m['rule']['id']} at {m['offset']}:{m['offset']+m['length']}")
        print(f"Replacements: {[r['value'] for r in m.get('replacements', [])]}")
