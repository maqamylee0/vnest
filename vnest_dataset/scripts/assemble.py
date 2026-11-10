"""Step 3: assemble chat-format fine-tuning data in the app's exact exercise JSON.

Correct answers: who/what from ConceptNet (pairs.jsonl), where/when/why from the teacher (wh.jsonl, ok rows only).
Wrong options: fixed lists of clearly impossible answers, minus anything ConceptNet lists as valid for the verb.

Usage: python3 -I assemble.py <raw_dir> <out_dir>
Writes train.jsonl, validation.jsonl, test.jsonl, review_sample.csv, stats.json
"""
import csv
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import SUITABLE_EXCEPTIONS, TEST_VERBS, UNSUITABLE, VERBS, strip_det, third_person  # noqa: E402

RAW, OUT = Path(sys.argv[1]), Path(sys.argv[2])
rng = random.Random(20261110)
TRAIN_VARIANTS = 2  # copies of each training pair with different wrong options / prompt style

# ---------------- wrong-option pools (clearly impossible) ----------------
WHO_WRONG = """stone cloud spoon pillow brick button puddle feather cup sock mountain pebble leaf candle bucket carpet
mirror teapot plate bowl hat envelope blanket sandwich banana tomato potato apple cushion lamp curtain balloon marble
crayon napkin doorknob shoelace chair table sofa bottle""".split()
WHAT_WRONG = ["anger", "sadness", "joy", "fear", "silence", "tuesday", "yesterday", "midnight", "honesty", "gravity",
              "thunder", "a thought", "a dream", "the past", "a minute", "laziness", "kindness", "an echo", "a memory",
              "jealousy", "boredom", "courage", "the alphabet", "a rumor", "patience", "tomorrow", "a wish",
              "loneliness", "an idea", "friday"]
WHERE_WRONG = ["under the sea", "on the moon", "inside a cloud", "on a rainbow", "inside a volcano", "inside a teapot",
               "on the sun", "in outer space", "inside a balloon", "on a star", "at the bottom of the ocean",
               "inside a raindrop", "on a cloud", "inside an egg"]
WHEN_WRONG = ["while sleeping", "before he was born", "during a dream", "after the sun explodes", "in the year 3000",
              "while underwater", "before dinosaurs lived", "while flying to the moon", "during an earthquake",
              "before time began", "while asleep", "on the moon"]
WHY_WRONG = ["to grow wings", "to make it rain", "to turn into a fish", "to stop the sun", "to fly to the moon",
             "to become invisible", "to turn into a cloud", "to talk to the stars", "to make time stop",
             "to live forever", "to turn into a bird", "to become a tree"]

# ---------------- what ConceptNet says is valid (so a wrong option is never actually right) ----------------
valid_objects, can_do = defaultdict(set), defaultdict(set)
for line in open(RAW / "conceptnet" / "train.jsonl"):
    d = json.loads(line)
    for phrase in (d["head"].lower(), d["tail"].lower()):
        p = phrase.split()
        if len(p) >= 2 and p[0] in VERBS:
            valid_objects[p[0]].add(strip_det(" ".join(p[1:])))
            valid_objects[p[0]].add(strip_det(p[-1]))
    if d["relation"] == "CapableOf":
        p = d["tail"].lower().split()
        if p and p[0] in VERBS:
            can_do[p[0]].add(strip_det(d["head"]))

def content(s):
    return {w for w in s.split() if w not in {"a", "an", "the", "in", "on", "at", "to", "of", "after", "before", "while", "during"}}

def sample(pool, exclude):
    ok = [x for x in pool if not exclude(x)]
    return rng.sample(ok, 3)

def exercise(r):
    v = r["verb"]
    def q(answer, wrong):
        opts = [answer] + wrong
        rng.shuffle(opts)  # don't let the model learn "the answer comes first"
        return {"options": opts, "answer": answer}
    return {
        "who": q(r["agent"], sample(WHO_WRONG, lambda x: x in can_do[v] or x == r["patient"])),
        "what": q(r["patient"], sample(WHAT_WRONG, lambda x: strip_det(x) in valid_objects[v])),
        "where": q(r["where"], sample(WHERE_WRONG, lambda x: content(x) & content(r["where"]))),
        "when": q(r["when"], sample(WHEN_WRONG, lambda x: content(x) & content(r["when"]))),
        "why": q(r["why"], sample(WHY_WRONG, lambda x: content(x) & content(r["why"]))),
    }

# ---------------- prompts (the app's long prompt, and a short one) ----------------
SYSTEM = ("You are a speech-language therapist. You write Verb Network Strengthening Treatment (VNeST) exercises "
          "for adults with aphasia. Use short, very common, concrete English words. Reply only with JSON.")
EXAMPLE = ('{"who": {"options": ["carpenter", "wood", "cloud", "spoon"], "answer": "carpenter"}, '
           '"what": {"options": ["wood", "song", "anger", "sky"], "answer": "wood"}, '
           '"where": {"options": ["in the workshop", "under the sea", "in the sky", "on the moon"], "answer": "in the workshop"}, '
           '"when": {"options": ["before cutting", "while sleeping", "while swimming", "before he was born"], "answer": "before cutting"}, '
           '"why": {"options": ["to build a table", "to grow wings", "to make it rain", "to turn into a fish"], "answer": "to build a table"}}')

