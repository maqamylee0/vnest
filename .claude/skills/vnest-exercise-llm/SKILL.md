---
name: vnest-exercise-llm
description: Project rules for the VNeST exercise LLM project (fine-tuning a small on-device model, Qwen2.5-1.5B-Instruct, to write VNeST aphasia exercises for the VNeST Practice Flutter app via MLC LLM). Use together with marimo-ml-notebook whenever creating, forking, fixing, running or analysing a training, evaluation, quantisation/export or analysis notebook in this repository, when changing the dataset in vnest_dataset/, and when reporting or comparing model results. Holds the project constants, data and split rules, the one scoring definition, and the research-log and notebook-register duty. Wins over marimo-ml-notebook where they differ.
---

# VNeST exercise LLM: project rules

Generic notebook rules: **marimo-ml-notebook** (load it too). This file sets the project constants and the
places where this project differs. On a conflict, this file wins.

## 1. Constants

| Constant | Value |
|---|---|
| Student model | `Qwen/Qwen2.5-1.5B-Instruct` |
| Current app model (baseline) | `Llama-3.2-3B-Instruct-q4f16_0-MLC` (`vnest_app/lib/services/llm_service.dart`) |
| `HF_USER` | `emmilly` |
| Outputs dataset | `emmilly/vnest-exercise-llm-outputs` (private; decided 2026-11-10). Dataset v1 lives in it under `data/v1/` (+ `SHA256SUMS`) |
| Model repos private? | **TO DECIDE** (check ConceptNet CC BY-SA and Llama 3.1 output terms first) |
| W&B | `team-me-and-me/vnest-exercise-llm` (decided 2026-11-10) |
| `DATA_VERSION` | `v1` = the 2026-11-10 build (SHA-256 in `vnest_dataset/docs/GENERATION.md` §9) |
| Notebooks | `notebooks/marimo/<N_section>/NN_name.py` (`1_training`, `2_evaluation`, `3_export` …), numbered from 01; `NOTEBOOK` id = `<section>.<NN>` (e.g. `2.01`) |
| Shared module | `common/vnest_common.py` (one scorer, naming, HF I/O, stages); embed with `tools/make_standalone.py`; offline checks `common/test_vnest_common.py` |
| Run names | `<exp>-<model>-<variant>`, e.g. `b1-qwen25-1.5b-instruct-untuned` (`wc.run_name`) |

Until a TO DECIDE value is chosen by the user, ask; do not invent it in a notebook.

## 2. Data and splits (non-negotiable)

- Data: `vnest_dataset/out/{train,validation,test}.jsonl`. Each line is `{"messages": [...], "meta": {...}}`; drop `meta` before training.
- Splits are **by verb**. Test verbs (cook, drive, paint, plant, wash) and validation verbs (chop, eat, lift, play, smell) must never appear in training. Every notebook asserts this from `meta.verb` and prints the overlap (must be 0).
- **Never select checkpoints, prompts or hyperparameters on test.** Use validation.
- Record the SHA-256 of the data files used in every run. If the dataset is rebuilt, bump `DATA_VERSION`, add a log entry and re-run baselines.

## 3. Scoring: one definition for every model

One shared scoring function, used by every notebook and for both baselines and fine-tuned models:

- **Acceptance**: the output parses as JSON and passes the same checks as `Scenario.fromModel` in `vnest_app/lib/data/scenario.dart` (5 questions, 4 different options, answer among them, ≤ 6 words, who ≠ what). Port these checks exactly; if the app's checks change, change the scorer and log it.
- **Copying**: output reuses the long prompt's worked example (wood / in the workshop / before cutting / to build a table).
- **Generic who**: "who" answer is a generic word (person, someone, people).
- **Answer correctness / distractor validity**: automatic checks first; a judge model or therapist review on a fixed sample. State which one produced each number.
- Report per prompt style (long / short) and per test verb, not only overall. Five test verbs: say so next to every number.
- On-device numbers (Galaxy Note 10): load time, seconds per exercise, tokens/s, model size. Phone timings only from the phone, never from a desktop.

## 4. Research log and notebook register duty

- `RESEARCH_LOG.md` at the project root is the journal for the paper.
- **Before** a notebook is first run, add it to the Notebook Register (§5 of the log). After every run, update its status and add the W&B run id and HF repo.
- Every run, result, failure and decision gets a dated Experiment Log entry (template in the log). Decisions also go in the Decisions Log table; failures also go in the What Failed table; numbers go in the Results Summary.
- Failures are as important as successes. Never fabricate or round away a bad result.
- Notebooks that produced results are never edited: fork into the next number and note "Forked from".
