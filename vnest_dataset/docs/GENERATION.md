# How the VNeST exercise dataset was generated

This document records how `out/train.jsonl`, `out/validation.jsonl` and `out/test.jsonl` were produced: the
sources, every processing step, the decisions behind them, what went wrong along the way, and how to reproduce
or extend the build. The dataset card (`../README.md`) gives the short version.

- **Built:** 10 November 2026, on a Linux laptop (Python 3.12.3, NVIDIA RTX 2050 4 GB)
- **Purpose:** fine-tune Qwen2.5-1.5B-Instruct to write VNeST exercises for the VNeST Practice app, offline on a phone
- **Status:** first version, not yet reviewed by a speech-language therapist

---

## 1. Why this dataset exists

The VNeST Practice app asks an on-device model to act as the therapist. For a verb, it writes five
multiple-choice questions (who, what, where, when, why), each with 4 options and one marked answer. The app's
code then checks the patient's taps against that answer.

Before fine-tuning, we tested the two phone-sized models with the app's prompt on 14 verbs:

| Model | What went wrong |
|---|---|
| Qwen2.5-1.5B | Copied the prompt's example ("wood / in the workshop / before cutting / to build a table") for most verbs. "Who" was almost always "a person". "What does a person wash? → a song" was marked correct. |
| Llama-3.2-3B | Mostly sensible, but some "wrong" options were valid ("painter" for *paint*) and some answers were nonsense ("drive → when i was born"). It also takes about 2 minutes per exercise on a Galaxy Note 10, against about 1 minute for Qwen. |

The goal is to teach the faster model (Qwen) the task: real people as "who", answers that fit the sentence,
clearly wrong distractors, exactly 4 options, and no copying of the example.

**No ready-made dataset exists for this.** We searched for VNeST or aphasia exercise datasets and found none
public. The dataset is therefore assembled from general commonsense resources plus a larger model.

---

## 2. Output format

Each line is one chat example:

```json
{"messages": [
   {"role": "system",    "content": "You are a speech-language therapist. ..."},
   {"role": "user",      "content": "VNeST exercise for the verb \"water\"."},
   {"role": "assistant", "content": "{\"who\": {\"options\": [\"mirror\", \"sandwich\", \"gardener\", \"bowl\"], \"answer\": \"gardener\"}, ...}"}
 ],
 "meta": {"verb": "water", "agent": "gardener", "patient": "herb garden", "prompt": "short", "teacher": "llama3.1:8b"}}
```

- The **assistant message** is exactly the JSON the app parses (`vnest_app/lib/data/scenario.dart`, `Scenario.fromModel`).
- The **user message** is one of two styles (50/50):
  - **long**: the app's current prompt, word for word (`LlmService.userPrompt`), including the worked "measure" example
  - **short**: `VNeST exercise for the verb "<verb>".` A fine-tuned model shouldn't need the instructions, and a
    short prompt is much faster for the phone to read (prompt reading was about 40 of the 124 seconds per exercise).
- About 30% of prompts include "not these people: …", which the app sends on repeat requests so each verb gets
  different people. The answer then avoids those people.
- `meta` is for analysis only and can be dropped before training.

---

## 3. Sources

| Source | Version / location | SHA-256 | Licence | Used for |
|---|---|---|---|---|
| ConceptNet, high-confidence subset | Hugging Face `relbert/conceptnet`, file `dataset/train.jsonl` (583,082 facts), downloaded 10 Nov 2026 | `ba5de412…04eba` | ConceptNet 5 is CC BY-SA 4.0 (the HF card says "other"; check) | who/what pairs; list of valid objects and doers per verb |
| ATOMIC 2019 | `https://homes.cs.washington.edu/~msap/atomic/data/atomic_data.tgz` | `f2277994…2ba9` | CC BY 4.0 (`raw/atomic/LICENSE`) | Downloaded, **not used** in the current build (see 6.1) |
| English word list | `/usr/share/dict/american-english` (Ubuntu `wamerican`, 104,334 lines) | | Public domain | Dropping misspelled objects |
| Teacher model | Ollama `llama3.1:8b` (digest `46e0c10c039e`, Q4_K_M), Ollama 0.40.2 | | Llama 3.1 Community Licence | Correct where/when/why; suitability flag |

Full checksums of the sources and outputs are in section 9.

**Considered but not used:**
- McRae et al. (1998) and Ferretti et al. (2001) thematic-fit norms: human ratings of typical doers, objects
  and places for verbs. They're the best fit for VNeST in principle, but the McRae lab download page returned
  404 at build time.
