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

---

## 5. Notebook Register

Every training / evaluation / export notebook, one row each. Add the row **before** the first run; update the
status after every run. Notebooks that produced results are never edited: fork them into a new number.

| NB | File | Purpose | Forked from | Status | Runs (W&B id / HF repo) | Log entry |
|---|---|---|---|---|---|---|
| | | | | | | |

Status values: `draft` → `ready (offline checks pass)` → `running` → `done` / `failed` / `superseded by NB x`.

---

## 6. Results Summary

### 6.1 Test verbs (cook, drive, paint, plant, wash), 85 exercises

| Model | Prompt | App acceptance % | Copies example % | Answer correct % (review) | Bad distractors % | Notes / NB |
|---|---|---|---|---|---|---|
| Qwen2.5-1.5B (untuned) | long | | | | | |
| Llama-3.2-3B (untuned) | long | | | | | |

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

---

## 8. What Failed / Dead Ends

| Date | What we tried | Why it failed | Lesson |
|---|---|---|---|
| ≤ 2026-11-10 | Untuned Qwen2.5-1.5B with the app's long prompt | Copies the worked example; "a person" as every "who"; accepts wrong answers | A small model needs task training, not a longer prompt |
| 2026-11-10 | where/when/why from ConceptNet/ATOMIC directly | Facts not tied to the specific sentence | Use a teacher model for the correct answers, code for the wrong ones |
| 2026-11-10 | Teacher's `suitable` flag (Llama-3.1-8B) | Marked every sentence suitable (guns, tanks, cigarettes) | Filter content in code |
| 2026-11-10 | Holding out all 14 app verbs for test | Left only 321 training sentences | Hold out 5 |
| 2026-11-10 | McRae / Ferretti thematic-fit norms | Download page 404 | Revisit later as a gold test source |

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
