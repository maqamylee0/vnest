# VNeST On-Device Exercise Model: Progress Report

11 November 2026 · Source of record: `RESEARCH_LOG.md` (Entries 0–12)

A fine-tuned Llama-3.2-1B model now writes complete VNeST exercises fully offline on a Samsung Galaxy Note10. On held-out verbs,
100 % of exercises pass the app's checks, against 0 % before fine-tuning, at about 1 minute per exercise on the phone. What remains is
quality that rules cannot check: whether each scene makes sense, how varied the scenes are, and gender bias in who does the action.

## Goal

The VNeST Practice app gives adults with aphasia Verb Network Strengthening Treatment exercises: for a verb (cook), the patient picks
who does it (chef), what (dinner), where, when and why, each from 4 options. A small language model on the device writes the exercises;
the app's code checks the patient's taps, so feedback never depends on the model.

Constraints: fully offline, low-cost Android devices, therapist-safe content, every step reproducible for a paper.

## Work so far

| Date | Step | Outcome |
|---|---|---|
| 11 Nov | Phone export of f1 (NB 3.01) | 705 MB, runs on the Note10; two format problems (position settings, tokenizer) caught by checks and fixed |
| 11 Nov | First fine-tune, f1 (NB 1.01) | LoRA on Llama-3.2-1B, about 2 minutes of GPU time; 100 % of held-out exercises valid |
| 11 Nov | Baseline b2: untuned Llama-1B (NB 2.02/2.02b) | 25.5 % of questions, 0 % of exercises valid |
| 11 Nov | Stricter content checks (app and scorer) | Reject copied instructions, vague "who", "why" repeating the verb, "when" as a place |
| 11 Nov | Dataset v2 | 3,570 / 205 / 380 examples, one question per example; audit removed wrong options that were sometimes right and 2 offensive sentences found in v1 |
| 11 Nov | App: one question per request, live sessions | Patient can start on "who" while the rest is written; fixed-field JSON replies |
| 11 Nov | Student model chosen: Llama-3.2-1B | Fastest on the phone: 11 s to first token on a 400-token prompt (Llama-3B: 39 s) |
| 10–11 Nov | Own phone engine (MLC LLM 2024, built from source) | Showed Qwen's slowness was its weight layout (10× slower prompt reading); 4 models compared on the Note10 |
| 10 Nov | Baseline b1: untuned Qwen2.5-1.5B (NB 2.01) | Correct format only with the long prompt; poor content |
| 10 Nov | Dataset v1, project tracking | ConceptNet + Llama-3.1-8B teacher; research log, git, notebooks on Hugging Face and W&B |

## Results

Held-out test verbs (cook, drive, paint, plant, wash; 76 exercises, 380 questions). Automatic scores only; the model never saw these verbs in training.

| Measure | Untuned Llama-1B | Fine-tuned f1 |
|---|---|---|
| Exercises fully valid, written the app's way | 0 % | 100 % |
| Single questions passing the app's checks | 21 % | 100 % |
| Answers copying the instructions | 49 % | 0 % |
| Answer equal to the reference | 3 % | 36 % |

On the Galaxy Note10 (Snapdragon 855, 8 GB RAM), f1 at 4-bit:

| Measure | Value |
|---|---|
| Model size | 705 MB |
| Memory while running | about 0.75 GB |
| Load time | 6.2 s |
| Per question | 10.6–12.4 s |
| Whole exercise (5 questions) | about 55–60 s |

Exercises are written in the background ahead of time (one per verb), so patients do not wait during practice.

## What the results do not show yet

All scores above are rule checks. Reading the exercises on the phone shows three gaps:

- **Sense errors.** "The diner cooks the breakfast" and "The maid washes the hair" pass every rule but are wrong.
- **Little variety.** 10 different "who" answers across 76 test exercises; for one verb the model gives nearly the same scene each time,
  and it struggled to name anyone but "mother" for cook. Wrong options are memorised from short fixed lists.