- DTFit (Vassallo et al. 2018): no data file found.
- Edmonds' VNeST dissertation stimuli: worth extracting later as a **gold test set**, not for training.
- Kinyarwanda corpora (`mbazaNLP/kinyarwanda_monolingual_v01.1`, Digital Umuganda Common Voice text): general
  text only, no exercise or question-answering data.

---

## 4. Pipeline

```
raw/conceptnet/train.jsonl ──► 1. extract_pairs.py ──► out/pairs.jsonl     (who/what)
                                                            │
                                  2. teacher_wh.py ◄────────┘
                                  (Llama-3.1-8B)  ──► out/wh.jsonl         (where/when/why + checks)
                                                            │
raw/conceptnet/train.jsonl ──► 3. assemble.py ◄─────────────┘
                                                  ──► out/train.jsonl, validation.jsonl, test.jsonl,
                                                      review_sample.csv, stats.json
```

Shared word lists and English helpers are in `scripts/common.py`. All scripts use only the Python standard
library and are run with `python3 -I` (isolated mode).

### Step 1: who/what pairs (`extract_pairs.py`)

Takes ConceptNet `CapableOf` facts whose doer is a person and whose action is "verb + object",
e.g. `a gardener → plant roses` becomes `(plant, gardener, roses)`.

| Rule | Why |
|---|---|
| Verb must be in a hand list of ~120 concrete, picturable transitive verbs (`common.VERBS`) | VNeST trains everyday action verbs. This drops "doubt a teacher", "guess an answer", "anger a parent". |
| Violent verbs (hit, shoot) left off that list | Therapy content |
| Doer must be in a hand list of ~200 person words (`common.PEOPLE`); plurals mapped to singular ("pilots" → pilot) | ConceptNet's own "X is a person" facts were too noisy: in a first attempt they let in "music" and "family" as doers. Generic words (person, someone, you, we) are excluded because "a person" as every answer was one of the habits we want to remove. |
| Object: leading articles and possessives removed ("your teeth" → teeth); at most 2 words; every word must be in the English word list | Drops typos ("thier child") and fragments ("from st") |
| Object can't start with a preposition | "hang from a tree" isn't a direct object |
| Object can't be a person, except with caring verbs (feed, teach, wash, examine …) | Keeps "the nurse feeds the baby", drops odd combinations |
| Object can't be a vague word (thing, stuff, it, them, persons …) | |
| **Shortened plurals restored**: clothe → clothes, trouser → trousers, thieve → thieves, glasse → glasses, pant → pants, jean → jeans, scissor → scissors; slack/short → slacks/shorts for garment verbs | ConceptNet's older entries contain crudely shortened plurals ("wash clothe"; 1,877 lines contain "clothe"). The word-list check didn't catch them because "clothe" is a real word. |

Result: **711 pairs over 64 verbs**.

### Step 2: where / when / why (`teacher_wh.py`)

For each pair, Llama-3.1-8B is given the exact sentence ("The baker bakes the cake.") and asked for:

- `suitable`: true only for a normal, everyday, pleasant action
- `where`: usual place, 2–4 words, starting with in/at/on
- `when`: usual time or moment, 2–4 words
- `why`: usual reason, 2–5 words, starting with "to"

Output is forced to that shape with a JSON schema; temperature 0.2. The prompt is in the script.

**Why a model here and not the knowledge bases:** the first attempt took these answers from ConceptNet/ATOMIC
and they didn't fit the sentences (section 6.1). Writing three correct answers for a known sentence is the
easiest part of the task; Llama-3.2-3B already got 10/10 on it earlier, so an 8B model is a reasonable teacher.
The teacher **never writes wrong options**: in earlier tests, model-written distractors were often actually correct.

The teacher's answers are then checked in code. Rejected if:

| Check | Rejected |
|---|---|
| Answer repeats the verb ("to serve the customers" for *serve*) | 32 |
| "where" doesn't start with a place word (in, at, on, by, near, outside, inside, under) | 1 |
| Wrong length, unexpected characters, "why" not starting with "to" | 0 |
| Teacher marked `suitable: false` | **0** (see 6.3) |

About 4.3 seconds per pair on the laptop; about 1 hour in total. The script is resumable: finished pairs are
appended to `out/wh.jsonl` and skipped on the next run.

### Step 3: assembly (`assemble.py`)

1. **Keep** teacher rows that passed the checks and whose pair still exists in the current `pairs.jsonl`.
2. **Content filter**: drop sentences containing unsuitable words (`common.UNSUITABLE`: weapons, war, soldier,
   graves, alcohol, tobacco, drugs, pranks, thieves …), with exceptions for harmless phrases ("blood pressure",
   "fish tank"). Dropped **18**, for example "the cowboy rolls the cigarette", "the soldier drives the tank",
   "the judge hangs the horse thieves".
