"""Dataset v2: one example per question (who, what, where, when, why), in the app's per-part format.

Same sentences and the same verb splits as v1 (read from v1's out/ files, so results stay comparable); what changes:
  1. Format: each exercise becomes 5 chat examples. The user message is the app's per-part prompt
     (LlmService.partPrompt: verb, part, and the sentence so far built in code); the assistant reply is
     {"answer": ..., "wrong1": ..., "wrong2": ..., "wrong3": ...} (RESEARCH_LOG decisions 2026-11-11, Entry 8).
     The system line is read from vnest_app/lib/services/llm_service.dart, so it is identical to the app's.
  2. Wrong-option lists cleaned: options that are valid for some verb in our list were removed (audit 2026-11-11:
     teach -> "the alphabet", fly -> "inside a cloud", write -> "a wish", ...).
  3. Verb check: a wrong option may not contain the verb (or its forms), a word of the correct answer, the person or
     the object, or a word in VERB_CONFLICTS for that verb.
Every example passes the app's own checks (Scenario.partFromModel + checkContent + who != what).

Usage: python3 -I assemble_v2.py <v1_out_dir> <v2_out_dir> <path to llm_service.dart>
Writes train.jsonl, validation.jsonl, test.jsonl, review_sample.csv, stats.json
"""
import csv
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import third_person  # noqa: E402  (same rules as Scenario.thirdPerson in the app)

V1, OUT, DART = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
OUT.mkdir(parents=True, exist_ok=True)
rng = random.Random(20261111)
TRAIN_VARIANTS = 2  # each training sentence twice, with different wrong options (and "not these people" sometimes)
AVOID_PROB = 0.3    # share of "who" prompts that list people already used for the verb (as the app does on repeats)
PARTS = ["who", "what", "where", "when", "why"]

# ---------------- wrong-option pools: only things that are impossible for every verb we use ----------------
WHO_WRONG = """stone cloud spoon pillow brick button puddle feather cup sock mountain pebble leaf candle bucket carpet
mirror teapot plate bowl hat envelope blanket sandwich banana tomato potato apple cushion lamp curtain balloon marble
crayon napkin doorknob shoelace chair table sofa bottle""".split()
WHAT_WRONG = ["anger", "sadness", "boredom", "laziness", "jealousy", "loneliness",
              "tuesday", "friday", "yesterday", "tomorrow", "next week", "last year"]
WHERE_WRONG = ["under the sea", "on the moon", "inside a cloud", "on a rainbow", "inside a volcano", "inside a teapot",
               "on the sun", "in outer space", "inside a balloon", "on a star", "at the bottom of the ocean",
               "inside a raindrop"]  # "on a cloud" dropped: near-duplicate of "inside a cloud" in the same question
WHEN_WRONG = ["while sleeping", "before he was born", "during a dream", "after the sun explodes", "in the year 3000",
              "while underwater", "before dinosaurs lived", "while flying to the moon", "before time began"]  # "while asleep" dropped: same as "while sleeping"
WHY_WRONG = ["to grow wings", "to make it rain", "to turn into a fish", "to stop the sun", "to fly to the moon",
             "to become invisible", "to turn into a cloud", "to talk to the stars", "to make time stop",
             "to live forever", "to turn into a bird", "to become a tree"]
POOLS = {"who": WHO_WRONG, "what": WHAT_WRONG, "where": WHERE_WRONG, "when": WHEN_WRONG, "why": WHY_WRONG}

# Words that make a "wrong" option possibly right for that verb (a plane flies inside a cloud; you wash under water).
SKY = {"cloud", "sky", "space", "moon", "star", "stars", "sun", "air", "balloon", "rainbow", "wings", "bird", "flying"}
WATER = {"sea", "ocean", "water", "underwater", "raindrop", "rain", "fish", "swimming"}
VERB_CONFLICTS = {
    "fly": SKY, "throw": SKY, "catch": SKY | {"fish"}, "climb": {"mountain", "tree", "volcano", "star", "stars"},
    "fish": WATER, "swim": WATER, "wash": WATER, "water": WATER, "clean": WATER, "mop": WATER, "wipe": WATER,
    "fill": WATER | {"balloon", "teapot", "cup", "bucket", "bottle", "bowl"}, "drink": WATER | {"teapot", "cup", "bottle"},
    "build": {"moon", "rocket", "volcano"}, "grow": {"tree", "wings"}, "plant": {"tree"}, "water_": set(),
    "draw": SKY, "paint": SKY | {"rainbow"}, "read": {"stars"}, "count": {"stars", "star"}, "sing": {"stars"},
    "blow": {"balloon"}, "pick": {"apple", "banana", "tomato", "potato", "leaf"}, "eat": {"apple", "banana", "tomato", "potato", "sandwich"},
}
STOP = {"a", "an", "the", "in", "on", "at", "to", "of", "after", "before", "while", "during", "inside", "under", "it", "he"}

