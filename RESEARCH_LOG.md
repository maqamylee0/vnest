# Research Log: Fine-tuning a Small On-Device LLM to Write VNeST Aphasia Exercises

> Working journal for the paper. Record everything, including what failed and why.
> Newest Experiment Log entries go at the **bottom** of section 7, so the history reads in order.
> Every notebook goes in the **Notebook register** (section 5) *before* it is first run.

---

## 1. Project Overview

| Item | Value |
|---|---|
| App | VNeST Practice (`vnest_app/`, Flutter, Android), offline Verb Network Strengthening Treatment practice for adults with aphasia |
| Current on-phone model | `Llama-3.2-3B-Instruct-q4f16_0-MLC` via MLC LLM (`vnest_app/lib/services/llm_service.dart`), ~1.7 GB |
| Model to fine-tune (student) | `Qwen/Qwen2.5-1.5B-Instruct` (about 2× faster than Llama-3.2-3B on the Galaxy Note 10, but poor at the task untuned) |
| Training data | `vnest_dataset/out/{train,validation,test}.jsonl` (844 / 45 / 85 examples, split by verb), see `vnest_dataset/docs/GENERATION.md` |
| Output the model must produce | The exercise JSON parsed by `vnest_app/lib/data/scenario.dart` (`Scenario.fromModel`): who / what / where / when / why, 4 options each, one answer |
| Test phone | Samsung Galaxy Note 10 (Snapdragon 855) |
| Start date | Before 2026-11-10 (dataset built 2026-11-10; tracking set up 2026-11-10) |

### Research questions
1. Can a fine-tuned 1.5B model write VNeST exercises as well as (or better than) an untuned 3B model, at about half the latency on a phone?
2. Does it generalise to verbs it never saw in training (the test split is held out by verb)?
3. Can a short prompt replace the long instruction prompt after fine-tuning, and how much latency does that save?
4. How much does 4-bit quantisation for the phone cost in exercise quality?