- **Gender bias.** Every person in the phone tests was a woman in a domestic role (mother, maid). The data is not mostly female overall
  (11 % female-coded people), but the household verbs in training are (iron: maid and mother; clean: maid; feed: mother), and the model
  generalised from them.

These trace mainly to the training data, which is small and comes from ConceptNet plus an 8B teacher. Some sense errors also reflect the
limited world knowledge of a 1B model, so a human review stays necessary.

## The proposed path: larger teacher model and constrained decoding

| Proposal | Assessment |
|---|---|
| Larger teacher (Llama 3.3 70B or GPT-4o) | Agree: the teacher is the main source of the gaps above. Llama 3.3 70B is the better fit: its licence allows training other models on its outputs with attribution (check before use), it can run on our own GPU server, and our student is a Llama model. GPT-4o's terms restrict using outputs to build competing models (check before use). |
| 2,000–5,000 examples | v2 already has 3,570 examples, but from only 357 sentences over 50 verbs. The need is more distinct scenes: many more verbs, several people per verb, gender-balanced roles. |
| Review by a speech-language pathologist | Agree: the missing piece. Needed both for the data and for judging the model's exercises. |
| Dialogue turns, patient error patterns, cueing hierarchies; model output `{"feedback", "hint", "step_passed"}` | This changes scope. Today the app checks answers in code: deterministic, instant, and safe. A model judging patient responses adds about 10 s per tap on the phone and clinical risk. Suggest a later phase where hints are written ahead of time with each exercise, not judged live. |
| Constrained decoding (llama.cpp JSON schema, Outlines) | Already in place: the phone engine enforces a JSON schema on every reply. It roughly halves writing speed on the phone, and f1 was 100 % valid without it on the GPU, so the next test is turning it off. |

## Next steps

1. Therapist review of 100 phone exercises across 20 verbs, including verbs never seen in training.
2. Add variety, bias and sense measures to the scorer.
3. Build dataset v3 with a larger teacher: many more verbs, several people per verb, gender-balanced household roles, longer wrong-option lists, no idiom pairings.
4. Train f2 with the same recipe; compare with f1 on the same held-out verbs.
5. Speed test with the JSON schema off (expected about 35 s per exercise instead of about 60 s).
6. Test on the target tablet: install, run the self-tests, write exercises.
7. Write up for the paper; every step above is in `RESEARCH_LOG.md`.

## When this deliverable is met

Proposed criteria, for the team to agree. "Now" is measured where stated, otherwise not yet done.

| Criterion | Proposed target | Now |
|---|---|---|
| Runs fully offline on the target device | Yes, on the chosen tablet | Yes on the Note10; tablet not tested |
| Valid exercises on held-out and new verbs, on the device | ≥ 95 % within the app's 3 tries | 100 % on GPU; small phone sample all valid |
| Rated acceptable by a speech-language pathologist | ≥ 90 % of ≥ 100 exercises, ≥ 20 verbs | Not done |
| Unsafe or offensive content | 0 in the reviewed sample | None seen; not formally reviewed |
| Variety | ≥ 3 different people per verb over 3 requests | About 1–2 |
| Gender balance of "who" on household verbs | 35–65 % female-coded | About 100 % in phone tests |
| First question ready | ≤ 15 s on the target device | 12 s on the Note10 |
| Whole exercise | ≤ 60 s on the target device | 55–60 s on the Note10 |
| Size | Model ≤ 1 GB, memory ≤ 1 GB | 705 MB, about 0.75 GB |
| Reproducible | Every result traceable to data, code and log | Yes |

## Decisions needed

- Target tablet model(s), so specs and tests can be fixed.
- Teacher model for dataset v3, and confirmation that its licence allows training on its outputs.
- Whether live feedback and hints are in scope, or a later phase.
- Who reviews the exercises, and when.
- One exercise per verb (current) or three.
