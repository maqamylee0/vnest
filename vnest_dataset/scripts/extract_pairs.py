"""Step 1: who/what pairs from ConceptNet "CapableOf" (e.g. "a gardener -> plant roses").

Usage: python3 -I extract_pairs.py <raw_dir> <out_dir>
Writes <out_dir>/pairs.jsonl: {"verb", "agent", "patient", "count"}
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import PEOPLE, PLURALS, VERBS, load_dictionary, strip_det  # noqa: E402

RAW, OUT = Path(sys.argv[1]), Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)
dictionary = load_dictionary()

# Objects that are people are only allowed with caring verbs ("the nurse feeds the baby").
CARE_VERBS = {"feed", "teach", "carry", "wash", "treat", "examine", "shave", "comb", "brush", "check", "hug", "bandage", "drive"}
BAD_OBJECTS = {"persons", "people", "person", "thing", "things", "stuff", "something", "it", "them", "one", "ones", "himself", "herself", "themselves",
               "itself", "lot", "way", "time", "more", "out", "up", "down", "off", "back", "away"}

def agent_of(head: str):
    h = strip_det(head)
    h = PLURALS.get(h, h) if h in PLURALS else h
    return h if h in PEOPLE else None

# ConceptNet's older entries contain crudely shortened plurals ("wash clothe"). Restore them.
FIX_WORDS = {"clothe": "clothes", "trouser": "trousers", "thieve": "thieves", "glasse": "glasses", "pant": "pants",
             "jean": "jeans", "scissor": "scissors", "dishe": "dishes", "boxe": "boxes", "potatoe": "potatoes",
             "tomatoe": "tomatoes"}
GARMENT_VERBS = {"wear", "iron", "wash", "fold", "hang", "sew", "pack"}

def fix_words(obj: str, verb: str) -> str:
    out = [FIX_WORDS.get(w, w) for w in obj.split()]
    if verb in GARMENT_VERBS and out[-1] in {"slack", "short"}:
        out[-1] += "s"
    return " ".join(out)

def object_of(rest: str):
    o = strip_det(rest)
    o = re.sub(r"\s+", " ", o).strip()
    if not o or len(o.split()) > 2 or not re.fullmatch(r"[a-z ]+", o):
        return None
    if any(w not in dictionary for w in o.split()):  # drops typos like "thier", fragments like "st"
        return None
    if o in BAD_OBJECTS or o.split()[0] in BAD_OBJECTS:
        return None
    if o.split()[0] in {"to", "for", "with", "from", "in", "on", "at", "up", "into", "out", "of", "by", "about"}:
        return None  # "hang from a tree": not a direct object
    return o

pairs = Counter()
for line in open(RAW / "conceptnet" / "train.jsonl"):
    d = json.loads(line)
    if d["relation"] != "CapableOf":
        continue
    agent = agent_of(d["head"])
    parts = d["tail"].strip().lower().split()
    if not agent or len(parts) < 2 or parts[0] not in VERBS:
        continue
    verb, obj = parts[0], object_of(" ".join(parts[1:]))
    if not obj:
        continue
    obj = fix_words(obj, verb)
    if (obj in PEOPLE or PLURALS.get(obj)) and verb not in CARE_VERBS:
        continue
    pairs[(verb, agent, obj)] += 1

with open(OUT / "pairs.jsonl", "w") as f:
    for (verb, agent, obj), n in sorted(pairs.items()):
        f.write(json.dumps({"verb": verb, "agent": agent, "patient": obj, "count": n}) + "\n")

verbs = Counter(v for v, _, _ in pairs)
print(f"{len(pairs)} pairs, {len(verbs)} verbs")
print("most pairs:", verbs.most_common(15))
print("test verbs covered:", sorted({v for v in verbs} & {"cook", "drink", "drive", "write", "read", "plant", "fix", "play", "wash", "paint", "cut", "feed", "open", "sweep"}))
