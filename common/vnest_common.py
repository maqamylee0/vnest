"""Shared module for the VNeST exercise LLM notebooks (embedded into every notebook by tools/make_standalone.py).

Holds: project constants, naming, prompts, the ONE scoring definition (ported from the app's
Scenario.fromModel), HF I/O with retries, crash-safe stages, run lock, resource tracking, W&B init.
Import-time dependencies: standard library only (pandas/numpy/torch/hf/wandb imported lazily).

Changelog
- 1.0.0 (2026-11-10): first version, for NB 2_evaluation/01 (untuned baselines).
- 1.1.0 (2026-11-11): per-part scoring for dataset v2 / the app's one-question-per-request format (RESEARCH_LOG Entries 8-9):
  PART_SYSTEM_PROMPT, PART_SCHEMA, part_prompt, part_accept (port of Scenario.partFromModel + checkContent),
  part_items_from_split, score_part, score_chain (the app's 3 tries per part, who != what), PART_METRICS.
  DATA_VERSION -> "v2". Whole-exercise functions (app_accept, score_output, ...) unchanged.
- 1.1.1 (2026-11-11): offline mode (VNEST_OFFLINE=1: no uploads; downloads from VNEST_OFFLINE_DIR or this run's own files),
  summarise(..., metrics=...), chain_items_from_split, CHAIN_METRICS, stop_token_ids. For NB 2_evaluation/02 (baseline b2).
- 1.1.2 (2026-11-11): stricter content check, same as the app's Scenario.checkContent (gaps found in b2, RESEARCH_LOG Entry 10):
  no answer starting with a question word ("what the chef cooks", "when"); "why" may not only repeat the verb ("to cook");
  "when" may not be a place ("at home"). part_accept(part, obj, verb=""); score_part / score_chain pass the verb.
  All 4,155 dataset v2 answers still pass.
- 1.2.0 (2026-11-11): training support for NB 1_training/01: phone_prompt (the phone's MLC "llama-3_1" chat layout, exact),
  ensure_model_repo, hf_model_upload_folder, hf_model_download_folder (offline-aware).
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import resource
import socket
import time
from pathlib import Path

VERSION = "1.2.0"

# ---------------------------------------------------------------------------------------------------------------
# Project constants (decided 2026-11-10, see RESEARCH_LOG.md §4)
# ---------------------------------------------------------------------------------------------------------------
HF_USER = "emmilly"
OUTPUTS_REPO = f"{HF_USER}/vnest-exercise-llm-outputs"  # private dataset: data copy, preds, tables, markers, code
OUTPUTS_PRIVATE = True
MODEL_REPOS_PRIVATE = True  # TO DECIDE before the first model upload (licences); private until then
WANDB_ENTITY = "team-me-and-me"
WANDB_PROJECT = "vnest-exercise-llm"
DATA_VERSION = "v2"  # 2026-11-11: one question per example (v1 = the 2026-11-10 build; not for training)

TEST_VERBS = ("cook", "drive", "paint", "plant", "wash")
VALIDATION_VERBS = ("chop", "eat", "lift", "play", "smell")
QUESTIONS = ("who", "what", "where", "when", "why")

# ---------------------------------------------------------------------------------------------------------------
# Naming (never build these strings by hand in a notebook)
# ---------------------------------------------------------------------------------------------------------------
_FIELD = re.compile(r"^[a-z0-9][a-z0-9.\-]*$")

def _check_field(x: str) -> str:
    if "__" in x or not _FIELD.match(x):
        raise ValueError(f"bad name field {x!r}: lowercase letters, digits, '.', '-' only, no '__'")
    return x

def run_name(exp: str, model: str, variant: str) -> str:
    """e.g. run_name('b1', 'qwen25-1.5b-instruct', 'untuned') -> 'b1-qwen25-1.5b-instruct-untuned'"""
    return "-".join(_check_field(x) for x in (exp, model, variant))

def parse_run_name(name: str) -> dict:
    exp, rest = name.split("-", 1)
    model, variant = rest.rsplit("-", 1)
    return {"exp": exp, "model": model, "variant": variant}

def run_dir(run: str) -> str:
    return f"runs/{_check_field(run)}"

def done_path(run: str, stage: str) -> str:
    return f"{run_dir(run)}/_done/{_check_field(stage)}.json"

def data_path(split: str, version: str = DATA_VERSION) -> str:
    return f"data/{version}/{_check_field(split)}.jsonl"

def preds_path(exp: str, nb: str, run: str, split: str, variant: str) -> str:
    return "preds/" + "__".join(_check_field(x) for x in (exp, nb, run, split, variant)) + ".csv"

def parse_preds_path(path: str) -> dict:
    exp, nb, run, split, variant = Path(path).stem.split("__")
    return {"exp": exp, "nb": nb, "run": run, "split": split, "variant": variant}

def table_path(exp: str, nb: str, what: str) -> str:
    return "tables/" + "__".join(_check_field(x) for x in (exp, nb, what)) + ".csv"

def model_repo(run: str) -> str:
    return f"{HF_USER}/vnest-exercise-llm-{_check_field(run)}"

# The phone builds prompts with MLC's "llama-3_1" conversation template (models/mlc/Llama-3.2-1B-Instruct-q4f16_0-MLC/
# mlc-chat-config.json; mlc-llm 7561c96d python/mlc_llm/conversation_template/llama.py). Hugging Face's Llama 3 template adds
# "Cutting Knowledge Date / Today Date" lines to the system turn, which the phone never sends, so training and evaluation that
# must match the phone build the text here instead. test_vnest_common.py rebuilds it from the phone's config file.
PHONE_BOS = "<|begin_of_text|>"
PHONE_EOT = "<|eot_id|>"

def phone_prompt(system: str, user: str) -> str:
    """The exact text the phone's engine feeds Llama 3.x for one system + one user message, ending where the reply starts."""
    return (f"{PHONE_BOS}<|start_header_id|>system<|end_header_id|>\n\n{system}{PHONE_EOT}"
            f"<|start_header_id|>user<|end_header_id|>\n\n{user}{PHONE_EOT}"
            f"<|start_header_id|>assistant<|end_header_id|>\n\n")