def words(s):
    return {w for w in re.findall(r"[a-z]+", s.lower()) if w not in STOP}

def verb_forms(v):
    t = third_person(v)
    ing = (v[:-1] if v.endswith("e") and not v.endswith("ee") else v) + "ing"
    return {v, t, ing, v + "ed", v + "d", (v[:-1] + "ied") if v.endswith("y") else v + "ed"}

def allowed(option, part, r):
    w = words(option)
    if w & verb_forms(r["verb"]):
        return False
    if w & words(r[{"who": "agent", "what": "patient"}.get(part, part)]):  # shares a word with the correct answer
        return False
    if w & (words(r["agent"]) | words(r["patient"])):
        return False
    return not (w & VERB_CONFLICTS.get(r["verb"], set()))

# ---------------- the app's per-part prompt (port of LlmService.partPrompt; checked against the app's test strings) --------
def dart_string_constant(src, name):
    m = re.search(rf"static const {name} =(.*?);\n", src, re.S)
    return "".join(re.findall(r"'((?:[^'\\]|\\.)*)'", m.group(1))).replace("\\'", "'")

SYSTEM = dart_string_constant(DART.read_text(), "partSystemPrompt")
assert SYSTEM.startswith("You write Verb Network Strengthening Treatment") and SYSTEM.endswith('"wrong3": "..."}.'), SYSTEM

def clean(s):   # Scenario.clean
    return re.sub(r"\s+", " ", re.sub(r"[.!?]+$", "", s.strip())).lower()

def noun(s):    # Scenario.noun
    return re.sub(r"^(a|an|the)\s+", "", s)

def part_prompt(verb, part, done, avoid=()):
    v3 = third_person(verb)
    a = lambda k: noun(done[k])  # noqa: E731
    head = f'VNeST "{verb}". {part}?'
    if part == "who":
        return (f"{head} Answer: a person (1 or 2 words) who often {v3} things. Wrong: 3 things that cannot {verb}."
                + (f" The answer must not be: {', '.join(avoid)}." if avoid else ""))
    if part == "what":
        return f"{head} The {a('who')} {v3} ___. Answer: what the {a('who')} {v3}. Wrong: 3 things nobody can {verb}."
    if part == "where":
        return (f"{head} The {a('who')} {v3} the {a('what')} ___. "
                "Answer: the usual place (2 to 4 words). Wrong: 3 impossible places.")
    if part == "when":
        return (f"{head} The {a('who')} {v3} the {a('what')} {done['where']} ___. "
                "Answer: the usual time (2 to 4 words). Wrong: 3 impossible times.")
    return (f"{head} The {a('who')} {v3} the {a('what')} {done['where']} {done['when']} ___. "
            'Answer: the usual reason, starting with "to" (2 to 5 words). Wrong: 3 silly reasons.')

# Same literals as the app's tests (test/widget_test.dart), so a drift between app and dataset fails here.
_done = {"who": "chef", "what": "egg", "where": "in the kitchen", "when": "in the morning"}
assert part_prompt("cook", "who", {}) == ("VNeST \"cook\". who? Answer: a person (1 or 2 words) who often cooks things. "
                                         "Wrong: 3 things that cannot cook.")
assert part_prompt("cook", "who", {}, ["chef", "grandma"]).endswith("The answer must not be: chef, grandma.")
assert part_prompt("cook", "what", _done) == ("VNeST \"cook\". what? The chef cooks ___. Answer: what the chef cooks. "
                                              "Wrong: 3 things nobody can cook.")
