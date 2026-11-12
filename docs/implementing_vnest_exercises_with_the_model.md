# Building VNeST exercises with the on-device model

A guide for developers who want to use the public model
[`emmilly/Llama-3.2-1B-Instruct-VNeST-f1-q4f16_0-MLC`](https://huggingface.co/emmilly/Llama-3.2-1B-Instruct-VNeST-f1-q4f16_0-MLC)
to write VNeST exercises inside an Android app, fully offline.

Everything here comes from the VNeST Practice app, where this model runs on a Samsung Galaxy Note10. The prompts, checks and
settings below are the ones that app uses. Change them and you are testing a different system: the model was trained on these
exact prompts.

> **Research use only.** The model has not been reviewed by a speech-language pathologist, and it makes sense errors and shows
> gender bias (see [Known problems](#9-known-problems-and-what-to-do-about-them)). Do not put its output in front of patients
> without the checks in section 5 and a human review plan.

---

## 1. The exercise

**VNeST (Verb Network Strengthening Treatment)** helps adults with aphasia retrieve words by building a small scene around one
verb. For the verb *cook*, the patient answers five questions, each by choosing from 4 options:

| Step | Question shown to the patient | Example answer | Example wrong options |
|---|---|---|---|
| who | Who cooks? | chef | spoon, cloud, rock |
| what | What does the chef cook? | dinner | yesterday, boredom, tuesday |
| where | Where does the chef cook the dinner? | in the kitchen | inside a teapot, on a star, inside a raindrop |
| when | When does the chef cook the dinner? | in the evening | before time began, while sleeping, while flying to the moon |
| why | Why does the chef cook the dinner? | to feed the family | to make it rain, to turn into a cloud, to turn into a bird |

Then the patient judges whole sentences, "Does this make sense?":

- *The chef cooks the dinner.* → makes sense
- *The dinner cooks the chef.* → no sense (roles swapped)
- *The chef cooks the boredom.* → no sense (wrong object)

The wrong options are meant to be **clearly impossible**, not merely less likely. The task is to find the one that fits, and
a wrong option that might also be right would confuse the patient.

## 2. The design rule: the model writes, code checks

```
          ┌────────────────── ahead of time (background) ─────────────────┐
 verb ──► │ model writes who → what → where → when → why (5 requests)     │
          │ each reply checked in code; failed part retried (max 3 tries) │
          └──────────────────────────────┬────────────────────────────────┘
                                         ▼ stored exercise (JSON)
          ┌──────────────────── during practice (no model) ──────────────┐
patient ► │ app shows options, compares the tap with the stored answer   │
          └──────────────────────────────────────────────────────────────┘
```

- The model writes the **content** of an exercise: the answer and 3 wrong options per question.
- The app's **code** checks every reply before storing it, and checks every patient tap against the stored answer.
  The model never judges a patient's response, so feedback is instant, deterministic and safe.
- Exercises are written **ahead of time** and stored on the device. A whole exercise takes about a minute on a mid-range
  phone, so patients should not wait for it.

## 3. What you need

| Item | Detail |
|---|---|
| Device | Android, arm64, with an OpenCL GPU. Tested on a Galaxy Note10 (Snapdragon 855, 8 GB RAM). Budget about 0.75 GB of RAM for the model. |
| Model files | The Hugging Face repo above: 22 weight shards, `ndarray-cache.json`, `mlc-chat-config.json`, tokenizer files (about 705 MB in total). |
| Inference engine | [MLC LLM](https://github.com/mlc-ai/mlc-llm) for Android (`mlc4j`), with a compiled **model library** for Llama-3.2-1B `q4f16_0`. |
| Tested engine version | MLC LLM commit `7561c96d` (26 Sep 2024) with TVM `mlc-ai/relax@2912b0fc`. Newer MLC versions were not tested. |

### The model library

MLC splits a model into **weights** (the Hugging Face files) and a compiled **model library**: the GPU code for that
architecture and quantisation, linked into the app's engine (`libtvm4j_runtime_packed.so`). This model has exactly the
same architecture, tensor names, shapes and quantisation as the stock
[`mlc-ai/Llama-3.2-1B-Instruct-q4f16_0-MLC`](https://huggingface.co/mlc-ai/Llama-3.2-1B-Instruct-q4f16_0-MLC). Only the weight
values differ, so **any engine that already runs the stock Llama-3.2-1B `q4f16_0` model runs this one**. Point it at these
weights instead.

**Ready-made engine.** The engine the VNeST app uses (MLC LLM 2024, arm64, OpenCL) is a download on the
[engine-mlc2024-v1 release](https://github.com/maqamylee0/vnest/releases/tag/engine-mlc2024-v1): `libtvm4j_runtime_packed.so`
plus `tvm4j_core.jar`. It already contains the `llama1b_q4f16_0` library, so you can skip the compile step below.

To build the library yourself (MLC 2024, from source), compile from the model's own config with the same limits the app uses:

```bash
python -m mlc_llm compile mlc-chat-config.json --device android \
  --system-lib-prefix llama1b_q4f16_0_ \
  --overrides "context_window_size=2048;prefill_chunk_size=256;max_batch_size=1" \
  -o llama1b_q4f16_0.tar
```

Then link it into the engine as `mlc_llm package` does (MLC's `android/mlc4j/prepare_libs.py`). When loading, pass the
library name you chose (here `llama1b_q4f16_0`) as `modelLib`.

Keep the limits small. With MLC's defaults (32k context, 2,048-token prefill chunks), a 1.5B model froze the test phone
completely. One exercise question needs fewer than 200 tokens.

## 4. Running one request

Download the model folder once (for example to `context.getExternalFilesDir("")/Llama-3.2-1B-Instruct-VNeST-f1-q4f16_0/`),
check it against the repo's `SHA256SUMS`, then load it with the same limits:

```kotlin
val engine = MLCEngine()
engine.reload(modelDir.absolutePath, "llama1b_q4f16_0", mapOf(
    "max_num_sequence" to 1,
    "max_total_sequence_length" to 2048,
    "max_single_sequence_length" to 2048,
    "prefill_chunk_size" to 256,
))
```

Every question is one **independent** chat completion: reset the engine first (no chat history), send the system message and
one user message, and stream the reply.

```kotlin
engine.reset()
val stream = engine.chat.completions.create(
    messages = listOf(
        ChatCompletionMessage(role = ChatCompletionRole.system, content = SYSTEM_PROMPT),
        ChatCompletionMessage(role = ChatCompletionRole.user, content = userPrompt),
    ),
    temperature = 0.3f,
    max_tokens = 48,
    stream_options = StreamOptions(include_usage = true),
    response_format = ResponseFormat(type = "json_object", schema = PART_SCHEMA), // optional, see below
)
val text = buildString { for (chunk in stream) if (chunk.choices.isNotEmpty()) append(chunk.choices[0].delta.content?.asText().orEmpty()) }
```

Run one request at a time behind a lock: the phone's GPU gains nothing from running two in parallel.

### The system message (identical for all five questions)

```
You write Verb Network Strengthening Treatment (VNeST) exercises for adults with aphasia. Each question has one correct answer and 3 wrong options that are clearly impossible. Use short, very common, concrete English words. Reply only with JSON: {"answer": "...", "wrong1": "...", "wrong2": "...", "wrong3": "..."}.
```

### The reply

```json
{"answer": "chef", "wrong1": "spoon", "wrong2": "cloud", "wrong3": "rock"}
```

`PART_SCHEMA` makes MLC's grammar engine allow only replies of this shape:

```json
{"type": "object",
 "properties": {"answer": {"type": "string"}, "wrong1": {"type": "string"},
                "wrong2": {"type": "string"}, "wrong3": {"type": "string"}},
 "required": ["answer", "wrong1", "wrong2", "wrong3"], "additionalProperties": false}
```

The schema is **optional**. Without it, the model produced valid JSON on 100 % of held-out questions on a GPU, and generation on
the phone is roughly twice as fast (expected about 35 s per exercise instead of about 60 s; not yet measured on the phone). With
or without it, run the checks in section 5.

## 5. Writing one exercise: the five prompts

Ask the questions **in order**, one request each. Each prompt repeats the sentence built so far, which **your code** assembles
from the earlier answers; the model never writes the sentence itself.

Notation: `V` = the verb (*cook*), `V3` = its third-person form (*cooks*), `WHO`, `WHAT`, `WHERE`, `WHEN` = earlier answers,
with a leading *a / an / the* removed from `WHO` and `WHAT` (*"a chef"* → *chef*).

| Part | User message |
|---|---|
| who | `VNeST "V". who? Answer: a person (1 or 2 words) who often V3 things. Wrong: 3 things that cannot V.` |
| what | `VNeST "V". what? The WHO V3 ___. Answer: what the WHO V3. Wrong: 3 things nobody can V.` |
| where | `VNeST "V". where? The WHO V3 the WHAT ___. Answer: the usual place (2 to 4 words). Wrong: 3 impossible places.` |
| when | `VNeST "V". when? The WHO V3 the WHAT WHERE ___. Answer: the usual time (2 to 4 words). Wrong: 3 impossible times.` |
| why | `VNeST "V". why? The WHO V3 the WHAT WHERE WHEN ___. Answer: the usual reason, starting with "to" (2 to 5 words). Wrong: 3 silly reasons.` |

For example, the "where" prompt for *cook* after "chef" and "dinner" is:

```
VNeST "cook". where? The chef cooks the dinner ___. Answer: the usual place (2 to 4 words). Wrong: 3 impossible places.
```

**Variety across exercises.** If you already have exercises for this verb, append the people used so far to the "who" prompt:

```
... Wrong: 3 things that cannot cook. The answer must not be: chef, mother.
```

**Third person** (`V3`): add *es* after *s, x, z, ch, sh, o* (*wash* → *washes*, *go* → *goes*); change consonant + *y* to *ies*
(*carry* → *carries*); irregular: *have* → *has*, *be* → *is*, *do* → *does*; otherwise add *s*.

### Checking each reply

Treat every reply as untrusted. If any check fails, ask for **the same part** again, up to **3 tries in total**. If all 3 fail,
drop the exercise and try later; never show a part that failed.

First, **normalise** every string: trim it, remove trailing `.!?`, collapse repeated spaces, and lower-case it.

**Shape checks (every part):**

1. The reply parses as a JSON object with `answer`, `wrong1`, `wrong2`, `wrong3`.
2. `answer` is not empty.
3. The four options are all different after normalising (so there are exactly 3 wrong options).
4. No option is longer than 6 words.

**Content checks:**

| Check | Applies to | Reject when |
|---|---|---|
| A particular person | who | the answer (without *a/an/the*) is a generic word: person, someone, somebody, people, anyone, anybody, human, a human, man, woman, they, you, everyone, adult, patient |
| Not repeating the question | all | the answer's first word is who, what, where, when, why or how ("what the chef cooks") |
| Not copying the instructions | all | any option contains: usual place, usual time, usual reason, a person who, person who, things that cannot, nobody can, impossible place, impossible time, silly reason, wrong option, correct answer, the answer |
| Reason is not just the verb | why | after removing a leading "to" and the words it, them, the, a, an, nothing is left, or every remaining word starts with the verb's stem ("to cook", "to cook it", "to cooking"). Stem = the verb minus its last letter if it is longer than 4 letters, otherwise the whole verb. |
| A time, not a place | when | the answer does not start with after, before, during, while, every, once, twice, each or until; contains no time word; **and** contains a place word ("at home") |
| Person ≠ thing | what | the "what" answer equals the "who" answer (without *a/an/the*) |
| New person | who | the answer is one of the people passed in "must not be" |

Time words: morning, afternoon, evening, night, day, days, daily, week, weeks, weekend, weekends, weekday, month, months, year,
years, spring, summer, autumn, fall, winter, season, breakfast, lunch, lunchtime, dinner, supper, meal, meals, mealtime, bedtime,
naptime, playtime, recess, noon, midnight, dawn, sunrise, sunset, time, hour, hours, minute, minutes, today, tomorrow,
yesterday, monday … sunday, sundays, semester, holiday, holidays, birthday, christmas, am, pm, shift, class, lesson, lessons,
start, end, way.

Place words: home, house, kitchen, garden, yard, park, office, room, bedroom, bathroom, store, shop, market, field, farm,
garage, street, road, beach, river, lake, restaurant, bakery, church, hospital, classroom, library, studio, workshop, stadium,
gym, pool, barn, city, town, village.

Last, **shuffle** the four options before storing them. The model tends to put the answer first.

### Pseudocode

```python
PARTS = ["who", "what", "where", "when", "why"]

def write_exercise(verb, avoid_people=()):
    done = {}
    for part in PARTS:
        for attempt in range(3):
            reply = generate(SYSTEM_PROMPT, part_prompt(verb, part, done, avoid_people))
            try:
                q = parse_and_check_shape(part, reply)        # raises on failure
                check_content(part, q, verb, done, avoid_people)
                done[part] = q                                 # {"answer": ..., "options": shuffled 4}
                break
            except CheckFailed:
                continue
        else:
            return None                                        # give up on this exercise; retry later
    return {"verb": verb, "questions": done}
```

Store the result as JSON on the device:

```json
{"verb": "cook", "source": "llm",
 "questions": {
   "who":   {"options": ["rock", "chef", "cloud", "spoon"], "answer": "chef"},
   "what":  {"options": ["dinner", "tuesday", "boredom", "yesterday"], "answer": "dinner"},
   "where": {"options": ["on a star", "in the kitchen", "inside a teapot", "inside a raindrop"], "answer": "in the kitchen"},
   "when":  {"options": ["while sleeping", "in the evening", "before time began", "while flying to the moon"], "answer": "in the evening"},
   "why":   {"options": ["to make it rain", "to feed the family", "to turn into a cloud", "to turn into a bird"], "answer": "to feed the family"}}}
```

## 6. Running the practice session

No model is involved here. Everything below is plain code over the stored exercise.

1. **Who / what.** Show "Who `V3`?", then "What does the `WHO` `V`?", with the four stored options as large buttons. Compare the
   tap with the stored answer. On a wrong tap, mark that option and let the patient try again. Record whether the first tap was
   right.
2. **Where / when / why.** Show the scene so far on screen (*The chef cooks the dinner.*) so the patient does not have to hold it
   in memory, then ask "Where / When / Why does the `WHO` `V` the `WHAT`?" the same way.
3. **Hint** (optional). Remove one remaining wrong option, but always leave at least one.
4. **Does it make sense?** Build these sentences in code, shuffle them, and ask "makes sense / no sense" for each:
   - the real sentence: *The WHO V3 the WHAT.* (makes sense)
   - roles swapped: *The WHAT V3 the WHO.* (no sense)
   - a wrong object: *The WHO V3 the X.*, where X is one of the stored wrong "what" options (no sense)
5. **Feedback.** Show first-try counts per step at the end. Feedback depends only on the stored answers, so it is instant.

**Live mode** (optional). If a patient opens a verb with no stored exercise, start writing one at once and show each question as
soon as its part passes. The first question is ready after about 12 s on the Note10, and each later one about 11 s after the
previous, so the patient can start on "who" while the rest is written. Add the sentence checks once all five parts exist. If
writing fails, tell the patient plainly and offer to go back.

## 7. Scheduling and performance

Measured on the Galaxy Note10 (Snapdragon 855, 8 GB RAM), with the JSON schema on:

| Measure | Value |
|---|---|
| Model load | about 6 s |
| Memory while running | about 0.75 GB |
| One question | 10.6–12.4 s (prompt 119–136 tokens, reply 29–42 tokens) |
| One exercise (5 questions) | about 55–60 s |

- Write exercises in a **background loop**, one at a time: least-covered verb first, and skip a verb after 3 failed exercises
  in a row. If a patient is waiting for a verb, write that one next.
- Store a small number per verb (the app keeps 1). Pass the people already used as "must not be" to vary new ones.
- Let the user or caregiver stop writing (finish the current exercise, then unload the model) to free memory and battery.
- Keep a fallback: a few reviewed, hand-written exercises per verb, used when no model exercise exists.

## 8. Expected quality

On held-out verbs never seen in training (cook, drive, paint, plant, wash; 76 exercises, 380 questions):

| Measure | Untuned Llama-3.2-1B | This model |
|---|---|---|
| Exercises fully valid | 0 % | 100 % |
| Single questions passing the checks | 21 % | 100 % |
| Answers copying the instructions | 49 % | 0 % |
| Answer equal to the reference | 3 % | 36 % |

These are rule checks only. They show that the format and the obvious failures are under control, not that every exercise
is clinically good.

## 9. Known problems and what to do about them

| Problem | Example | Mitigation |
|---|---|---|
| Sense errors that pass every rule | *The maid washes the hair*; *The diner cooks the breakfast* | Have a therapist or caregiver approve exercises before patients see them, or at least let them flag and delete one. |
| Little variety | 10 different "who" answers across 76 exercises; often the same scene for a verb | Pass "must not be" people; keep several exercises per verb only if they differ. |
| Gender bias | On household verbs, the person was always a woman in a domestic role (mother, maid) | Review "who" answers; consider a reviewed list of people per verb and asking the model to write the rest of the scene. |
| Limited world knowledge (1B model) | Odd pairings from rare verbs | Prefer common, concrete verbs; keep the human review. |
| Words, not meaning, are checked | The rule lists catch known failure patterns only | Log every rejected reply and its reason; extend the lists from what you see. |

## 10. Checklist before you ship

- [ ] Model files verified with `sha256sum -c SHA256SUMS` after download.
- [ ] Engine loads the model with the small limits (2,048 context, 256 prefill chunk, 1 sequence).
- [ ] System message and the five prompts copied **exactly**, including spacing and punctuation.
- [ ] Temperature 0.3, at most 48 new tokens, engine reset before each request.
- [ ] Every shape and content check in section 5 implemented, with 3 tries per part.
- [ ] Options shuffled before storing.
- [ ] Patient taps checked against stored answers only; no model call during practice.
- [ ] Exercises written in the background and stored; a reviewed fallback exists.
- [ ] A human review step, or at least a way to flag and remove a bad exercise.
- [ ] "Built with Llama" shown in the app's about page, and the Llama 3.2 Community License included
      (it is in the model repo as `LICENSE.txt`).

## 11. Reference implementation

The VNeST Practice app (Flutter + Kotlin, [github.com/maqamylee0/vnest](https://github.com/maqamylee0/vnest)) implements
everything above:

| File | What it does |
|---|---|
| `vnest_app/lib/services/llm_service.dart` | Prompts, schema, per-part generation with retries, engine limits |
| `vnest_app/lib/data/scenario.dart` | Shape and content checks, word lists, third-person rule |
| `vnest_app/lib/services/scenario_service.dart` | Background writer, live mode, storage, fallback |
| `vnest_app/lib/screens/session_screen.dart` | Practice session, hint, sentence checks |
| `vnest_app/android/app/src/main/kotlin/rw/ongera/vnest_app/LlmChannel.kt` | MLC engine calls on Android |
| `tools/build_phone_models.sh`, `tools/package_engine.sh` | Compiling the model library and building the engine (MLC 2024) |

If something here differs from those files, the code is what the reported results were measured with.