# ---------------------------------------------------------------------------------------------------------------
# Prompts: identical to the app (vnest_app/lib/services/llm_service.dart) and the dataset (assemble.py)
# ---------------------------------------------------------------------------------------------------------------
SYSTEM_PROMPT = ("You are a speech-language therapist. You write Verb Network Strengthening Treatment (VNeST) "
                 "exercises for adults with aphasia. Use short, very common, concrete English words. Reply only with JSON.")
EXAMPLE_JSON = ('{"who": {"options": ["carpenter", "wood", "cloud", "spoon"], "answer": "carpenter"}, '
                '"what": {"options": ["wood", "song", "anger", "sky"], "answer": "wood"}, '
                '"where": {"options": ["in the workshop", "under the sea", "in the sky", "on the moon"], "answer": "in the workshop"}, '
                '"when": {"options": ["before cutting", "while sleeping", "while swimming", "before he was born"], "answer": "before cutting"}, '
                '"why": {"options": ["to build a table", "to grow wings", "to make it rain", "to turn into a fish"], "answer": "to build a table"}}')
EXAMPLE_ANSWERS = {"who": "carpenter", "what": "wood", "where": "in the workshop", "when": "before cutting", "why": "to build a table"}

# JSON schema the app hands to MLC's constrained decoding (LlmService.scenarioSchema)
_Q_SCHEMA = {"type": "object", "properties": {"options": {"type": "array", "items": {"type": "string"}},
                                              "answer": {"type": "string"}}, "required": ["options", "answer"]}
SCENARIO_SCHEMA = {"type": "object", "properties": {k: _Q_SCHEMA for k in QUESTIONS}, "required": list(QUESTIONS)}

def third_person(verb: str) -> str:  # Scenario.thirdPerson
    irregular = {"have": "has", "be": "is", "go": "goes", "do": "does"}
    if verb in irregular:
        return irregular[verb]
    if re.search(r"(s|x|z|ch|sh|o)$", verb):
        return verb + "es"
    if re.search(r"[^aeiou]y$", verb):
        return verb[:-1] + "ies"
    return verb + "s"

def long_prompt(verb: str, avoid: list[str] | None = None) -> str:  # LlmService.userPrompt
    avoid = avoid or []
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
            f'Example for "measure": {EXAMPLE_JSON}')

def short_prompt(verb: str, avoid: list[str] | None = None) -> str:
    avoid = avoid or []
    return f'VNeST exercise for the verb "{verb}".' + (f" Not these people: {', '.join(avoid)}." if avoid else "")

def prompt_for(style: str, verb: str, avoid: list[str] | None = None) -> str:
    return {"long": long_prompt, "short": short_prompt}[style](verb, avoid)

def avoid_from_prompt(user_text: str) -> list[str]:
    """Recover the 'not these people' list from a dataset prompt (either style)."""
    m = re.search(r"\(not ([^)]*)\)", user_text) or re.search(r"Not these people: ([^.]*)\.", user_text)
    return [x.strip() for x in m.group(1).split(",")] if m else []

# ---------------------------------------------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------------------------------------------
def load_jsonl(path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]

def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def items_from_split(rows: list[dict], split: str) -> list[dict]:
    """One evaluation item per dataset example: verb, avoid list, and the reference exercise."""
    items = []
    for i, r in enumerate(rows):
        user = r["messages"][1]["content"]
        items.append({"split": split, "idx": i, "verb": r["meta"]["verb"], "avoid": avoid_from_prompt(user),
                      "ref_agent": r["meta"]["agent"], "ref_patient": r["meta"]["patient"],
                      "ref_json": r["messages"][2]["content"], "dataset_prompt_style": r["meta"].get("prompt", "")})
    return items

def check_split_verbs(train_rows, val_rows, test_rows) -> dict:
    """Project rule: verbs never cross splits. Returns overlaps (all must be empty)."""
    verbs = lambda rows: {r["meta"]["verb"] for r in rows}
    tr, va, te = verbs(train_rows), verbs(val_rows), verbs(test_rows)
    return {"train&val": sorted(tr & va), "train&test": sorted(tr & te), "val&test": sorted(va & te),
            "test_verbs": sorted(te), "val_verbs": sorted(va)}

# ---------------------------------------------------------------------------------------------------------------
# Scoring: ONE definition for every model (RESEARCH project skill §3)
# ---------------------------------------------------------------------------------------------------------------
GENERIC_WHO = {"person", "a person", "someone", "somebody", "people", "human", "a human", "anyone", "they", "you", "we"}

