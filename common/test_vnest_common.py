"""Offline checks for vnest_common (run: python -I common/test_vnest_common.py <repo_root>)."""
import json
import sys
from pathlib import Path

ROOT = Path(sys.argv[1])
sys.path.insert(0, str(ROOT / "common"))
import vnest_common as wc  # noqa: E402

out = ROOT / "vnest_dataset" / "out"
train, val, test = (wc.load_jsonl(out / f"{s}.jsonl") for s in ("train", "validation", "test"))

# 1. split rule
ov = wc.check_split_verbs(train, val, test)
assert not ov["train&val"] and not ov["train&test"] and not ov["val&test"], ov
assert tuple(ov["test_verbs"]) == wc.TEST_VERBS and tuple(ov["val_verbs"]) == wc.VALIDATION_VERBS, ov

# 2. every reference exercise is accepted and scores cleanly
items = wc.items_from_split(test, "test") + wc.items_from_split(val, "validation")
refs = wc.known_valid(items)
bad = []
for it in items:
    r = wc.score_output(it["ref_json"], it["verb"], refs[it["verb"]])
    if not r["accepted"] or r["copies_example"] or r["generic_who"] or not r["who_known_valid"] or not r["what_known_valid"]:
        bad.append((it["verb"], r))
assert not bad, bad[:3]
person = sum(wc.score_output(it["ref_json"], it["verb"], refs[it["verb"]])["who_is_person"] for it in items)
print(f"references: {len(items)}/{len(items)} accepted, 0 copy, 0 generic; who_is_person {person}/{len(items)}")

# 3. prompts rebuilt from items match the dataset prompts exactly
for rows, split in ((test, "test"), (val, "validation")):
    for r, it in zip(rows, wc.items_from_split(rows, split)):
        style = r["meta"]["prompt"]
        assert wc.prompt_for(style, it["verb"], it["avoid"]) == r["messages"][1]["content"], (style, it)
        assert r["messages"][0]["content"] == wc.SYSTEM_PROMPT
print("prompts: rebuilt prompts identical to the dataset (both styles, with avoid lists)")

# 4. known failure modes are caught
r_cook = refs["cook"]
copy = wc.EXAMPLE_JSON.replace("carpenter", "a person")  # Qwen's real failure: example + "a person"
s = wc.score_output(copy, "cook", r_cook)
assert s["accepted"] and s["copies_example"] and s["generic_who"] and not s["who_is_person"], s
prose = "Sure! Here is the exercise:\n```json\n" + test[0]["messages"][2]["content"] + "\n```"
s = wc.score_output(prose, test[0]["meta"]["verb"], refs[test[0]["meta"]["verb"]])
assert s["accepted"] and s["json_how"] == "embedded", s
three = json.loads(test[0]["messages"][2]["content"]); three["why"]["options"] = three["why"]["options"][:3]
assert wc.score_output(json.dumps(three), "x", {})["reject_reason"].startswith("why: fewer than 4")
missing = json.loads(test[0]["messages"][2]["content"]); missing["what"]["answer"] = "zebra"
assert "not one of the options" in wc.score_output(json.dumps(missing), "x", {})["reject_reason"]
assert wc.score_output("not json at all", "x", {})["reject_reason"] == "no JSON found"
same = {k: {"options": ["a b", "c", "d", "e"], "answer": "a b"} for k in wc.QUESTIONS}
assert wc.score_output(json.dumps(same), "x", {})["reject_reason"] == "who and what are the same"
long_opt = json.loads(test[0]["messages"][2]["content"]); long_opt["where"]["options"][1] = "one two three four five six seven"
assert "too long" in wc.score_output(json.dumps(long_opt), "x", {})["reject_reason"]
# a valid person offered as a wrong "who" is flagged
dis = json.loads(test[0]["messages"][2]["content"]); w = dis["who"]
w["options"] = [w["answer"], "teacher", "stone", "cloud"]
assert wc.score_output(json.dumps(dis), test[0]["meta"]["verb"], refs[test[0]["meta"]["verb"]])["bad_who_distractors"] == 1
print("failure modes: copy / generic who / prose-wrapped / 3 options / answer missing / no JSON / who==what / long option / bad distractor all detected")

# 5. naming round-trips and refuses '__'
rn = wc.run_name("b1", "qwen25-1.5b-instruct", "untuned")
assert wc.parse_run_name(rn) == {"exp": "b1", "model": "qwen25-1.5b-instruct", "variant": "untuned"}
pp = wc.preds_path("b1", "nb2.01", rn, "test", "long-schema")
assert wc.parse_preds_path(pp)["variant"] == "long-schema", pp
try:
    wc.run_name("b1", "bad__name", "x"); raise SystemExit("'__' accepted")
except ValueError:
    pass
print("naming:", rn, "|", pp)

# 6. summary + bootstrap run
import pandas as pd  # noqa: E402
rows = [{**wc.score_output(it["ref_json"], it["verb"], refs[it["verb"]]), "verb": it["verb"], "split": it["split"],
         "gen_tokens": 150} for it in items]
print(wc.summarise(pd.DataFrame(rows), ["split"])[["split", "n", "n_verbs", "accepted_pct", "accepted_ci", "who_is_person_pct"]].to_string(index=False))
print("ALL CHECKS PASSED, module", wc.VERSION)