3. **Dedupe** singular/plural duplicates of the same pair ("shoe"/"shoes").
4. **Cap** at 30 sentences per verb, so common verbs (play, wear) don't dominate.
5. **Add wrong options in code.** For each question, 3 options are sampled from fixed lists of clearly impossible answers:

   | Question | Wrong-option list (examples) | Also excluded |
   |---|---|---|
   | who | stone, pillow, teapot, banana, curtain … (40 objects that can't act; tools like knife or key are left out because they "do" verbs) | anything ConceptNet says can do that verb |
   | what | anger, tuesday, an echo, honesty, the alphabet … (30 things nobody can act on) | anything ConceptNet uses as an object of that verb |
   | where | on the moon, inside a teapot, on a rainbow … (14) | lists sharing a word with the answer |
   | when | while sleeping, in the year 3000, before dinosaurs lived … (12) | same |
   | why | to grow wings, to turn into a fish, to stop the sun … (12) | same |

6. **Shuffle option order**, so the answer isn't always first. Before fine-tuning, the models tended to put it first.
7. **Two variants per training sentence**, differing in wrong options and prompt style (long/short).
   Validation and test have one each.
8. **Split by verb** (section 5).
9. Write `review_sample.csv`: 100 random training exercises in one-row-per-exercise form, with an "ok? (y/n)"
   column for a therapist.

All randomness uses a fixed seed (20261110), so step 3 gives identical files for the same inputs.

---

## 5. Splits

Splitting is **by verb**: a verb's sentences are all in the same split. The test therefore measures what
happens when a therapist adds a verb the model has never seen.

| Split | Verbs | Examples |
|---|---|---|
| train | 51 verbs (see `out/stats.json`) | 844 (422 sentences × 2) |
| validation | chop, eat, lift, play, smell | 45 |
| test | cook, drive, paint, plant, wash | 85 |

The test verbs are five of the app's verbs, the ones used in the on-phone model comparison, so fine-tuned
results can be compared directly with the earlier ones. The app's other verbs (write, read, fix, cut, feed, open,
drink…) are in training. An earlier split held out all 14 app verbs, which put 221 examples in test and left only
321 training sentences; the most common verbs were too valuable to hold out.

---

## 6. What went wrong and how it was fixed

### 6.1 First attempt: answers taken directly from the knowledge bases (discarded)

The first build took every part from ConceptNet and ATOMIC: "where" from the places a person appears in
(`AtLocation`), "when" from prerequisites (`HasPrerequisite`, ATOMIC `xNeed` turned into "after …") and "why"
from goals (`MotivatedByGoal`, ATOMIC `xIntent`). It produced 369 training examples, but the answers didn't fit
their sentences:

| Sentence | Where | When | Why |
|---|---|---|---|
| The boy carries the groceries. | in the football game | after working hard | to travel |
| The music lifts the one spirit. | in the night club | after holding something | to praise jesus |
| The parent hits their child. | in the family | after driving to a city | to get home |
| The slave hangs from st. | in the south | after being scolded | to thing that is bad |

Causes: a person appears in many places, so the place chosen often had nothing to do with the action; facts
about the verb in general were used when nothing matched the object; and the doer filter was too loose. Training
on this would have taught nonsense, so the approach was replaced with the teacher model (step 2). The who/what
extraction from that attempt was kept and made stricter.

### 6.2 Shortened plurals in ConceptNet

"The housekeeper irons the **clothe**", "the man irons the **slack**". Traced to ConceptNet itself, which
contains older crudely-shortened entries. Fixed by restoring known plurals in step 1 (see the table there).

### 6.3 The teacher's suitability flag doesn't work

Llama-3.1-8B marked **every** sentence as suitable, including "the hunter cleans the gun" and "the soldier drives
the tank". The flag is still requested but shouldn't be relied on; the content word filter in step 3 does the
actual work. A stronger teacher may do better.

### 6.4 Too little training data with all app verbs held out

Fixed by holding out 5 instead of 14 (section 5).

---

## 7. Quality checks done

| Check | Result |
|---|---|
| Every assistant JSON passes the app's acceptance rules (4 different options, answer among them, ≤ 6 words, who ≠ what) | 978 / 978 pass |
| Correct answer position spread across the 4 slots | 1,209 / 1,191 / 1,182 / 1,308 |
| Prompt styles | 50/50 long and short in every split |
| Manual reading of random samples | Mostly good ("the dentist pulls the teeth / in the office / every six months / to keep healthy"); some weak ("the singer measures the breath", "the grandma serves the turnips *in the garden*") |
| **Therapist review** | **Not done yet.** Fill in `out/review_sample.csv` (100 exercises). |