# Person words (from vnest_dataset/scripts/common.py PEOPLE); used to tell whether "who" is a person.
PEOPLE = set("""chef cook mother father doctor nurse teacher farmer driver student mechanic child baby artist carpenter
gardener painter waiter waitress baker pilot fisherman dentist plumber electrician tailor barber hairdresser cashier
singer musician soldier policeman firefighter postman mailman librarian scientist builder janitor cleaner housekeeper
butcher shopkeeper grandmother grandfather boy girl man woman kid parent athlete player golfer swimmer hunter writer
author poet secretary vet veterinarian pharmacist surgeon photographer shepherd milkman maid nanny lifeguard coach
referee judge lawyer banker clerk husband wife friend neighbor cowboy pitcher homeowner worker chemist fireman sailor
captain miner engineer architect dancer actor actress priest teenager brother sister son daughter aunt uncle customer
shopper tourist camper florist grocer jockey rancher potter weaver knitter sculptor drummer pianist guitarist violinist
typist mom dad grandma grandpa toddler bartender housewife homemaker gardner lumberjack plasterer roofer welder
handyman janitress cleaner maid server host hostess""".split())

def clean_option(s) -> str:  # Scenario.clean
    s = str(s).strip()
    s = re.sub(r"[.!?]+$", "", s)
    s = re.sub(r"\s+", " ", s)
    return s.lower()

def strip_det(s: str) -> str:
    s = s.strip().lower()
    for a in ("a ", "an ", "the ", "some "):
        if s.startswith(a):
            return s[len(a):]
    return s

def app_accept(obj) -> tuple[dict | None, str | None]:
    """Exact port of Scenario.fromModel (vnest_app/lib/data/scenario.dart). Returns (questions, None) or (None, reason).
    questions[k] = {"options": [answer + first 3 other distinct options], "answer": answer}."""
    if not isinstance(obj, dict):
        return None, "not a JSON object"
    qs = {}
    for k in QUESTIONS:
        raw = obj.get(k)
        if not isinstance(raw, dict):
            return None, f'missing "{k}"'
        answer = clean_option(raw.get("answer") if raw.get("answer") is not None else "")
        options = []
        opts_raw = raw.get("options")
        for o in (opts_raw if isinstance(opts_raw, list) else []):
            c = clean_option(o)
            if c and c not in options:
                options.append(c)
        if not answer:
            return None, f"{k}: empty answer"
        if answer not in options:
            return None, f'{k}: answer "{answer}" is not one of the options'
        wrong = [o for o in options if o != answer]
        if len(wrong) < 3:
            return None, f"{k}: fewer than 4 different options"
        picked = [answer] + wrong[:3]
        for o in picked:
            if len(o.split(" ")) > 6:
                return None, f'{k}: option too long: "{o}"'
        qs[k] = {"options": picked, "answer": answer}
    if qs["who"]["answer"] == qs["what"]["answer"]:
        return None, "who and what are the same"
    return qs, None

def extract_json(text: str):
    """The model's JSON: the whole text, else the first {...} block (free decoding may add prose or ``` fences)."""
    t = text.strip()
    try:
        return json.loads(t), "whole"
    except Exception:
        pass
    m = re.search(r"\{.*\}", t, re.S)
    if m:
        try:
            return json.loads(m.group(0)), "embedded"
        except Exception:
            pass
    return None, "none"

def known_valid(items: list[dict]) -> dict:
    """Per verb: agents and objects that appear in reference exercises (automatic proxy for 'is this answer valid')."""
    out = {}
    for it in items:
        d = out.setdefault(it["verb"], {"agents": set(), "patients": set()})
        d["agents"].add(it["ref_agent"])
        d["patients"].add(it["ref_patient"])
    return out

def score_output(text: str, verb: str, refs: dict) -> dict:
    """Every per-output metric. refs = known_valid(...)[verb]. All metrics are automatic; none is a therapist judgement."""
    obj, how = extract_json(text)
    qs, reason = app_accept(obj) if obj is not None else (None, "no JSON found")
    row = {"json_found": obj is not None, "json_how": how, "accepted": qs is not None, "reject_reason": reason or ""}
    raw_answers = {}
    if isinstance(obj, dict):
        for k in QUESTIONS:
            q = obj.get(k)
            raw_answers[k] = clean_option(q.get("answer", "")) if isinstance(q, dict) else ""
    for k in QUESTIONS:
        row[f"{k}_answer"] = raw_answers.get(k, "")
    # copying the long prompt's worked example (measured on raw answers, accepted or not)
    row["n_example_answers"] = sum(raw_answers.get(k) == v for k, v in EXAMPLE_ANSWERS.items())
    row["copies_example"] = row["n_example_answers"] >= 2
    who = strip_det(raw_answers.get("who", ""))
    row["generic_who"] = who in GENERIC_WHO or raw_answers.get("who", "") in GENERIC_WHO
    row["who_is_person"] = who in PEOPLE
    row["who_known_valid"] = who in refs.get("agents", set())
    row["what_known_valid"] = strip_det(raw_answers.get("what", "")) in refs.get("patients", set())
    # distractors that are known to be valid answers (only checkable for accepted outputs)
    bad_who = bad_what = 0
    if qs:
        for o in qs["who"]["options"][1:]:
            if strip_det(o) in PEOPLE or strip_det(o) in refs.get("agents", set()):
                bad_who += 1
        for o in qs["what"]["options"][1:]:
            if strip_det(o) in refs.get("patients", set()):
                bad_what += 1
    row["bad_who_distractors"] = bad_who
    row["bad_what_distractors"] = bad_what
    row["any_bad_distractor"] = (bad_who + bad_what) > 0
    if isinstance(obj, dict):
        firsts = []
        for k in QUESTIONS:
            q = obj.get(k)
            if isinstance(q, dict) and isinstance(q.get("options"), list) and q["options"]:
                firsts.append(clean_option(q["options"][0]) == clean_option(q.get("answer", "")))
        row["answer_first_all"] = bool(firsts) and all(firsts) and len(firsts) == 5
    else:
        row["answer_first_all"] = False
    return row

