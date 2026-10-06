
import json, urllib.request
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
targets = json.load(open("/tmp/probe-targets.json"))
results = {}
for name, url in targets.items():
    try:
        with opener.open(url, timeout=5) as response:
            results[name] = {"reachable": response.status == 200}
    except Exception as exc:
        results[name] = {"reachable": False, "exception": type(exc).__name__}
print(json.dumps(results))
