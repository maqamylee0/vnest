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
# ===================================== per-part format (module 1.1.0, dataset v2) =====================================
import re  # noqa: E402

v2 = ROOT / "vnest_dataset" / "out_v2"
tr2, va2, te2 = (wc.load_jsonl(v2 / f"{s}.jsonl") for s in ("train", "validation", "test"))

# 7. app <-> scorer: the system line and the JSON rule are the app's (read from its source)
dart = (ROOT / "vnest_app" / "lib" / "services" / "llm_service.dart").read_text()
m = re.search(r"static const partSystemPrompt =(.*?);\n", dart, re.S)
dart_system = "".join(re.findall(r"'((?:[^'\\]|\\.)*)'", m.group(1)))
assert dart_system == wc.PART_SYSTEM_PROMPT, (dart_system, wc.PART_SYSTEM_PROMPT)
assert re.search(r"partTries = 3\b", dart) and wc.PART_TRIES == 3
assert re.search(r"_partMaxTokens = 48\b", dart) and wc.PART_MAX_NEW_TOKENS == 48
for f in wc.PART_FIELDS:
    assert f"'{f}'" in dart, f
print("app: system line, fields, tries and token limit identical to llm_service.dart")

# 8. v2 split rule + every example: system line, rebuilt prompt identical, reference accepted and clean
ov2 = wc.check_split_verbs(tr2, va2, te2)
assert not ov2["train&val"] and not ov2["train&test"] and not ov2["val&test"], ov2
assert tuple(ov2["test_verbs"]) == wc.TEST_VERBS and tuple(ov2["val_verbs"]) == wc.VALIDATION_VERBS, ov2
n = 0
for rows, split in ((tr2, "train"), (va2, "validation"), (te2, "test")):
    for r, it in zip(rows, wc.part_items_from_split(rows, split)):
        assert r["messages"][0]["content"] == wc.PART_SYSTEM_PROMPT
        assert wc.part_prompt(it["verb"], it["part"], it["done"], it["avoid"]) == r["messages"][1]["content"], (it, r)
        s = wc.score_part(it["ref_reply"], it["part"], it["verb"], {}, it["ref_answer"])
        assert s["accepted"] and s["answer_matches_ref"] and not s["echoes_instructions"] and not s["generic_who"], (it, s)
        n += 1
print(f"v2: {n} examples: system line, prompts rebuilt identically, every reference accepted, matches itself, clean")

# 9. the failures seen on the phone (Entry 8) are caught
P = lambda **k: json.dumps(k)  # noqa: E731
cases = {
    "copied hint as option (old shape)": ("who", json.dumps({"options": ["a person who often cooks something", "a chef", "a cook", "a person who cooks"], "answer": "a chef"}), "repeats the instructions"),
    "generic who": ("who", P(answer="a person", wrong1="a car", wrong2="a book", wrong3="a tree"), "not a particular kind of person"),
    "echoed instruction as answer": ("where", P(answer="the usual place", wrong1="the kitchen", wrong2="the microwave", wrong3="the oven"), "repeats the instructions"),
    "repeated options": ("when", P(answer="at night", wrong1="at night", wrong2="while sleeping", wrong3="while sleeping"), "fewer than 4 different options"),
    "cut-off JSON": ("who", '{"options": ["a cook", "a chef", "a teacher", "a parent", "a pa', "no JSON found"),
    "answer missing (old shape)": ("what", json.dumps({"options": ["egg", "rice", "soup", "bread"], "answer": "breakfast"}), "is not one of the options"),
    "option too long": ("why", P(answer="to eat", wrong1="to fly over the moon and back again", wrong2="to grow wings", wrong3="to stop the sun"), "too long"),
}
for name, (part, text, expect) in cases.items():
    s = wc.score_part(text, part, "cook", {})
    assert not s["accepted"] and expect in s["reject_reason"], (name, s)
ok = wc.score_part(P(answer="Chef.", wrong1="cloud", wrong2="candle", wrong3="cup"), "who", "cook", {"agents": {"chef"}}, "chef")
assert ok["accepted"] and ok["who_is_person"] and ok["who_known_valid"] and ok["answer_matches_ref"], ok
bad = wc.score_part(P(answer="chef", wrong1="baker", wrong2="cloud", wrong3="cup"), "who", "cook", {"agents": {"chef"}})
assert bad["accepted"] and bad["bad_distractors"] == 1, bad
print("phone failures: copied hint / generic who / echoed instruction / repeated options / cut-off JSON / answer missing / long option all caught")