METRICS = ["json_found", "accepted", "copies_example", "generic_who", "who_is_person", "who_known_valid",
           "what_known_valid", "any_bad_distractor", "answer_first_all"]

# ---------------------------------------------------------------------------------------------------------------
# Per-part format (dataset v2; the app writes one question per request; RESEARCH_LOG decisions 2026-11-11, Entries 8-9)
# Everything here is a port of vnest_app/lib/services/llm_service.dart (partSystemPrompt, partSchema, partPrompt,
# partTries) and vnest_app/lib/data/scenario.dart (partFromModel, checkContent, checkWhoWhat, noun).
# test_vnest_common.py checks these against the app's source and against every v2 example.
# ---------------------------------------------------------------------------------------------------------------
PART_SYSTEM_PROMPT = ("You write Verb Network Strengthening Treatment (VNeST) exercises for adults with aphasia. "
                      "Each question has one correct answer and 3 wrong options that are clearly impossible. "
                      "Use short, very common, concrete English words. "
                      'Reply only with JSON: {"answer": "...", "wrong1": "...", "wrong2": "...", "wrong3": "..."}.')
PART_FIELDS = ("answer", "wrong1", "wrong2", "wrong3")
PART_SCHEMA = {"type": "object", "properties": {k: {"type": "string"} for k in PART_FIELDS},
               "required": list(PART_FIELDS), "additionalProperties": False}
PART_TRIES = 3          # the app redoes a failed part up to 3 times in total (LlmService.partTries)
PART_MAX_NEW_TOKENS = 48  # the app's limit per question

# Scenario.genericPeople / Scenario.instructionEchoes (the app's content checks; not the same set as GENERIC_WHO above)
APP_GENERIC_PEOPLE = {"person", "someone", "somebody", "people", "anyone", "anybody", "human", "a human", "man", "woman",
                      "they", "you", "everyone", "adult", "patient"}
INSTRUCTION_ECHOES = ("usual place", "usual time", "usual reason", "a person who", "person who", "things that cannot",
                      "nobody can", "impossible place", "impossible time", "silly reason", "wrong option",
                      "correct answer", "the answer")

# Scenario.questionWords / timeWords / whenStarters / placeWords (test_vnest_common.py checks they equal the app's)
QUESTION_WORDS = {"who", "what", "where", "when", "why", "how"}
TIME_WORDS = {
    "morning", "afternoon", "evening", "night", "day", "days", "daily", "week", "weeks", "weekend", "weekends", "weekday",
    "month", "months", "year", "years", "spring", "summer", "autumn", "fall", "winter", "season", "breakfast", "lunch",
    "lunchtime", "dinner", "supper", "meal", "meals", "mealtime", "bedtime", "naptime", "playtime", "recess", "noon",
    "midnight", "dawn", "sunrise", "sunset", "time", "hour", "hours", "minute", "minutes", "today", "tomorrow", "yesterday",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "sundays", "semester", "holiday",
    "holidays", "birthday", "christmas", "am", "pm", "shift", "class", "lesson", "lessons", "start", "end", "way"}
WHEN_STARTERS = {"after", "before", "during", "while", "every", "once", "twice", "each", "until"}
PLACE_WORDS = {
    "home", "house", "kitchen", "garden", "yard", "park", "office", "room", "bedroom", "bathroom", "store", "shop",
    "market", "field", "farm", "garage", "street", "road", "beach", "river", "lake", "restaurant", "bakery", "church",
    "hospital", "classroom", "library", "studio", "workshop", "stadium", "gym", "pool", "barn", "city", "town", "village"}

def content_problem(part: str, answer: str, options: list[str], verb: str = "") -> str | None:
    """Port of Scenario.checkContent. Returns the reason the part is rejected, or None."""
    words = answer.split(" ")
    if part == "who" and noun(answer) in APP_GENERIC_PEOPLE:
        return f'who: "{answer}" is not a particular kind of person'
    if words[0] in QUESTION_WORDS:
        return f'{part}: "{answer}" repeats the question'
    for o in options:
        for e in INSTRUCTION_ECHOES:
            if e in o:
                return f'{part}: "{o}" repeats the instructions'
    if part == "why" and verb:
        rest = [w for w in (words[1:] if words[0] == "to" else words) if w not in {"it", "them", "the", "a", "an"}]
        stem = verb[:-1] if len(verb) > 4 else verb
        if not rest or all(w.startswith(stem) for w in rest):
            return f'why: "{answer}" only repeats the verb'
    if part == "when" and words[0] not in WHEN_STARTERS and not (set(words) & TIME_WORDS) and (set(words) & PLACE_WORDS):
        return f'when: "{answer}" is a place, not a time'
    return None

def noun(s: str) -> str:  # Scenario.noun: "a chef" -> "chef"
    return re.sub(r"^(a|an|the)\s+", "", s)