### Success criteria (to fill in)
- App acceptance rate (valid JSON that passes the app's checks) on test verbs: _TBD_ (e.g. ≥ 95 %)
- Exercise correctness judged by a therapist: _TBD_
- Latency per exercise on the Galaxy Note 10: _TBD_ (Llama-3.2-3B baseline ≈ 2 min, untuned Qwen ≈ 1 min)
- Model size on the phone: _TBD_

---

## 2. Environment & Reproducibility

### Development machine (laptop)
| Component | Spec |
|---|---|
| OS | Linux (kernel 6.8.0-85-generic) |
| GPU | NVIDIA GeForce RTX 2050 (4 GB VRAM) |
| Python | 3.12.3 (`uv` available at `~/.local/bin/uv`) |
| Marimo | `~/.local/bin/marimo` |
| Ollama | snap (`/snap/bin/ollama`), 0.40.2; teacher `llama3.1:8b` digest `46e0c10c039e` |

### Training machine (GPU server / Colab)
| Component | Spec |
|---|---|
| GPU | _fill in from the first run's environment dump_ |
| CPU / RAM | |

### Key software versions (fill in as installed)
| Package / tool | Version / commit |
|---|---|
| transformers | |
| torch | |
| peft / trl | |
| MLC LLM (app runtime) | Android release `Android-09262024` (`llama_q4f16_0_2d32572d8a4ab2af20a1f587ef6c8c63`); tvm4j from `mlc-ai/relax@2912b0fc` |
| `libtvm4j_runtime_packed.so` (arm64-v8a, **not in git**, 103,162,320 bytes) | SHA-256 `5b6b3a27cbf17372c81c8f354b46cd8858354e613d36c12179df8905a6d22cc0`; goes in `vnest_app/android/app/src/main/jniLibs/arm64-v8a/` |
| Version control | git, repo at `vnest/` (from 2026-11-10, Entry 4) |
| Dataset build | 2026-11-10, SHA-256 in `vnest_dataset/docs/GENERATION.md` §9 |

### Test devices (phones)
| Device | SoC | RAM | OS version |
|---|---|---|---|
| Samsung Galaxy Note 10 | Snapdragon 855 | | |

---

## 3. Planned Approach

1. **Dataset**: built (v1, 2026-11-10). Therapist review of `out/review_sample.csv` still to do.
2. **Baseline**: untuned Qwen2.5-1.5B and Llama-3.2-3B on the test verbs with the same scorer.
3. **Fine-tune**: Qwen2.5-1.5B-Instruct (LoRA or full, TO DECIDE) on `train.jsonl`, select on `validation.jsonl`.
4. **Evaluate** on test verbs: acceptance rate, copying-the-example rate, answer correctness, distractor validity, short vs long prompt.
5. **Export for the phone**: merge, quantise (q4f16) and compile for MLC LLM; check quality after quantisation.
6. **On-device**: latency, memory and quality on the Galaxy Note 10 inside the app.

---

## 4. Decisions Log

| Date | Decision | Rationale | Alternatives considered |
|---|---|---|---|
| ≤ 2026-11-10 | Fine-tune **Qwen2.5-1.5B-Instruct** as the phone model | About 1 min per exercise on the Note 10 against about 2 min for Llama-3.2-3B; its failures (copying the prompt example, "a person" as every "who") look like things training can fix | Keep untuned Llama-3.2-3B (slower, some wrong distractors and nonsense answers) |
| 2026-11-10 | Build our own dataset from ConceptNet + a teacher model | No public VNeST / aphasia exercise dataset found; McRae / Ferretti norms unreachable (404) | Thematic-fit norms; Edmonds' stimuli (kept for a future gold test set) |
| 2026-11-10 | who/what from ConceptNet `CapableOf`; where/when/why from **Llama-3.1-8B** (Ollama, temp 0.2) | Knowledge-base answers didn't fit their sentences (Entry 2) | ConceptNet/ATOMIC for every part (discarded) |
| 2026-11-10 | **Wrong options written in code**, never by a model | Model-written distractors were often actually correct | Teacher-written distractors |
| 2026-11-10 | Content word filter in code instead of the teacher's suitability flag | Teacher marked every sentence suitable, including weapons and alcohol | Trust the teacher flag |
| 2026-11-10 | **Split by verb**; test = cook, drive, paint, plant, wash; validation = chop, eat, lift, play, smell | Test measures unseen verbs (a therapist adding a verb); 5 not 14 held out to keep enough training data | Hold out all 14 app verbs (only 321 training sentences) |
| 2026-11-10 | 50/50 long (the app's) and short prompts in training | A fine-tuned model may not need the long prompt; prompt reading was ~40 of 124 s per exercise | Long prompt only |
| 2026-11-10 | Put `vnest/` under git; raw downloads, build output, the MLC engine binary and model weights stay out | Trace every result to exact code; large/regenerable files would bloat the history | No version control (as in `cdli`) |
| 2026-11-10 | Track the project like `cdli`: one `RESEARCH_LOG.md` with a notebook register, plus project skill `.claude/skills/vnest-exercise-llm/` | User wants every notebook, step and decision recorded for the paper; reuse a system that already works | Separate files per notebook |
| 2026-11-10 | **Rebuild the app's MLC engine (option A)** with models in the `q4f16_0` layout (weights stored "KN"), using a current MLC version | Entry 6: in the shipped engine Qwen's `q4f16_1` ("NK", the only difference in MLC's definition) prefills 5–10× slower than Llama-3B's `q4f16_0` on the Note10's Adreno 640; the same pipeline is needed to ship a fine-tuned model | B: keep the engine, use the short prompt and no JSON rule (measures speed only; leaves the cause unexplained) |
| 2026-11-10 | Engine gets **both Qwen2.5-1.5B (converted to q4f16_0) and Llama-3.2-1B-Instruct (q4f16_0)**, plus the current Llama-3.2-3B; compare speed on the phone and add a b1-style baseline for Llama-1B before choosing the student | User decision. Llama-1B is a similar size (1.24 B vs 1.54 B), is published by MLC in q4f16_0, and Llama decodes with the JSON rule at almost no cost; Qwen is stronger untuned. A compiled library only fits one model shape, so neither avoids the rebuild | Switch to Llama-1B now; Qwen only |
| 2026-11-10 | App starting verb list reduced to **one verb, "cook"** (`vnest_app/assets/therapist_verbs.json`; was 14) | User decision: short on-phone test runs (3 exercises instead of ~42 per model). "cook" is a test verb (never trained on), is in the b1 baseline, and has a reviewed fallback list | drive, wash; keep all 14 |
| 2026-11-10 | App can switch between on-device models (Model screen); Qwen2.5-1.5B uses the `qwen2_q4f16_1` library already packed in the MLC engine | No engine rebuild needed to test Qwen; a fine-tuned Qwen2.5-1.5B (q4f16_1) can reuse the same library | Recompile the engine with a new model library |
| 2026-11-10 | HF outputs repo `emmilly/vnest-exercise-llm-outputs` (private); W&B `team-me-and-me/vnest-exercise-llm` | Chosen by the user; private until licences are checked | |
| 2026-11-10 | Dataset v1 uploaded to the outputs repo under `data/v1/` with `SHA256SUMS`; notebooks verify the checksums | Remote GPU machines only have the notebook file; checksums tie every run to the exact v1 files | Separate dataset repo |
| 2026-11-10 | Baselines use **greedy** decoding (app: temperature 0.3), bf16 on GPU, 2 prompts × 2 decodings (schema-constrained like the app, and free) | Deterministic and batch-safe; the schema variant mirrors the app, the free one shows what the model does unaided | Sample at 0.3 with seeds |
| 2026-11-10 | Automatic scorer only for now (`vnest_common.score_output`): acceptance (port of `Scenario.fromModel`), copying, generic who, who is a person, answers/distractors vs known valid ones | No judge model or therapist yet; every number says it is automatic | LLM judge (later) |

---

## 5. Notebook Register

Every training / evaluation / export notebook, one row each. Add the row **before** the first run; update the
status after every run. Notebooks that produced results are never edited: fork them into a new number.

| NB | File | Purpose | Forked from | Status | Runs (W&B id / HF repo) | Log entry |
|---|---|---|---|---|---|---|
| 2.01 | `notebooks/marimo/2_evaluation/01_baseline_qwen25_untuned.py` | Baseline: untuned Qwen2.5-1.5B-Instruct on validation + test, long/short prompt × schema/free decoding, automatic scores | – | **done** 2026-11-10 (RTX PRO 6000, ~2 min generation); output export `2_evaluation/baseline_qwen_untuned_results.ipynb` | run `b1-qwen25-1.5b-instruct-untuned` (W&B id = run name); outputs in `emmilly/vnest-exercise-llm-outputs` | Entry 5 |

Status values: `draft` → `ready (offline checks pass)` → `running` → `done` / `failed` / `superseded by NB x`.

---

## 6. Results Summary

### 6.1 Test verbs (cook, drive, paint, plant, wash), 85 exercises

All numbers over **5 test verbs**; 95 % CIs resample verbs. All scores **automatic** (`vnest_common.score_output` 1.0.0) unless the column says review.
Greedy decoding, bf16 on GPU (not the phone's 4-bit model).

| Model | Prompt | Decoding | App acceptance % (CI) | Copies example % | Generic who % | Answer correct % (review) | Bad distractors % | Notes / NB |
|---|---|---|---|---|---|---|---|---|
| Qwen2.5-1.5B (untuned) | long | schema | 100.0 (100.0–100.0) | 0 | 43.5 | – | not copied yet¹ | NB 2.01, Entry 5 |
| Qwen2.5-1.5B (untuned) | long | free | 72.9 (38.8–95.0) | 0 | 43.5 | – | not copied yet¹ | NB 2.01 |
| Qwen2.5-1.5B (untuned) | short | schema | 2.4 (0.0–5.4) | 0 | 0.0 | – | – | NB 2.01 |
| Qwen2.5-1.5B (untuned) | short | free | 0.0 (0.0–0.0) | 0 | 0.0 | – | – | NB 2.01 |
| Llama-3.2-3B (untuned) | long | schema | | | | | | (b2, planned) |

¹ In `tables/b1__2.01__summary.csv` on HF (`any_bad_distractor_pct`); the download from the laptop timed out on 2026-11-10. The automatic check only covers who/what and only knows the dataset's objects, so it is a **lower bound** (Entry 5).

### 6.2 On-device (Galaxy Note 10)

| Model | Quant | Size | Load time | Time per exercise | Tokens/s | Notes |
|---|---|---|---|---|---|---|
| Llama-3.2-3B-Instruct | q4f16_0 | ~1.7 GB | | ≈ 2 min | | Entry 0 |
| Qwen2.5-1.5B-Instruct (untuned) | | | | ≈ 1 min | | Entry 0 |

---

## 7. Experiment Log

<!--
Template: copy for each new entry.

### [YYYY-MM-DD] Entry N: <short title>
**Goal:**
**Notebook / script:** (file, NB number, commit/hash of inputs)
**What we did:** (commands, settings: enough to reproduce)
**Results:** (numbers, outputs, file sizes, W&B run id, HF repo)
**Status:** ✅ Worked / ❌ Failed / ⚠️ Partial
**Issues & how we resolved them:**
**Decisions made:** (also add them to section 4)
**Takeaways / next steps:**
-->

### [≤ 2026-11-10] Entry 0: Untuned on-phone models on the app's prompt (backfilled)
**Goal:** See whether a phone-sized model can write VNeST exercises without training.

**What we did:** Ran the app's prompt on 14 verbs with Qwen2.5-1.5B and Llama-3.2-3B on the Galaxy Note 10.
(Exact date and raw outputs were not recorded; summary taken from `vnest_dataset/docs/GENERATION.md` §1.)

**Results:**
- Qwen2.5-1.5B: copied the prompt's worked example ("wood / in the workshop / before cutting / to build a table")
  for most verbs; "who" almost always "a person"; marked "what does a person wash? → a song" as correct. ≈ 1 min per exercise.
- Llama-3.2-3B: mostly sensible, but some "wrong" options were valid ("painter" for *paint*) and some answers were
  nonsense ("drive → when i was born"). ≈ 2 min per exercise; prompt reading ≈ 40 of 124 s.

**Status:** ⚠️ Partial. Neither model is good enough untuned.

**Takeaways / next steps:** Fine-tune the faster Qwen model on purpose-built data. Re-run this comparison properly
(same scorer, saved outputs) as the baseline once the evaluation notebook exists.

### [2026-11-10] Entry 1: Dataset, first attempt from knowledge bases only (discarded, backfilled)
**Goal:** Build training exercises entirely from ConceptNet and ATOMIC.

**What we did:** where from `AtLocation`, when from `HasPrerequisite` / ATOMIC `xNeed`, why from `MotivatedByGoal` / ATOMIC `xIntent`. 369 training examples.

**Results:** Answers didn't fit their sentences ("The boy carries the groceries / in the football game / after working hard / to travel").

**Status:** ❌ Failed.

**Issues & how we resolved them:** Places/goals were facts about the person or the verb in general, not this action. Replaced by a teacher model (Entry 2). Details: `vnest_dataset/docs/GENERATION.md` §6.1.

### [2026-11-10] Entry 2: Dataset v1 built (ConceptNet who/what + Llama-3.1-8B where/when/why + code distractors, backfilled)
**Goal:** A clean, reproducible fine-tuning dataset.

**Notebook / script:** `vnest_dataset/scripts/{extract_pairs,teacher_wh,assemble}.py`

**Results:** 711 pairs (64 verbs) → 552 accepted sentences (61 verbs) → **844 / 45 / 85** train/validation/test.
978/978 pass the app's acceptance rules; answer positions balanced (1,209 / 1,191 / 1,182 / 1,308).
Rejected: 32 "why" (repeat the verb), 1 "where", 18 unsuitable sentences. SHA-256 in GENERATION.md §9.

**Status:** ✅ Worked (not yet reviewed by a therapist).

**Issues & how we resolved them:** Shortened plurals in ConceptNet ("clothe") restored; teacher suitability flag useless, so a word filter was added; holding out 14 verbs left too little training data, so 5 were held out instead.

**Takeaways / next steps:** Therapist review of `out/review_sample.csv`. Check licences (ConceptNet CC BY-SA, Llama 3.1 output terms) before publishing.

### [2026-11-10] Entry 3: Research tracking set up
**Goal:** Record every notebook, step and decision from here on, like the `cdli` project.

**What we did:** Created this log (with a notebook register, section 5), the project skill
`.claude/skills/vnest-exercise-llm/SKILL.md` (rules for notebooks, scoring, and the logging duty) and the folder
`notebooks/marimo/1_training/`. Backfilled Entries 0–2 from `vnest_dataset/docs/GENERATION.md`.

**Status:** ✅ Worked.

**Takeaways / next steps:** Answer the open questions in section 9 that block the first notebook (HF / W&B names, LoRA vs full, training machine, MLC compile path for Qwen).

### [2026-11-10] Entry 4: Project put under git
**Goal:** A history of every change to the log, notebooks, dataset scripts and app, so any result can be traced to the exact code that produced it.

**What we did:** `git init` in `vnest/`, root `.gitignore`, one initial commit of the current state.
Left out (and why): Flutter build output (regenerable); `vnest_dataset/raw/` (155 MB downloads, re-fetchable, SHA-256 in
GENERATION.md §9); the 98 MB prebuilt MLC engine `libtvm4j_runtime_packed.so` (SHA-256 in §2); model weights (go to HF).
Kept: `vnest_dataset/out/` (1.9 MB): teacher step 2 isn't deterministic, so these files are the only exact copy of dataset v1.

**Status:** ✅ Worked.

**Takeaways / next steps:** Commit after each logged step; put the commit hash in each Experiment Log entry and notebook-register row from now on.

### [2026-11-10] Entry 5: Baseline b1, untuned Qwen2.5-1.5B-Instruct (NB 2.01)
**Goal:** Measure the untuned student model on the task with the project's one scorer, as the reference for fine-tuning.

**Notebook / script:** `notebooks/marimo/2_evaluation/01_baseline_qwen25_untuned.py` (NB 2.01), shared module `vnest_common` 1.0.0.
Run `b1-qwen25-1.5b-instruct-untuned`, W&B `team-me-and-me/vnest-exercise-llm/runs/b1-qwen25-1.5b-instruct-untuned`,
outputs in HF `emmilly/vnest-exercise-llm-outputs` (`preds/b1__2.01__…`, `tables/b1__2.01__summary.csv`, `tables/b1__2.01__per-verb.csv`).
Exported results: `notebooks/marimo/2_evaluation/baseline_qwen_untuned_results.ipynb`.

**What we did:** Validation (45) and test (85) × 2 prompts (long = the app's, short = `VNeST exercise for the verb "x".`) × 2 decodings
(schema = JSON-schema constrained like the app, via xgrammar; free) = 520 generations. Greedy, max 320 new tokens, bf16, batch 16.
Data checksums verified against `data/v1/SHA256SUMS` (train `f18824fe04`, validation `e982f94ae1`, test `119fcaa2a5`); verb overlap between splits = 0.
Environment: NVIDIA RTX PRO 6000 Blackwell Server Edition; Python 3.13.11, torch 2.11.0+cu130, transformers 5.14.1, xgrammar 0.2.9, pandas 3.0.3.

**Results** (automatic scores; test = 5 verbs):

| Split | Prompt | Decoding | Accepted % (95 % CI, verbs resampled) | Copies example % | Generic who % | Distinct outputs |
|---|---|---|---|---|---|---|
| test | long | schema | 100.0 (100.0–100.0) | 0 | 43.5 | 41 / 85 |
| test | long | free | 72.9 (38.8–95.0) | 0 | 43.5 | 41 / 85 |
| test | short | schema | 2.4 (0.0–5.4) | 0 | 0.0 | 35 / 85 |
| test | short | free | 0.0 | 0 | 0.0 | 37 / 85 |
| validation | long | schema | 97.8 (96.9–100.0) | 0 | 26.7 | 19 / 45 |
| validation | long | free | 91.1 (72.7–100.0) | 0 | 24.4 | 19 / 45 |
| validation | short | schema | 2.2 (0.0–10.3) | 0 | 6.7 | 20 / 45 |
| validation | short | free | 0.0 | 0 | 0.0 | 18 / 45 |

Cost: 0.037 GPU-hours in total for generation (≈ 2.2 min); peak GPU memory 3.72 GB; 476–657 tokens/s.
Bad-distractor rates are in the HF summary table (not copied here; the laptop download timed out).

**Status:** ✅ Worked (run complete, all 8 parts scored).

**Issues & how we resolved them:**
- The `404 … _done/generate.json` lines in the log are expected on a first run (no earlier stage marker to resume from).
- Summary tables were exported as images only; exact CSVs are on HF.
- **The exported `.ipynb` contained the real HF write token and W&B key** (pasted into the KEYS cell). Caught before any commit; replaced with
  placeholders, and a git pre-commit hook (`.git/hooks/pre-commit`) now blocks commits containing HF/W&B key patterns. If that export was
  shared anywhere else before 2026-11-10 ~16:30, rotate both keys.

**Observations (from reading outputs, not automatic scores):**
- **Long prompt: format is solved, content is not.** Accepted exercises often have *valid* wrong options, e.g. *drive*: what = a car / a bike / a plane / a boat;
  why = for work / for fun / for school / for shopping. "who" = "a person" in 44 % of test exercises. "why" answers like "because I want to eat".
- **Short prompt: the untuned model doesn't know the task** (writes sentence-repetition exercises or other JSON; with schema, only 2 "who" options).
- **Copying the worked example: 0 %**, which contradicts Entry 0 (phone, 4-bit, temperature 0.3). Likely the 4-bit model or sampling; to be checked on the phone (Entry 6).
- Greedy decoding gives near-identical exercises per verb (41 distinct of 85): the 85 test exercises are effectively ~5 verbs × a few "avoid people" variants. Small effective sample.
- The automatic distractor check covers only who/what and only objects in our dataset, so it **misses** cases like "a bike" for *drive*: a lower bound.

**Decisions made:** none new (setup decisions logged 2026-11-10 in §4).

**Takeaways / next steps:**
1. Acceptance is saturated with the long prompt, so it can't show that fine-tuning helps → need a content measure: human labels on ~50 b1 exercises + an LLM judge checked against them.
2. Baseline b2 (Llama-3.2-3B) with the same notebook (fork as NB 2.02).
3. Check the Qwen path on the phone (Entry 6).

### [2026-11-10] Entry 6: Untuned Qwen2.5-1.5B inside the app on the Galaxy Note10 (in progress)
**Goal:** Check that the app can run Qwen2.5-1.5B through its MLC engine before any fine-tuning, and measure it on the phone.

**What we did:**
- Found that the app's MLC engine (`libtvm4j_runtime_packed.so`, release Android-09262024) already packs five model libraries:
  `llama_q4f16_0_2d32…` (in use), `qwen2_q4f16_1_2e221f430380225c03990ad24c3d030e`, `gemma2_q4f16_1`, `phi3_q4f16_0`, `mistral_q4f16_1`.
  The release's `mlc-package-config.json` (mlc-llm commit `7561c96d`) maps the qwen2 library to `mlc-ai/Qwen2.5-1.5B-Instruct-q4f16_1-MLC`, so **no engine rebuild is needed**.
- Added a model picker to the app (commit `1fe9954`); starting verb list reduced to "cook" (commit `4531c2a`).
- Downloaded `mlc-ai/Qwen2.5-1.5B-Instruct-q4f16_1-MLC` at revision `9bd564b064631febf14deadcac492efb761d60c3` (840 MB, 30 weight shards, sizes match `ndarray-cache.json`; `tensor-cache.json` is an identical copy) to `models/mlc/` (not in git) and pushed it to the phone.
- Phone: Samsung Galaxy Note10 SM-N970U1, Android 12 (build N970U1UEU8HXE1), 7.6 GB RAM; on USB power, battery 40 %.

**Results, run 1 (MLC default engine settings: 32,768-token context, 2,048-token prefill chunks):** ❌
- App started 16:50:18, Qwen loaded; no exercise appeared for about 4 minutes ("taking so long").
- 16:52:55 and 16:54:16: system processes killed (`crash_dump helper failed to exec, or was killed`); 16:54:21: **`surfaceflinger` aborted, "SurfaceFlinger RESET by watchdog"**, then "The system died" and the phone restarted itself.
- The display server couldn't run for too long. Most likely cause: memory pressure and/or very long GPU jobs from the engine's defaults. **Not proven**: the log filter (app/TVM tags only) hid the low-memory killer and GPU driver messages.
- Llama-3.2-3B runs in the same app with even larger defaults (131,072 context, 8,192 chunks), so the defaults alone don't explain it.

**Run 1b (same build, user closed all other apps, ~17:00–17:06):** stuck again. Unfiltered log: Android's low-memory killer (`lmkd`) killing app after app,
"low watermark is breached and swap is low"; the app held **1.85 GB of GPU memory** (0.84 GB weights + ~1 GB KV cache for the 32,768-token default context);
1.85 GB RAM left; load average 16–18 with the app at 2.5 % CPU (waiting, not computing). Stopped with `am force-stop`.
→ Memory pressure confirmed for the default settings.

**Run 2 (commit `32a0fe1`, Qwen-only engine limits):** `max_num_sequence` 1, `max_total_sequence_length` 2048, `max_single_sequence_length` 2048,
`prefill_chunk_size` 256 (an exercise needs < 1,100 tokens); Llama keeps the MLC defaults, so its baseline is unchanged. Timing lines added (`VnestLlm` tag). ❌
- `load done … in 13406 ms` (17:08:07); GPU memory 1.16 GB; **RAM steady at ~2.2 GB free, no low-memory kills** → the memory fix worked.
- `generate start (prompt 1533 chars, max 320 tokens)` at 17:08:07, then **no first token** ever. The app process was gone by ~17:10:36; at 17:11 Android's
  `system_server` watchdog fired ("The system died") and the phone restarted again.
- **Conclusion so far:** memory caused run 1's pressure but is **not** the root cause. With this engine build, Qwen's first GPU work (prefill, or the JSON-schema
  grammar setup for Qwen's 151,936-token vocabulary) never finishes on the Note10 (Adreno 640), and blocks the system. Not yet known which.

Logs: `logs/phone/2026-11-10_run1_qwen_defaults_filtered.txt`, `…_run2_qwen_limits_memory.txt` (in git); full system logs `…_full.txt.gz` kept local only (personal device data).

**Status:** ❌ Qwen does not run in the app on the Note10 yet. Two phone restarts caused; stop blind retries.

**Run 3 (17:18, same build, started by the user):** same hang (load 10.6 s, no first token after 75 s); stopped with `am force-stop` before the system watchdog; no restart.
The user had uninstalled/reinstalled the app (deletes the weights in its folder); Qwen re-pushed, Llama re-downloaded (revision in `models/mlc/…/REVISION`).

**Run 4: self-test (commit `59ef9ab`):** model screen buttons send a one-line prompt, max 24 tokens, with and without the JSON schema; automatic exercise writing
off by default; a laptop-side guard force-stops the app if no first token arrives within 90 s. ✅ **Both answered → the GPU kernels work; Qwen is extremely slow, not hung.**

| Request | Prompt tokens | First token after | Prefill tok/s | Decode tok/s | Completion tokens | Total |
|---|---|---|---|---|---|---|
| "Say hello", no JSON rule | 26 | 20.7 s | **1.26** | 5.32 | 10 | 22.4 s |
| "Say hello", JSON rule | 30 | 26.5 s | **1.13** | **0.51** | 8 | 40.3 s |

Load: 9.8 s. Interpretation: (1) **prefill ~1 tok/s** is ~100× below normal for a phone GPU; the ~400-token exercise prompt alone needs ≥ 5 min, during which the GPU blocks
the system → watchdog. (2) The **JSON rule cuts decode 10×** for Qwen (probably the per-token grammar mask over the 151,936-token vocabulary on the phone CPU).
Main suspect for (1): the `q4f16_1` weight layout of this engine's Qwen library on Adreno 640 (Llama in this engine is `q4f16_0`, the layout MLC recommends for Adreno).
**Next:** same self-test on Llama-3.2-3B. Much faster prefill despite 2× the parameters → build Qwen as q4f16_0 with our own engine build. Equally slow → phone/engine limit.

**Run 5: same self-test on Llama-3.2-3B (q4f16_0, MLC defaults), 18:02:** ✅ (Llama weights re-downloaded at revision `3cb00cd6cd2f698612d800ba01ecfd1742ec1bfd`, 58 shards verified.)

| Model (layout) | Request | Prompt tokens | First token after | Prefill tok/s | Decode tok/s | Completion tokens | Total |
|---|---|---|---|---|---|---|---|
| Llama-3.2-3B (q4f16_0) | no JSON rule | 28 | 4.6 s | **6.12** | 1.89 | 3 | 5.6 s |
| Llama-3.2-3B (q4f16_0) | JSON rule | 32 | 2.8 s | **11.32** | 1.67 | 8 | 7.0 s |
| Qwen2.5-1.5B (q4f16_1) | no JSON rule | 26 | 20.7 s | 1.26 | **5.32** | 10 | 22.4 s |
| Qwen2.5-1.5B (q4f16_1) | JSON rule | 30 | 26.5 s | 1.13 | **0.51** | 8 | 40.3 s |

Load: Llama 14.4 s, Qwen 9.8 s. Tiny requests (3–10 output tokens), so rates are rough; the first Llama request may include warm-up.
**Findings:** (1) Llama prefills **5–10× faster than Qwen with 2× the parameters** → the slow part is Qwen's `q4f16_1` library on Adreno 640, not the phone.
(2) Without the JSON rule Qwen **decodes ~3× faster than Llama**, as expected for a smaller model. (3) The JSON rule costs Qwen ~10× in decode but Llama
almost nothing (1.9 → 1.7) → a second, Qwen-specific problem (grammar with Qwen's tokenizer in this engine version). Llama's ~11 tok/s prefill matches Entry 0 (≈ 40 s for the long prompt).

**Status:** ⚠️ Cause located; Qwen not yet usable in the app with this engine build.

---

## 8. What Failed / Dead Ends

| Date | What we tried | Why it failed | Lesson |
|---|---|---|---|
| ≤ 2026-11-10 | Untuned Qwen2.5-1.5B with the app's long prompt | Copies the worked example; "a person" as every "who"; accepts wrong answers | A small model needs task training, not a longer prompt |
| 2026-11-10 | where/when/why from ConceptNet/ATOMIC directly | Facts not tied to the specific sentence | Use a teacher model for the correct answers, code for the wrong ones |
| 2026-11-10 | Teacher's `suitable` flag (Llama-3.1-8B) | Marked every sentence suitable (guns, tanks, cigarettes) | Filter content in code |
| 2026-11-10 | Holding out all 14 app verbs for test | Left only 321 training sentences | Hold out 5 |
| 2026-11-10 | McRae / Ferretti thematic-fit norms | Download page 404 | Revisit later as a gold test source |
| 2026-11-10 | Untuned Qwen2.5-1.5B in the app on the Note10 with MLC default engine settings | No output for ~4 min, then the phone's display server was reset by its watchdog and the phone restarted (Entry 6) | Set engine limits per model; log the phone unfiltered during first runs of a new model |
| 2026-11-10 | `huggingface_hub` 2.2.0 downloads from this laptop (private outputs repo and public MLC repo) | Hung with no output; `curl` to the same repo works | Download with `curl` from `resolve/<revision>/` and pin the revision |

---

## 9. Open Questions

- **HF and W&B names** for this project (proposed, not decided: outputs dataset `emmilly/vnest-exercise-llm-outputs`, W&B `team-me-and-me/vnest-exercise-llm`). Private or public model repos?
- **LoRA or full fine-tune?** Full 1.5B training doesn't fit the 4 GB laptop GPU; which machine (RTX 6000 server, Colab) will train?
- **MLC LLM compile path for Qwen:** the app's packed runtime only contains the Llama-3.2-3B model library. A fine-tuned Qwen needs its own compiled library and a rebuilt runtime; check this works before training many variants.
- **How to score "answer correct"** without a therapist for every run: automatic checks + a fixed LLM judge + therapist review on a sample?
- Therapist review of `vnest_dataset/out/review_sample.csv`: who, and when?
- Licences: ConceptNet CC BY-SA share-alike for derived data; Llama 3.1 terms on training with its outputs.
- Kinyarwanda version: needs native-speaking therapists.

---

## 10. Paper Notes

### Possible structure
1. Introduction: VNeST for aphasia; offline, private, low-cost phones
2. Related work: VNeST (Edmonds), LLMs for therapy material, small on-device LLMs, distillation from a teacher
3. Data: building VNeST exercises from ConceptNet + a teacher model; what failed
4. Method: fine-tuning Qwen2.5-1.5B; short vs long prompt; quantisation for MLC LLM
5. Evaluation: unseen verbs; acceptance, correctness, distractor validity; on-device latency
6. Discussion: limits of synthetic data, therapist review, safety filtering
7. Conclusion

### Key observations to highlight
- Untuned small models copy the prompt's example; a smarter prompt doesn't fix it.
- The teacher model never flags unsuitable content; code-side filtering is required.

### References to cite
- Edmonds, L. A. (2016), VNeST overview / original studies
- Speer et al. (2017), ConceptNet 5.5
- Sap et al. (2019), ATOMIC
- Qwen2.5 technical report; Llama 3 / 3.1 / 3.2
- MLC LLM: https://github.com/mlc-ai/mlc-llm