---

## 8. Known limitations

- **Small:** 422 unique training sentences. Enough to teach the format and style, not much new world knowledge.
- **Where/when/why are from an 8B model, not people.** Expect some weak answers until the review is done.
- **Wrong options are deliberately easy and repeat** across exercises; a fine-tuned model will reuse them.
  They're always wrong, but they don't train fine distinctions.
- **The "also valid" checks rely on ConceptNet's coverage.** A valid object ConceptNet doesn't know about
  could in principle be offered as wrong, though the wrong-option lists are chosen to make that unlikely.
- **English only.**
- **Licences:** ConceptNet's CC BY-SA may require sharing derived datasets under the same licence. Llama 3.1's
  licence has terms on using its outputs to train other models (to our understanding it allows this, with
  attribution and naming requirements). Check both before publishing the dataset or a model trained on it.

---

## 9. Reproducing the build

```bash
cd ~/Documents/research/vnest/vnest_dataset

# sources
mkdir -p raw/conceptnet raw/atomic
curl -sfL -o raw/conceptnet/train.jsonl https://huggingface.co/datasets/relbert/conceptnet/resolve/main/dataset/train.jsonl
curl -sfL -o raw/atomic/atomic_data.tgz https://homes.cs.washington.edu/~msap/atomic/data/atomic_data.tgz
tar -xzf raw/atomic/atomic_data.tgz -C raw/atomic

# teacher model (Ollama must be running)
curl -s -X POST localhost:11434/api/pull -d '{"model":"llama3.1:8b","stream":false}'

# build
python3 -I scripts/extract_pairs.py raw out
python3 -I scripts/teacher_wh.py out llama3.1:8b     # ~1 hour; resumable
python3 -I scripts/assemble.py raw out
```

**Determinism:** steps 1 and 3 are deterministic. Step 2 is **not**: the teacher was run at temperature 0.2
without a fixed seed, so regenerating `wh.jsonl` gives slightly different answers. To reproduce this exact
dataset, keep `out/wh.jsonl` and re-run only steps 1 and 3.

SHA-256 of this build:

```
ba5de4122d7c3729e8a5d00256e3b6360244763f46180245cdfe4cd1c9d04eba  raw/conceptnet/train.jsonl
f22779944e6613044d530875dd9592a333be2e3cb83d25493b36bba7c59b2ba9  raw/atomic/atomic_data.tgz
196cf7ec223df6292112acd7810245a6499169548c4305238ac273a0bfde6252  out/pairs.jsonl
4b43950ac05a66b7f9798374b3a1855b6dee7001361eec9afc8a6f0296b1924a  out/wh.jsonl
f18824fe04afb471a81e46be1417ea3535f091aa1ce8d114cfa5e4280e80344b  out/train.jsonl
e982f94ae1115f5634d1a3bc84bc977deefdd5507588c2a0669c8729c3ec7e10  out/validation.jsonl
119fcaa2a59d19b47120c56b9543a118818290395c9074762b3ed02881bebec1  out/test.jsonl
```

`out/wh.jsonl` also holds 9 rows from before the plural fix (e.g. "clothe"). They're ignored by step 3 because
their pairs no longer exist in `pairs.jsonl`.

---

## 10. Extending the dataset

| To… | Do this |
|---|---|
| Add verbs | Add them to `common.VERBS`, re-run all three steps (step 2 only processes new pairs) |
| Add doers | Add words to `common.PEOPLE` |
| Use a better teacher (e.g. a hosted API model) | Replace the `ask()` function in `teacher_wh.py`, move the old `wh.jsonl` aside, re-run steps 2–3 |
| Change wrong-option lists | Edit the lists at the top of `assemble.py`, re-run step 3 |
| Block more content | Add words to `common.UNSUITABLE`, re-run step 3 |
| Add Kinyarwanda | Needs exercises written or translated by native-speaking therapists; the format stays the same, with a language field to add |
| Change the held-out verbs | Edit `common.TEST_VERBS`, re-run step 3 |

---

## 11. Change log

| Date | Change |
|---|---|
| 10 Nov 2026 | First attempt using ConceptNet/ATOMIC for every part; discarded (6.1) |
| 10 Nov 2026 | Rebuilt: ConceptNet who/what + Llama-3.1-8B where/when/why + code distractors |
| 10 Nov 2026 | Content filter added after the teacher approved weapons/alcohol sentences (6.3) |
| 10 Nov 2026 | Held-out verbs reduced from 14 to 5 (6.4) |
| 10 Nov 2026 | Shortened plurals restored (6.2). Current build: 844 / 45 / 85 |