def part_prompt(verb: str, part: str, done: dict, avoid: list[str] | None = None) -> str:
    """LlmService.partPrompt. done = {part: answer} for the parts before this one (answers as the app holds them, cleaned)."""
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
    if part == "why":
        return (f"{head} The {a('who')} {v3} the {a('what')} {done['where']} {done['when']} ___. "
                'Answer: the usual reason, starting with "to" (2 to 5 words). Wrong: 3 silly reasons.')
    raise ValueError(part)

def avoid_from_part_prompt(user_text: str) -> list[str]:
    m = re.search(r"The answer must not be: (.*)\.$", user_text)
    return [x.strip() for x in m.group(1).split(",")] if m else []

def part_accept(part: str, obj, verb: str = "") -> tuple[dict | None, str | None]:
    """Port of Scenario.partFromModel + Scenario.checkContent (the app's checks on ONE question).
    Accepts the fixed-field reply {"answer", "wrong1", "wrong2", "wrong3"} and the older {"options": [...], "answer"}.
    Returns ({"options": [answer + 3 others], "answer": answer}, None) or (None, reason). who != what is checked in score_chain."""
    if not isinstance(obj, dict):
        return None, f"{part}: not a JSON object"
    answer = clean_option(obj.get("answer") if obj.get("answer") is not None else "")
    listed = [obj.get(k) for k in PART_FIELDS] if "wrong1" in obj else (obj.get("options") if isinstance(obj.get("options"), list) else [])
    options = []
    for o in listed:
        if o is None:
            continue
        c = clean_option(o)
        if c and c not in options:
            options.append(c)
    if not answer:
        return None, f"{part}: empty answer"
    if answer not in options:
        return None, f'{part}: answer "{answer}" is not one of the options'
    wrong = [o for o in options if o != answer]
    if len(wrong) < 3:
        return None, f"{part}: fewer than 4 different options"
    picked = [answer] + wrong[:3]
    for o in picked:
        if len(o.split(" ")) > 6:
            return None, f'{part}: option too long: "{o}"'
    problem = content_problem(part, answer, picked, verb)
    if problem:
        return None, problem
    return {"options": picked, "answer": answer}, None

def part_items_from_split(rows: list[dict], split: str) -> list[dict]:
    """One item per v2 example (one question). 'done' holds the reference answers of the earlier parts of the same exercise
    (rows are grouped by exercise, who..why in order), so the exact dataset prompt can be rebuilt (teacher forcing)."""
    items, done, group = [], {}, None
    for i, r in enumerate(rows):
        m = r["meta"]
        g = (m["sentence_id"], m.get("variant", 0))
        if g != group:
            group, done = g, {}
        ref = json.loads(r["messages"][2]["content"])
        items.append({"split": split, "idx": i, "verb": m["verb"], "part": m["part"], "sentence_id": m["sentence_id"],
                      "variant": m.get("variant", 0), "avoid": avoid_from_part_prompt(r["messages"][1]["content"]),
                      "done": dict(done), "ref_answer": clean_option(ref["answer"]), "ref_reply": r["messages"][2]["content"],
                      "ref_agent": m["agent"], "ref_patient": m["patient"]})
        done[m["part"]] = clean_option(ref["answer"])
    return items

def score_part(text: str, part: str, verb: str, refs: dict, ref_answer: str = "") -> dict:
    """Every per-reply metric for one question. refs = known_valid(items)[verb]. All automatic; none is a therapist judgement."""
    obj, how = extract_json(text)
    q, reason = part_accept(part, obj, verb) if obj is not None else (None, "no JSON found")
    raw_answer = clean_option(obj.get("answer", "")) if isinstance(obj, dict) else ""
    row = {"json_found": obj is not None, "json_how": how, "accepted": q is not None, "reject_reason": reason or "",
           "answer": raw_answer, "answer_matches_ref": bool(ref_answer) and noun(raw_answer) == noun(clean_option(ref_answer))}
    opts = q["options"] if q else []
    row["echoes_instructions"] = isinstance(reason, str) and ("repeats the instructions" in reason or "repeats the question" in reason)
    row["generic_who"] = part == "who" and noun(raw_answer) in (APP_GENERIC_PEOPLE | GENERIC_WHO)
    row["who_is_person"] = part == "who" and noun(raw_answer) in PEOPLE
    row["who_known_valid"] = part == "who" and noun(raw_answer) in refs.get("agents", set())
    row["what_known_valid"] = part == "what" and noun(raw_answer) in refs.get("patients", set())
    bad = 0  # wrong options known to be valid answers (who: a person or a known doer; what: a known object)
    for o in opts[1:]:
        if part == "who" and (noun(o) in PEOPLE or noun(o) in refs.get("agents", set())):
            bad += 1
        elif part == "what" and noun(o) in refs.get("patients", set()):
            bad += 1
    row["bad_distractors"] = bad
    row["any_bad_distractor"] = bad > 0
    return row

PART_METRICS = ["json_found", "accepted", "answer_matches_ref", "echoes_instructions", "generic_who", "who_is_person",
                "who_known_valid", "what_known_valid", "any_bad_distractor"]

