"""Step 2: a larger "teacher" model writes the CORRECT where / when / why answers for each who/what pair,
and flags sentences that are odd, idiomatic, violent or sad (not suitable for therapy).

Wrong options are NOT written here: assemble.py adds them from fixed lists of impossible answers.

Runs against a local Ollama server (default llama3.1:8b). Resumable: already-done pairs are skipped.
Usage: python3 -I teacher_wh.py <out_dir> [model] [limit]
Writes <out_dir>/wh.jsonl: {"verb","agent","patient","ok","where","when","why","teacher","reason"}
"""
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import third_person  # noqa: E402

OUT = Path(sys.argv[1])
MODEL = sys.argv[2] if len(sys.argv) > 2 else "llama3.1:8b"
LIMIT = int(sys.argv[3]) if len(sys.argv) > 3 else None

SCHEMA = {
    "type": "object",
    "properties": {
        "suitable": {"type": "boolean"},
        "where": {"type": "string"},
        "when": {"type": "string"},
        "why": {"type": "string"},
    },
    "required": ["suitable", "where", "when", "why"],
}
SYSTEM = ("You are a speech-language therapist preparing exercises for adults with aphasia. "
          "Use very common, simple, concrete English. Reply only with JSON.")

def prompt(verb, agent, patient):
    s = f"The {agent} {third_person(verb)} the {patient}."
    return (f'Sentence: "{s}"\n'
            "suitable: true only if this is a normal, everyday, pleasant action that is easy to picture. "
            "false if it is strange, an idiom, violent, sad, about death, weapons or illness, or grammatically odd.\n"
            "where: the usual place, 2 to 4 words, starting with in, at or on (example: in the kitchen).\n"
            "when: the usual time or moment, 2 to 4 words (example: in the morning, after school, before dinner).\n"
            f"why: the usual reason the {agent} does it, 2 to 5 words, starting with to (example: to feed the family).\n"
            "Each answer must fit this exact sentence. Do not repeat the verb in the answers.")

def ask(verb, agent, patient):
    body = {"model": MODEL, "stream": False, "format": SCHEMA,
            "options": {"temperature": 0.2, "num_predict": 120},
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt(verb, agent, patient)}]}
    req = urllib.request.Request("http://localhost:11434/api/chat", json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(json.load(r)["message"]["content"])

def clean(s):
    return re.sub(r"\s+", " ", str(s).strip().lower().rstrip(".!"))

def check(d, verb):
    """Returns a reason the teacher's answers can't be used, or None."""
    if not d.get("suitable"):
        return "teacher: not suitable"
    forms = {verb, third_person(verb), verb + "ing", verb[:-1] + "ing" if verb.endswith("e") else verb + "ing"}
    for k, (lo, hi) in {"where": (2, 5), "when": (1, 5), "why": (2, 6)}.items():
        v = d[k]
        if not re.fullmatch(r"[a-z' ,-]+", v):
            return f"{k}: unexpected characters"
        if not lo <= len(v.split()) <= hi:
            return f"{k}: length"
        if set(v.split()) & forms:
            return f"{k}: repeats the verb"
    if not d["where"].split()[0] in {"in", "at", "on", "by", "near", "outside", "inside", "under"}:
        return "where: not a place phrase"
    if not d["why"].startswith("to "):
        return "why: does not start with 'to'"
    return None

pairs = [json.loads(l) for l in open(OUT / "pairs.jsonl")]
done_path = OUT / "wh.jsonl"
done = set()
if done_path.exists():
    for l in open(done_path):
        r = json.loads(l)
        done.add((r["verb"], r["agent"], r["patient"]))

todo = [p for p in pairs if (p["verb"], p["agent"], p["patient"]) not in done]
if LIMIT:
    todo = todo[:LIMIT]
print(f"{len(done)} done, {len(todo)} to do with {MODEL}", flush=True)
t0 = time.time()
with open(done_path, "a") as f:
    for i, p in enumerate(todo, 1):
        try:
            raw = ask(p["verb"], p["agent"], p["patient"])
            d = {"suitable": bool(raw.get("suitable")), **{k: clean(raw.get(k, "")) for k in ("where", "when", "why")}}
            reason = check(d, p["verb"])
        except Exception as e:  # keep going; the pair is recorded as failed and can be retried by deleting the line
            d, reason = {"suitable": False, "where": "", "when": "", "why": ""}, f"error: {e}"
        rec = {**{k: p[k] for k in ("verb", "agent", "patient")}, "ok": reason is None,
               "where": d["where"], "when": d["when"], "why": d["why"], "teacher": MODEL, "reason": reason}
        f.write(json.dumps(rec) + "\n")
        f.flush()
        if i % 25 == 0 or i == len(todo) or LIMIT:
            rate = (time.time() - t0) / i
            print(f"[{i}/{len(todo)}] {rate:.1f}s each | {'OK ' if rec['ok'] else 'REJ'} "
                  f"The {p['agent']} {third_person(p['verb'])} the {p['patient']}. -> "
                  f"{rec['where']} | {rec['when']} | {rec['why']} {reason or ''}", flush=True)