# 10. the chain: the app's 3 tries per part, stop at the first part that never passes, who != what
good = {p: [it["ref_reply"]] for p, it in zip(wc.QUESTIONS, wc.part_items_from_split(te2[:5], "test"))}
c = wc.score_chain(good, "cook", {})
assert c["exercise_accepted"] and c["total_tries"] == 5 and c["failed_part"] == "", c
retry = dict(good, where=["not json", P(answer="x", wrong1="x", wrong2="x", wrong3="x"), good["where"][0]])
c = wc.score_chain(retry, "cook", {})
assert c["exercise_accepted"] and c["where_tries"] == 3 and c["total_tries"] == 7, c
give_up = dict(good, who=["bad", "bad", "bad", good["who"][0]])  # a 4th try is never used
c = wc.score_chain(give_up, "cook", {})
assert not c["exercise_accepted"] and c["failed_part"] == "who" and c["total_tries"] == 3, c
who_ans = json.loads(good["who"][0])["answer"]
same = dict(good, what=[P(answer=who_ans, wrong1="anger", wrong2="tuesday", wrong3="boredom")] * 3)
c = wc.score_chain(same, "cook", {})
assert not c["exercise_accepted"] and c["failed_part"] == "what" and c["fail_reason"] == "who and what are the same", c
print("chain: complete / retried part / give up after 3 / who == what all behave like the app")

# 11. per-part summary runs (bootstrap over verbs)
items2 = wc.part_items_from_split(te2, "test") + wc.part_items_from_split(va2, "validation")
refs2 = wc.known_valid(items2)
rows2 = [{**wc.score_part(it["ref_reply"], it["part"], it["verb"], refs2[it["verb"]], it["ref_answer"]),
          "verb": it["verb"], "split": it["split"], "part": it["part"]} for it in items2]
df2 = pd.DataFrame(rows2)
for mtr in wc.PART_METRICS:
    df2[mtr] = df2[mtr].astype(bool)
print(wc.summarise(df2, ["split", "part"], metrics=wc.PART_METRICS)[["split", "part", "n", "n_verbs", "accepted_pct", "who_known_valid_pct", "any_bad_distractor_pct"]].to_string(index=False))

# 12. chained items: one per exercise, references + avoid list; scoring the references chains to a complete exercise
ch = wc.chain_items_from_split(te2, "test") + wc.chain_items_from_split(va2, "validation")
stats2 = json.loads((v2 / "stats.json").read_text())["sentences"]
assert len([c for c in ch if c["split"] == "test"]) == stats2["test"] and len([c for c in ch if c["split"] == "validation"]) == stats2["validation"]
by_ex = {}
for r in te2:
    m = r["meta"]; by_ex.setdefault(f"test:{m['sentence_id']}#{m['variant']}", {})[m["part"]] = [r["messages"][2]["content"]]
assert all(wc.score_chain(by_ex[c["exercise_id"]], c["verb"], {})["exercise_accepted"] for c in ch if c["split"] == "test")
cdf = pd.DataFrame([{"verb": c["verb"], "split": c["split"], "exercise_accepted": True} for c in ch])
assert (wc.summarise(cdf, ["split"], metrics=wc.CHAIN_METRICS)["exercise_accepted_pct"] == 100.0).all()
print(f"chain items: {len(ch)} exercises (test {stats2['test']}, validation {stats2['validation']}); references complete as chains")

# 13. stop tokens: generation config + tokenizer eos + chat end-of-turn tokens present in the vocabulary
class _Tok:
    eos_token_id = 128001
    def get_vocab(self): return {"<|eot_id|>": 128009, "<|end_of_text|>": 128001, "hello": 5}
assert wc.stop_token_ids(_Tok(), [128001, 128008]) == [128001, 128008, 128009]
assert wc.stop_token_ids(_Tok(), None) == [128001, 128009]
print("stop tokens: generation config + eos + <|eot_id|>/<|im_end|>/<|end_of_text|> when present")

# 14. offline mode: no upload, downloads from the mirror or from this run's own files
import os, tempfile  # noqa: E401,E402
with tempfile.TemporaryDirectory() as _mirror, tempfile.TemporaryDirectory() as _work:
    os.environ["VNEST_OFFLINE"], os.environ["VNEST_OFFLINE_DIR"] = "1", _mirror
    try:
        (Path(_mirror) / "data/v2").mkdir(parents=True); (Path(_mirror) / "data/v2/x.txt").write_text("hi")
        assert wc.hf_download("data/v2/x.txt", _work).read_text() == "hi"
        assert wc.hf_download("data/v2/missing.txt", _work) is None
        st = wc.Stages("b2-test-offline", {}, set(), _work)
        assert st.should_run("generate")
        st.mark_done("generate", {"ok": 1})       # written locally only ("[offline] not uploaded")
        assert not st.should_run("generate")       # ...and found again: resume works offline
        assert wc.whoami() == wc.HF_USER
    finally:
        del os.environ["VNEST_OFFLINE"], os.environ["VNEST_OFFLINE_DIR"]
print("offline mode: no uploads, mirror + own-file downloads, stage markers resume locally")
print("ALL CHECKS PASSED, module", wc.VERSION)
