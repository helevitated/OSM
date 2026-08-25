import json
import urllib.request
import urllib.parse

def check_grammar(text):
    url = "https://api.languagetool.org/v2/check"
    data = urllib.parse.urlencode({'language': 'en-US', 'text': text}).encode('utf-8')
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req) as response:
        res = json.loads(response.read().decode('utf-8'))
        return len([m for m in res.get('matches', []) if m['rule']['id'] != 'UPPERCASE_SENTENCE_START'])

print(check_grammar("put it over their with there things"))
print(check_grammar("put it over there with their things"))
