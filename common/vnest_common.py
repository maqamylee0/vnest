"""Shared module for the VNeST exercise LLM notebooks (embedded into every notebook by tools/make_standalone.py).

Holds: project constants, naming, prompts, the ONE scoring definition (ported from the app's
Scenario.fromModel), HF I/O with retries, crash-safe stages, run lock, resource tracking, W&B init.
Import-time dependencies: standard library only (pandas/numpy/torch/hf/wandb imported lazily).

Changelog
- 1.0.0 (2026-11-10): first version, for NB 2_evaluation/01 (untuned baselines).
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

VERSION = "1.0.0"

# ---------------------------------------------------------------------------------------------------------------
# Project constants (decided 2026-11-10, see RESEARCH_LOG.md §4)
# ---------------------------------------------------------------------------------------------------------------
HF_USER = "emmilly"
OUTPUTS_REPO = f"{HF_USER}/vnest-exercise-llm-outputs"  # private dataset: data copy, preds, tables, markers, code
OUTPUTS_PRIVATE = True
MODEL_REPOS_PRIVATE = True  # TO DECIDE before the first model upload (licences); private until then
WANDB_ENTITY = "team-me-and-me"
WANDB_PROJECT = "vnest-exercise-llm"
DATA_VERSION = "v1"  # the 2026-11-10 dataset build

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

def summarise(df, by: list[str], group_col: str = "verb"):
    """One row per group in `by`: n, and for each metric mean % with a verb-resampled 95% CI."""
    import pandas as pd
    out = []
    for keys, sub in df.groupby(by, dropna=False):
        keys = keys if isinstance(keys, tuple) else (keys,)
        row = dict(zip(by, keys))
        row["n"] = len(sub)
        row["n_verbs"] = sub[group_col].nunique()
        for m in METRICS:
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

def hf_api(token: str | None = None):
    from huggingface_hub import HfApi
    return HfApi(token=token or os.environ.get("HF_TOKEN") or None)

def whoami(token: str | None = None) -> str:
    try:
        return hf_api(token).whoami()["name"]
    except Exception as e:
        return f"(unknown: {str(e)[:80]})"

def ensure_outputs_repo(token=None):
    api = hf_api(token)
    _retry(lambda: api.create_repo(OUTPUTS_REPO, repo_type="dataset", private=OUTPUTS_PRIVATE, exist_ok=True), "create repo")

def hf_exists(path_in_repo: str, token=None) -> bool:
    api = hf_api(token)
    try:
        return _retry(lambda: api.file_exists(OUTPUTS_REPO, path_in_repo, repo_type="dataset"), f"exists {path_in_repo}")
    except Exception:
        return False

def hf_download(path_in_repo: str, local_dir, token=None):
    """Download one file from the outputs repo into local_dir (keeping its path). Returns the local Path or None."""
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
