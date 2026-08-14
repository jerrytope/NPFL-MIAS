"""Quick API test. Run via: python tools/test_api.py"""
import urllib.request
import json

def test_endpoint(url, label):
    print(f'\n=== {label} ===')
    print(f'GET {url}')
    r = urllib.request.urlopen(url)
    data = json.loads(r.read())
    if 'count' in data:
        print(f'Count: {data["count"]}')
        print(f'Snapshot: {data["snapshot"]["version_label"]}')
        for p in data['results'][:5]:
            print(f'  {p["home"]} vs {p["away"]}: {p["predicted_result"]} ({p["confidence"]}%)')
        if data['count'] > 5:
            print(f'  ... and {data["count"] - 5} more')
    elif 'snapshots' in data:
        for s in data['snapshots']:
            print(f'  ID={s["id"]} {s["version_label"]} latest={s["is_latest"]} predictions={s["prediction_count"]}')
    else:
        print(json.dumps(data, indent=2))

BASE = 'http://127.0.0.1:8000/supercomputer/api'

test_endpoint(f'{BASE}/snapshots/', 'All Snapshots')
test_endpoint(f'{BASE}/predictions/?match_day=1', 'Match Day 1')
test_endpoint(f'{BASE}/predictions/?team=Enyimba', 'Team: Enyimba')
test_endpoint(f'{BASE}/predictions/?snapshot=1', 'Snapshot 1 (Pre-Season)')
test_endpoint(f'{BASE}/predictions/?match_day=5&team=Rivers+United', 'MD5 + Rivers United')