def score_chain(attempts: dict, verb: str, refs: dict) -> dict:
    """The app's behaviour for one exercise written part by part (LlmService.generateScenario): parts in order, each tried up to
    PART_TRIES times, stop at the first part that never passes; 'what' must differ from 'who'.
    attempts = {part: [reply text of try 1, try 2, ...]} in the order generated. Returns exercise-level metrics."""
    out = {"exercise_accepted": False, "failed_part": "", "fail_reason": "", "total_tries": 0}
    who = None
    for part in QUESTIONS:
        tries = attempts.get(part, [])[:PART_TRIES]
        passed = None
        for i, text in enumerate(tries, 1):
            out["total_tries"] += 1
            obj, _ = extract_json(text)
            q, reason = part_accept(part, obj, verb) if obj is not None else (None, "no JSON found")
            if q and part == "what" and who is not None and noun(q["answer"]) == noun(who):
                q, reason = None, "who and what are the same"
            if q:
                passed = q
                out[f"{part}_tries"] = i
                break
            out["fail_reason"] = reason
        if passed is None:
            out["failed_part"] = part
            out[f"{part}_tries"] = len(tries)
            return out
        if part == "who":
            who = passed["answer"]
    out["exercise_accepted"] = True
    out["fail_reason"] = ""
    return out

CHAIN_METRICS = ["exercise_accepted"]

def chain_items_from_split(rows: list[dict], split: str) -> list[dict]:
    """One item per EXERCISE of a v2 split (the 5 examples of one sentence/variant), for the chained protocol: the model writes
    who, then what given its own who, and so on, as the app does. 'avoid' comes from the exercise's "who" prompt."""
    items, by = [], {}
    for r in rows:
        m = r["meta"]
        key = (m["sentence_id"], m.get("variant", 0))
        if key not in by:
            by[key] = {"split": split, "exercise_id": f"{split}:{m['sentence_id']}#{m.get('variant', 0)}", "verb": m["verb"],
                       "sentence_id": m["sentence_id"], "variant": m.get("variant", 0), "avoid": [], "ref": {},
                       "ref_agent": m["agent"], "ref_patient": m["patient"]}
            items.append(by[key])
        it = by[key]
        it["ref"][m["part"]] = clean_option(json.loads(r["messages"][2]["content"])["answer"])
        if m["part"] == "who":
            it["avoid"] = avoid_from_part_prompt(r["messages"][1]["content"])
    for it in items:
        assert set(it["ref"]) == set(QUESTIONS), it["exercise_id"]
    return items

def stop_token_ids(tokenizer, generation_eos=None) -> list[int]:
    """Every end-of-turn token the model may use, passed to generate() explicitly so stopping never relies on defaults:
    the generation config's eos ids, the tokenizer's eos, and <|eot_id|> (Llama 3), <|im_end|> (Qwen), <|end_of_text|>
    when the vocabulary has them. (From the NB 2.02 stop-token note, notes/nb2.02_stop_token_fix.patch.)"""
    ids = set(generation_eos if isinstance(generation_eos, (list, tuple, set)) else [generation_eos] if generation_eos is not None else [])
    ids.add(getattr(tokenizer, "eos_token_id", None))
    vocab = tokenizer.get_vocab() if hasattr(tokenizer, "get_vocab") else {}
    for t in ("<|eot_id|>", "<|im_end|>", "<|end_of_text|>"):
        if t in vocab:
            ids.add(vocab[t])
    return sorted(i for i in ids if isinstance(i, int))

def bootstrap_ci(values, groups, n_boot: int = 2000, seed: int = 0, alpha: float = 0.05):
    """Mean with a CI that resamples GROUPS (verbs), not items. Returns (mean, lo, hi)."""
    import numpy as np
    v = np.asarray(values, dtype=float)
    g = np.asarray(groups)
    if len(v) == 0:
        return float("nan"), float("nan"), float("nan")
    ug = np.unique(g)
    by = [v[g == x] for x in ug]
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(n_boot):
        pick = rng.integers(0, len(ug), len(ug))
        means.append(np.concatenate([by[i] for i in pick]).mean())
    lo, hi = np.quantile(means, [alpha / 2, 1 - alpha / 2])
    return float(v.mean()), float(lo), float(hi)

def summarise(df, by: list[str], group_col: str = "verb", metrics: list[str] | None = None):
    """One row per group in `by`: n, and for each metric (default METRICS) mean % with a verb-resampled 95% CI."""
    import pandas as pd
    out = []
    for keys, sub in df.groupby(by, dropna=False):
        keys = keys if isinstance(keys, tuple) else (keys,)
        row = dict(zip(by, keys))
        row["n"] = len(sub)
        row["n_verbs"] = sub[group_col].nunique()
        for m in (metrics or METRICS):
            mean, lo, hi = bootstrap_ci(sub[m].astype(float).values, sub[group_col].values)
            row[f"{m}_pct"] = round(100 * mean, 1)
            row[f"{m}_ci"] = f"{100 * lo:.1f}-{100 * hi:.1f}"
        if "gen_tokens" in sub:
            row["mean_gen_tokens"] = round(float(sub["gen_tokens"].mean()), 1)
        out.append(row)
    return pd.DataFrame(out)

# ---------------------------------------------------------------------------------------------------------------
# Hugging Face I/O (retries; every upload also kept locally)
# ---------------------------------------------------------------------------------------------------------------
def _retry(fn, what: str, tries: int = 6):
    delay = 5
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # 412/429/5xx/network
            msg = str(e)
            transient = any(s in msg for s in ("412", "429", "500", "502", "503", "504", "Timeout", "timed out",
                                                "Connection", "Temporary", "rate"))
            if i == tries - 1 or not transient:
                raise
            print(f"[hf] {what}: {msg[:120]} -> retry in {delay}s", flush=True)
            time.sleep(delay)
            delay = min(delay * 2, 120)