assert part_prompt("cook", "where", _done).startswith('VNeST "cook". where? The chef cooks the egg ___. ')
assert part_prompt("cook", "why", _done).startswith('VNeST "cook". why? The chef cooks the egg in the kitchen in the morning ___. ')

# ---------------- the app's checks on one part (Scenario.partFromModel + checkContent) ----------------
GENERIC_PEOPLE = {"person", "someone", "somebody", "people", "anyone", "anybody", "human", "a human", "man", "woman", "they",
                  "you", "everyone", "adult", "patient"}
ECHOES = ["usual place", "usual time", "usual reason", "a person who", "person who", "things that cannot", "nobody can",
          "impossible place", "impossible time", "silly reason", "wrong option", "correct answer", "the answer"]

def app_accepts(part, reply):
    opts = [clean(reply[k]) for k in ("answer", "wrong1", "wrong2", "wrong3")]
    if len(set(opts)) != 4 or any(not o or len(o.split(" ")) > 6 for o in opts):
        return False
    if part == "who" and noun(opts[0]) in GENERIC_PEOPLE:
        return False
    return not any(e in o for o in opts for e in ECHOES)

# ---------------- sentences and splits: v1's, minus generic people and sexual slang ----------------
# v1's content filter missed ConceptNet sexual slang: "woman spread pussy" (train) and "man eat pussy" (validation), which
# the teacher explained innocently ("to plant flowers", "to feed the cat"). Extra words, on top of common.UNSUITABLE
# (kept unchanged so v1 still rebuilds to its recorded checksums).
EXTRA_UNSUITABLE = {"pussy", "puss", "dick", "cock", "cum", "sex", "sexy", "porn", "ass", "arse", "boob", "boobs", "tit",
                    "tits", "nipple", "nipples", "penis", "vagina", "naked", "nude", "stripper", "whore", "slut", "bitch",
                    "horny", "condom", "panties", "lick", "spank", "booty", "balls", "beaver", "pecker", "willy", "screw"}
wh = {(r["verb"], r["agent"], r["patient"]): r for r in map(json.loads, open(V1 / "wh.jsonl")) if r["ok"]}
split_rows, v1_verbs, dropped = {}, {}, defaultdict(list)
for split in ["train", "validation", "test"]:
    seen, rows = set(), []
    for d in map(json.loads, open(V1 / f"{split}.jsonl")):
        m = d["meta"]
        key = (m["verb"], m["agent"], m["patient"])
        if key in seen:
            continue
        seen.add(key)
        r = dict(wh[key])
        text = " ".join([r["agent"], r["patient"], r["where"], r["when"], r["why"]]).lower()
        if set(re.findall(r"[a-z]+", text)) & EXTRA_UNSUITABLE:
            dropped[split].append(("unsuitable", " ".join(key)))
        elif noun(clean(r["agent"])) in GENERIC_PEOPLE:  # the app rejects generic "who" answers (Entry 8)
            dropped[split].append(("generic person", " ".join(key)))
        else:
            rows.append(r)
    rows.sort(key=lambda r: (r["verb"], r["agent"], r["patient"]))  # deterministic order
    split_rows[split] = rows
    v1_verbs[split] = sorted({r["verb"] for r in rows})
assert not (set(v1_verbs["train"]) & (set(v1_verbs["validation"]) | set(v1_verbs["test"])))

def reply_for(part, r):
    answer = clean(r[{"who": "agent", "what": "patient"}.get(part, part)])
    pool = [o for o in POOLS[part] if allowed(o, part, r)]
    wrong = rng.sample(pool, 3)
    return {"answer": answer, "wrong1": wrong[0], "wrong2": wrong[1], "wrong3": wrong[2]}

def examples(r, avoid, variant, sid):
    done, out = {}, []
    for part in PARTS:
        reply = reply_for(part, r)
        assert app_accepts(part, reply), (part, reply)
        if part == "what":
            assert noun(reply["answer"]) != noun(done["who"])
        user = part_prompt(r["verb"], part, done, avoid if part == "who" else ())
        out.append({"messages": [{"role": "system", "content": SYSTEM},
                                 {"role": "user", "content": user},
                                 {"role": "assistant", "content": json.dumps(reply, ensure_ascii=False)}],
                    "meta": {"verb": r["verb"], "part": part, "agent": r["agent"], "patient": r["patient"],
                             "sentence_id": sid, "variant": variant, "avoid": list(avoid), "teacher": r.get("teacher")}})
        done[part] = reply["answer"]
    return out

