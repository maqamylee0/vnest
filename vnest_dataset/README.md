# VNeST exercise dataset (draft)

> Full record of how this was built (sources, decisions, problems found, reproduction): [docs/GENERATION.md](docs/GENERATION.md)

Training data for teaching a small model (Qwen2.5-1.5B-Instruct) to write **VNeST exercises** in the exact
JSON format used by the VNeST Practice app (`vnest_app/lib/data/scenario.dart`):

```json
{"who":   {"options": ["stone", "baker", "pillow", "cup"],                 "answer": "baker"},
 "what":  {"options": ["cake", "anger", "tuesday", "an echo"],             "answer": "cake"},
 "where": {"options": ["in the bakery", "on the moon", "inside a teapot", "on a star"], "answer": "in the bakery"},
 "when":  {"options": ["while sleeping", "in the morning", "in the year 3000", "during a dream"], "answer": "in the morning"},
 "why":   {"options": ["to grow wings", "to sell it", "to stop the sun", "to become a tree"], "answer": "to sell it"}}
```

Each line of `out/{train,validation,test}.jsonl` is a chat example:
`{"messages": [system, user, assistant], "meta": {...}}`. The assistant message is the JSON above as a string.
`meta` is for analysis only; drop it before training if your trainer complains about extra columns.

> **Use dataset v2 (`out_v2/`) for training.** v2 (11 Nov 2026) has one question per example in the app's per-part format,
> cleaned wrong options and fixes found by an audit, including **two offensive sentences in v1** (one in v1's training split).
> Details: [docs/GENERATION.md §12](docs/GENERATION.md). The rest of this README describes v1 (`out/`).

## Current build (10 Nov 2026)

| | |
|---|---|
| who/what pairs from ConceptNet | 711 (64 verbs) |
| accepted after teacher checks + content filter | 552 unique sentences (61 verbs) |
| **train** | **844 examples** (422 sentences × 2 variants, 51 verbs) |
| validation | 45 (chop, eat, lift, play, smell) |
| test | 85 (cook, drive, paint, plant, wash: never seen in training) |
| prompt styles | 50% the app's long prompt, 50% a short prompt |
| teacher | Llama-3.1-8B (Ollama, temperature 0.2) |

Rejected by checks: 32 "why" answers (mostly repeating the verb), 1 "where", 18 unsuitable sentences
(weapons, war, alcohol, tobacco, graves, pranks, thieves). All 978 examples pass the app's own acceptance checks,
and the correct answer is spread evenly over the 4 option positions.

## How it's built

| Step | Script | What it does |
|---|---|---|
| 1 | `scripts/extract_pairs.py` | **Who / what** from ConceptNet `CapableOf` facts with a person as the doer ("a gardener → plant roses"). Limited to a list of concrete, picturable verbs (`scripts/common.py`), a list of person words, and objects found in an English dictionary (drops typos). Violent verbs are excluded. |
| 2 | `scripts/teacher_wh.py` | A larger local model (Llama-3.1-8B via Ollama) writes the **correct** where / when / why for each sentence and marks sentences that are odd, idiomatic, violent or sad as unsuitable. Answers that repeat the verb, are too long, or have the wrong shape are rejected. Resumable. |
| 3 | `scripts/assemble.py` | Adds **wrong options in code** from fixed lists of clearly impossible answers (stone / anger / on the moon / while sleeping / to grow wings), skipping any that ConceptNet lists as valid for the verb. Shuffles option order. Writes 2 variants per training pair, half with the app's long prompt and half with a short prompt (`VNeST exercise for the verb "bake".`), so a fine-tuned model can skip the long prompt and run faster on a phone. |

Rebuild everything:

```bash
python3 -I scripts/extract_pairs.py raw out
python3 -I scripts/teacher_wh.py out llama3.1:8b      # ~5 s per pair on a laptop GPU; resumable
python3 -I scripts/assemble.py raw out
```

`raw/` holds the downloaded sources (ConceptNet subset from Hugging Face `relbert/conceptnet`, ATOMIC 2019 from
the University of Washington). ATOMIC isn't used by the current pipeline; it's kept for a possible "when/why" source.

## Splits

Split **by verb**, so test results show how the model does on verbs it has never seen (as when a therapist adds a new verb):

- **test**: the app's verbs (cook, drink, drive, write, read, plant, fix, play, wash, paint, cut, feed, open, sweep)
- **validation**: a few other verbs (see `out/stats.json`)
- **train**: everything else

## Known limitations (read before training)

- **Small**: hundreds of unique sentences, not thousands. Good enough to teach the format and style
  (not copying the example, 4 options, real people as "who"), not enough to teach much new world knowledge.
- **Where / when / why come from an 8B model**, not from people. Most are good; some are weak
  ("the grandma serves turnips *in the garden*"). Have a therapist go through `out/review_sample.csv`
  (100 random exercises, ok y/n) and use the error rate to decide whether to filter more.
- **Wrong options are easy on purpose** (stone, anger, on the moon). They are always wrong, but they don't train
  fine distinctions. They also repeat across exercises, so a fine-tuned model will reuse them.
- **English only.** No Kinyarwanda source data was found; Kinyarwanda exercises need native-speaking therapists.
- **People words are mostly from a hand list**; ConceptNet's own person facts were too noisy to use.

## Licences

- **ConceptNet**: ConceptNet 5 is released under CC BY-SA 4.0 (the `relbert/conceptnet` card says "other";
  check before publishing). Share-alike may apply to datasets derived from it.
- **ATOMIC 2019**: CC BY 4.0 (see `raw/atomic/LICENSE`).
- **Teacher outputs**: generated with Llama-3.1-8B; Meta's Llama 3.1 licence has terms on using outputs to train
  other models. Check it, or regenerate step 2 with a model whose terms suit you.