def offline() -> bool:
    """VNEST_OFFLINE=1: nothing is uploaded; downloads come from VNEST_OFFLINE_DIR (a local mirror of the outputs repo) or
    from files this run already wrote. For local smoke tests that must not write into the real outputs repo."""
    return os.environ.get("VNEST_OFFLINE") == "1"

def hf_api(token: str | None = None):
    from huggingface_hub import HfApi
    return HfApi(token=token or os.environ.get("HF_TOKEN") or None)

def whoami(token: str | None = None) -> str:
    if offline():
        return HF_USER
    try:
        return hf_api(token).whoami()["name"]
    except Exception as e:
        return f"(unknown: {str(e)[:80]})"

def ensure_outputs_repo(token=None):
    if offline():
        return
    api = hf_api(token)
    _retry(lambda: api.create_repo(OUTPUTS_REPO, repo_type="dataset", private=OUTPUTS_PRIVATE, exist_ok=True), "create repo")

def ensure_model_repo(run: str, token=None) -> str:
    """Create the run's model repo with the project's visibility (MODEL_REPOS_PRIVATE), or fix an existing one's."""
    repo = model_repo(run)
    if offline():
        return repo
    api = hf_api(token)
    _retry(lambda: api.create_repo(repo, repo_type="model", private=MODEL_REPOS_PRIVATE, exist_ok=True), f"create {repo}")
    try:
        _retry(lambda: api.update_repo_settings(repo, private=MODEL_REPOS_PRIVATE), f"visibility {repo}")
    except Exception as e:
        print(f"[hf] could not set visibility of {repo}: {str(e)[:80]}")
    return repo

def hf_model_upload_folder(local_dir, repo: str, path_in_repo: str, message: str, token=None, delete_patterns=None):
    """Upload a folder into a model repo (one commit). delete_patterns removes old files there first (rolling checkpoints)."""
    if offline():
        print(f"[offline] not uploaded: {repo}/{path_in_repo}", flush=True)
        return
    api = hf_api(token)
    _retry(lambda: api.upload_folder(repo_id=repo, repo_type="model", folder_path=str(local_dir), path_in_repo=path_in_repo or None,
                                     commit_message=message, delete_patterns=delete_patterns), f"upload {repo}/{path_in_repo}")

def hf_model_download_folder(repo: str, path_in_repo: str, local_dir, token=None):
    """Download one folder of a model repo into local_dir/<path_in_repo>. Returns that Path, or None if it doesn't exist."""
    local = Path(local_dir) / path_in_repo if path_in_repo else Path(local_dir)
    if offline():
        return local if local.is_dir() and any(local.iterdir()) else None
    from huggingface_hub import snapshot_download
    try:
        _retry(lambda: snapshot_download(repo, repo_type="model", local_dir=str(local_dir),
                                         allow_patterns=[f"{path_in_repo}/*"] if path_in_repo else None,
                                         token=token or os.environ.get("HF_TOKEN") or None), f"download {repo}/{path_in_repo}")
    except Exception as e:
        if any(x in str(e) for x in ("404", "RepositoryNotFound", "not found", "Not Found")):
            return None
        raise
    return local if local.is_dir() and any(local.iterdir()) else None

def hf_exists(path_in_repo: str, token=None) -> bool:
    api = hf_api(token)
    try:
        return _retry(lambda: api.file_exists(OUTPUTS_REPO, path_in_repo, repo_type="dataset"), f"exists {path_in_repo}")
    except Exception:
        return False

def hf_download(path_in_repo: str, local_dir, token=None):
    """Download one file from the outputs repo into local_dir (keeping its path). Returns the local Path or None."""
    if offline():
        import shutil
        local = Path(local_dir) / path_in_repo
        mirror = Path(os.environ.get("VNEST_OFFLINE_DIR", "")) / path_in_repo if os.environ.get("VNEST_OFFLINE_DIR") else None
        if mirror is not None and mirror.is_file():
            local.parent.mkdir(parents=True, exist_ok=True)
            if mirror.resolve() != local.resolve():
                shutil.copyfile(mirror, local)
            return local
        return local if local.is_file() else None
    from huggingface_hub import hf_hub_download
    try:
        p = _retry(lambda: hf_hub_download(OUTPUTS_REPO, path_in_repo, repo_type="dataset", local_dir=str(local_dir),
                                           token=token or os.environ.get("HF_TOKEN") or None), f"download {path_in_repo}")
        return Path(p)
    except Exception as e:
        if "404" in str(e) or "EntryNotFound" in type(e).__name__ or "not found" in str(e).lower():
            return None
        raise

def hf_upload(local_path, path_in_repo: str, message: str, token=None):
    if offline():
        print(f"[offline] not uploaded: {path_in_repo}", flush=True)
        return
    api = hf_api(token)
    _retry(lambda: api.upload_file(path_or_fileobj=str(local_path), path_in_repo=path_in_repo, repo_id=OUTPUTS_REPO,
                                   repo_type="dataset", commit_message=message), f"upload {path_in_repo}")

def put_json(obj, path_in_repo: str, local_root, message: str, token=None) -> Path:
    local = Path(local_root) / path_in_repo
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(json.dumps(obj, indent=1, default=str))
    hf_upload(local, path_in_repo, message, token)
    return local

def hf_json(path_in_repo: str, local_root, token=None):
    p = hf_download(path_in_repo, local_root, token)
    return json.loads(p.read_text()) if p else None

def read_csv(path):
    import pandas as pd
    try:
        return pd.read_csv(path, keep_default_na=False)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()

