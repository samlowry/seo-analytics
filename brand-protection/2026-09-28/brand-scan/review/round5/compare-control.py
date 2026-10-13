"""Sonnet control verdicts vs round 4 (violator yes/no). Run from this folder: python3 compare-control.py"""
import json
truth = json.load(open("control-truth.json"))
got = {}
for f in ("verdicts-control-1.json", "verdicts-control-2.json"):
    for v in json.load(open(f)):
        got[v["domain"]] = v
missing = sorted(set(truth) - set(got))
same = [d for d in truth if d in got and got[d].get("violator") is not None and got[d]["violator"] == truth[d]]
diff = [d for d in truth if d in got and got[d].get("violator") is not None and got[d]["violator"] != truth[d]]
unsure = [d for d in truth if d in got and got[d].get("violator") is None]
print(f"agree {len(same)}/{len(same) + len(diff)}, unsure {len(unsure)}, missing {len(missing)}")
print("round-4 refuted:", sum(1 for d in truth if not truth[d]), "sonnet caught:",
      sum(1 for d in truth if not truth[d] and got.get(d, {}).get("violator") is False))
for d in diff:
    print(f"  {d}: round4={truth[d]} sonnet={got[d]['violator']} — {got[d].get('comment', '')[:160]}")