def long_prompt(verb, avoid):  # identical to LlmService.userPrompt in the app
    return (f'Verb: "{verb}".\n'
            "Write one exercise. Each question has 4 options. ONLY ONE option may be correct; "
            "the other 3 must be clearly impossible, so a patient choosing them is definitely wrong. "
            "The answer must be copied exactly from the options.\n"
            "who: answer = a kind of person who often does this" + (f" (not {', '.join(avoid)})" if avoid else "") + ". "
            f"The 3 wrong options must NOT be people or animals: use objects or nature words that cannot {verb} "
            "(like cloud, spoon, stone).\n"
            f"what: answer = what that person {third_person(verb)}. The 3 wrong options must be things nobody can {verb} "
            "(feelings, weather, sounds, far-away things like song, anger, sky, moon).\n"
            "where, when, why: about that person and thing. Answer = the usual place, time and reason (2 to 4 words). "
            "The 3 wrong options must be impossible or silly (like under the sea, while sleeping, to grow wings).\n"
            f'Example for "measure": {EXAMPLE}')

def short_prompt(verb, avoid):
    return f'VNeST exercise for the verb "{verb}".' + (f" Not these people: {', '.join(avoid)}." if avoid else "")

def chat(r, avoid, style):
    user = long_prompt(r["verb"], avoid) if style == "long" else short_prompt(r["verb"], avoid)
    return {"messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": user},
                         {"role": "assistant", "content": json.dumps(exercise(r), ensure_ascii=False)}],
            "meta": {"verb": r["verb"], "agent": r["agent"], "patient": r["patient"], "prompt": style,
                     "teacher": r.get("teacher")}}

# ---------------- load, dedupe, split by verb ----------------
current = {(p["verb"], p["agent"], p["patient"]) for p in map(json.loads, open(OUT / "pairs.jsonl"))}
rows = [r for r in map(json.loads, open(OUT / "wh.jsonl")) if (r["verb"], r["agent"], r["patient"]) in current]
reasons = Counter((r["reason"] or "ok").split(":")[0] for r in rows)
def suitable(r):
    text = " ".join([r["agent"], r["patient"], r["where"], r["when"], r["why"]])
    for ok_phrase in SUITABLE_EXCEPTIONS:
        text = text.replace(ok_phrase, "")
    return not (set(text.split()) & UNSUITABLE)

good = [r for r in rows if r["ok"] and suitable(r)]
reasons["unsuitable content"] = sum(1 for r in rows if r["ok"] and not suitable(r))

by_verb = defaultdict(list)
seen = set()
for r in good:
    key = (r["verb"], r["agent"], r["patient"].rstrip("s"))  # "shoe"/"shoes" count once
    if key in seen:
        continue
    seen.add(key)
    by_verb[r["verb"]].append(r)
CAP = 30  # no single verb dominates
for v in by_verb:
    rng.shuffle(by_verb[v])
    by_verb[v] = by_verb[v][:CAP]

others = sorted(v for v in by_verb if v not in TEST_VERBS)
rng.shuffle(others)
val_verbs = set(others[: max(4, len(others) // 10)])

splits = {"train": [], "validation": [], "test": []}
for v, items in sorted(by_verb.items()):
    split = "test" if v in TEST_VERBS else "validation" if v in val_verbs else "train"
    for i, r in enumerate(items):
        prev = [x["agent"] for x in items[:i] if x["agent"] != r["agent"]][-3:]
        for k in range(TRAIN_VARIANTS if split == "train" else 1):
            avoid = prev if prev and rng.random() < 0.3 else []
            splits[split].append(chat(r, avoid, "long" if (k + i) % 2 == 0 else "short"))

for name, data in splits.items():
    rng.shuffle(data)
    with open(OUT / f"{name}.jsonl", "w") as f:
        for d in data:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")

# ---------------- human review sheet ----------------
with open(OUT / "review_sample.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["sentence", "where", "when", "why", "wrong who", "wrong what", "ok? (y/n)", "notes"])
    for d in rng.sample(splits["train"], min(100, len(splits["train"]))):
        e, m = json.loads(d["messages"][2]["content"]), d["meta"]
        w.writerow([f"The {m['agent']} {third_person(m['verb'])} the {m['patient']}.",
                    e["where"]["answer"], e["when"]["answer"], e["why"]["answer"],
                    ", ".join(o for o in e["who"]["options"] if o != e["who"]["answer"]),
                    ", ".join(o for o in e["what"]["options"] if o != e["what"]["answer"]), "", ""])

stats = {
    "teacher_rows": len(rows), "teacher_outcomes": dict(reasons), "unique_ok_pairs": sum(len(v) for v in by_verb.values()),
    "verbs": len(by_verb), "split_examples": {k: len(v) for k, v in splits.items()},
    "split_verbs": {"train": sorted(set(by_verb) - TEST_VERBS - val_verbs), "validation": sorted(val_verbs),
                    "test": sorted(set(by_verb) & TEST_VERBS)},
    "pairs_per_verb": {v: len(x) for v, x in sorted(by_verb.items(), key=lambda x: -len(x[1]))},
}
json.dump(stats, open(OUT / "stats.json", "w"), indent=1)
print(json.dumps({k: stats[k] for k in ("teacher_rows", "teacher_outcomes", "unique_ok_pairs", "verbs", "split_examples")}, indent=1))
print("validation verbs:", stats["split_verbs"]["validation"])
print("test verbs:", stats["split_verbs"]["test"])