splits, review = {}, []
for split, rows in split_rows.items():
    data, by_verb = [], defaultdict(list)
    for r in rows:
        by_verb[r["verb"]].append(r)
    for v, items in by_verb.items():
        for i, r in enumerate(items):
            prev = [noun(clean(x["agent"])) for x in items[:i] if x["agent"] != r["agent"]][-3:]
            for k in range(TRAIN_VARIANTS if split == "train" else 1):
                avoid = prev if prev and rng.random() < AVOID_PROB else []
                ex = examples(r, avoid, k, f"{v}|{r['agent']}|{r['patient']}")
                data.extend(ex)
                if split == "train":
                    review.append(ex)
    splits[split] = data

for name, data in splits.items():
    with open(OUT / f"{name}.jsonl", "w") as f:  # grouped by sentence (who..why in order); shuffle when training
        for d in data:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")

# ---------------- audit: wrong options that could be right (the 2026-11-11 suspect list; must all be 0 now) -------------
SUSPECT = {"the alphabet", "a dream", "an idea", "a memory", "silence", "a wish", "a minute", "thunder", "inside an egg",
           "during an earthquake", "a rumor", "kindness", "patience", "courage", "honesty", "gravity", "joy", "fear"}
SUSPECT_BY_VERB = {("fly", "inside a cloud"), ("fly", "on a cloud"), ("fly", "in outer space"), ("fly", "to fly to the moon"),
                   ("fly", "while flying to the moon"), ("build", "to fly to the moon"), ("water", "to make it rain"),
                   ("wash", "while underwater"), ("fish", "under the sea"), ("fish", "at the bottom of the ocean")}
audit = Counter()
for data in splits.values():
    for d in data:
        rep, v = json.loads(d["messages"][2]["content"]), d["meta"]["verb"]
        for o in (rep["wrong1"], rep["wrong2"], rep["wrong3"]):
            if o in SUSPECT or (v, o) in SUSPECT_BY_VERB:
                audit[(v, d["meta"]["part"], o)] += 1
assert not audit, f"suspect wrong options still present: {audit}"

# ---------------- human review sheet: 100 random training exercises, one row each ----------------
with open(OUT / "review_sample.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["sentence", "where", "when", "why", "wrong who", "wrong what", "wrong where", "wrong when", "wrong why",
                "ok? (y/n)", "notes"])
    for ex in rng.sample(review, min(100, len(review))):
        rep = {e["meta"]["part"]: json.loads(e["messages"][2]["content"]) for e in ex}
        m = ex[0]["meta"]
        wr = lambda p: ", ".join(rep[p][k] for k in ("wrong1", "wrong2", "wrong3"))  # noqa: E731
        w.writerow([f"The {noun(clean(m['agent']))} {third_person(m['verb'])} the {noun(clean(m['patient']))}.",
                    rep["where"]["answer"], rep["when"]["answer"], rep["why"]["answer"],
                    wr("who"), wr("what"), wr("where"), wr("when"), wr("why"), "", ""])

stats = {
    "format": "one example per part; reply {answer, wrong1, wrong2, wrong3}; prompts = LlmService.partPrompt",
    "system_prompt": SYSTEM,
    "sentences": {k: len(v) for k, v in split_rows.items()},
    "split_examples": {k: len(v) for k, v in splits.items()},
    "split_verbs": v1_verbs,
    "examples_with_avoid_list": sum(1 for d in splits["train"] if d["meta"]["avoid"]),
    "dropped_from_v1": {s: Counter(why for why, _ in v).most_common() for s, v in dropped.items()},
    "dropped_unsuitable": {s: [t for why, t in v if why == "unsuitable"] for s, v in dropped.items()},
    "wrong_pool_sizes": {k: len(v) for k, v in POOLS.items()},
    "audit_suspect_wrong_options": 0,
}
json.dump(stats, open(OUT / "stats.json", "w"), indent=1)
print(json.dumps({k: stats[k] for k in ("sentences", "split_examples", "examples_with_avoid_list", "wrong_pool_sizes")}, indent=1))