# ---------------------------------------------------------------------------------------------------------------
# Stages (done-markers on HF) and the run lock
# ---------------------------------------------------------------------------------------------------------------
class Stages:
    def __init__(self, run: str, enabled: dict, force: set, local_root, token=None):
        self.run, self.enabled, self.force, self.root, self.token = run, enabled, set(force), Path(local_root), token

    def marker(self, stage: str):
        return hf_json(done_path(self.run, stage), self.root, self.token)

    def should_run(self, stage: str) -> bool:
        if not self.enabled.get(stage, True):
            print(f"[stage] {stage}: switched off in STAGES")
            return False
        if stage in self.force:
            print(f"[stage] {stage}: forced")
            return True
        m = self.marker(stage)
        if m:
            print(f"[stage] {stage}: already done at {m.get('time')} -> reading results back")
            return False
        return True

    def mark_done(self, stage: str, info: dict):
        info = {**info, "stage": stage, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "module_version": VERSION}
        put_json(info, done_path(self.run, stage), self.root, f"{self.run}: {stage} done", self.token)

def claim_run(work_dir) -> Path:
    """One process per run per machine. Takes over a lock held by a dead process or by this process."""
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    lock = work_dir / "run.lock"
    if lock.exists():
        try:
            pid = int(lock.read_text().split()[0])
        except Exception:
            pid = -1
        alive = False
        if pid > 0 and pid != os.getpid():
            try:
                os.kill(pid, 0)
                alive = True
            except OSError:
                alive = False
        if alive:
            raise RuntimeError(f"run already active in process {pid} on this machine ({lock}); stop it or delete the lock")
    lock.write_text(f"{os.getpid()} {socket.gethostname()} {time.strftime('%Y-%m-%d %H:%M:%S')}")
    return lock

# ---------------------------------------------------------------------------------------------------------------
# Resource tracking
# ---------------------------------------------------------------------------------------------------------------
def gpu_name() -> str:
    try:
        import torch
        return torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu"
    except Exception:
        return "unknown"

@contextlib.contextmanager
def track_resources(stage: str, log_fn=None, csv_path=None, **extra):
    """Wall time, GPU hours, peak GPU/RAM. Writes one row to csv_path (merged by column name) and to W&B summary."""
    import pandas as pd
    torch = None
    try:
        import torch as _t
        torch = _t if _t.cuda.is_available() else None
    except Exception:
        pass
    if torch:
        torch.cuda.reset_peak_memory_stats()
    t0 = time.time()
    rec = {"stage": stage, "status": "failed", "gpu_name": gpu_name(), **extra}
    try:
        yield rec
        rec["status"] = "ok"
    finally:
        wall = time.time() - t0
        rec["wall_time_h"] = round(wall / 3600, 4)
        rec["gpu_hours"] = rec["wall_time_h"] if torch else 0.0
        rec["peak_gpu_mem_gb"] = round(torch.cuda.max_memory_allocated() / 1e9, 2) if torch else 0.0
        ram = max(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)
        rec["peak_ram_gb"] = round(ram / 1e6, 2)  # ru_maxrss is KiB on Linux
        if rec.get("gen_tokens"):
            rec["tokens_per_s"] = round(rec["gen_tokens"] / max(wall, 1e-6), 1)
        rec["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
        if csv_path:
            p = Path(csv_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            old = read_csv(p) if p.exists() else pd.DataFrame()
            pd.concat([old, pd.DataFrame([rec])], ignore_index=True).to_csv(p, index=False)
        if log_fn and rec["status"] == "ok":
            log_fn({f"{stage}/{k}": v for k, v in rec.items() if isinstance(v, (int, float))})
        print(f"[resources] {stage}: {rec['status']} | {rec['wall_time_h']} h | peak GPU {rec['peak_gpu_mem_gb']} GB"
              + (f" | {rec['tokens_per_s']} tok/s" if 'tokens_per_s' in rec else ""), flush=True)

# ---------------------------------------------------------------------------------------------------------------
# Weights & Biases
# ---------------------------------------------------------------------------------------------------------------
def wandb_init(run: str, job_type: str, tags: list[str], config: dict):
    """Returns (run_obj, log_fn). Without WANDB_API_KEY returns (None, None)."""
    if not os.environ.get("WANDB_API_KEY"):
        print("[wandb] no WANDB_API_KEY: skipping W&B for this run")
        return None, None
    import wandb
    kw = dict(entity=WANDB_ENTITY, project=WANDB_PROJECT, name=run, resume="allow", job_type=job_type,
              tags=tags, config=config)
    try:
        wb = wandb.init(id=run, **kw)
    except Exception as e:
        if "deleted" in str(e).lower() or "in use" in str(e).lower():
            alt = f"{run}-r{time.strftime('%m%d%H%M')}"
            print(f"[wandb] id {run} unusable ({str(e)[:80]}); logging to {alt}")
            wb = wandb.init(id=alt, **{**kw, "tags": tags + ["wandb-id-fallback"]})
        else:
            raise

    def log_fn(d: dict):
        try:
            for k, v in d.items():
                wb.summary[k] = v
        except Exception as e:  # never let W&B break a stage
            print(f"[wandb] summary update skipped: {str(e)[:80]}")
    return wb, log_fn

def subset_md5(ids, n: int, salt: str = "vnest") -> list:
    """Deterministic nested subset: the n ids with the smallest md5(salt:id)."""
    return sorted(ids, key=lambda x: hashlib.md5(f"{salt}:{x}".encode()).hexdigest())[:n]
