#import "@preview/polylux:0.4.0": *
#import "@preview/jotter-polylux:0.1.0": (
  framed-block, post-it, setup, title-slide,
)

#set text(
  size: 25pt,
  font: "Kalam",
  fill: blue.darken(50%),
)

#show math.equation: set text(
  font: (
    "Pennstander Math",
    /* as a fallback: */
    "New Computer Modern Math",
  ),
  weight: "light",
)

#show raw: set text(font: "Fantasque Sans Mono")

#let today = datetime(year: 2026, month: 11, day: 11)

#show: setup.with(
  header: [ #today.display() ],
  highlight-color: red.lighten(30%),
  binding: true,
)

#set figure(numbering: none)

// Tables: no grid lines, light rule under the header row
#set table(stroke: none, inset: (x: 0.4em, y: 0.25em))
#let hdr(..cells) = cells.pos().map(c => strong(c))

#title-slide[VNeST Practice: an on-device model that writes aphasia exercises][

  #place(
    bottom + right,
    text("Carnegie Mellon University Africa", size: 0.7em),
  )
]


#slide[
  = #smallcaps("The Goal")

  VNeST Practice gives adults with aphasia verb exercises: for a verb
  (_cook_), pick who, what, where, when and why from 4 options each.

  - A small model *on the phone* writes the exercises
  - The app's code checks the patient's taps, not the model
  - Fully offline, low-cost Android devices, therapist-safe, reproducible
]


#slide[
  = #smallcaps("Where we are")

  A fine-tuned Llama-3.2-1B writes complete exercises *fully offline* on a
  Galaxy Note10, about 1 minute per exercise.

  #place(horizon + right, dx: -2em, dy: 1.5em)[
    #post-it[*100 %* \ valid on \ new verbs]
  ]
]


#slide[
  = #smallcaps("Work so far")

  #set text(size: 0.9em)
  - Dataset v1 → v2: 3,570 / 205 / 380 examples, audited
  - Own phone engine (MLC LLM, built from source); 4 models compared
  - Student chosen: Llama-3.2-1B (11 s to first token; 3B: 39 s)
  - Stricter content checks in the app and the scorer
  - Fine-tune f1: LoRA, about 2 minutes of GPU time
  - Phone export: 705 MB, runs on the Note10
]


#slide[
  = #smallcaps("Results: unseen verbs")

  #set text(size: 0.95em)
  cook, drive, paint, plant, wash: 76 exercises, 380 questions

  #table(
    columns: (auto, auto, auto),
    align: (left, center, center),
    table.header(..hdr[Measure][Untuned][Fine-tuned f1]),
    table.hline(stroke: 0.5pt),
    [Exercises fully valid], [0 %], [*100 %*],
    [Questions passing checks], [21 %], [*100 %*],
    [Copying the instructions], [49 %], [*0 %*],
    [Equal to the reference], [3 %], [*36 %*],
  )
]


#slide[
  = #smallcaps("On the phone")

  Galaxy Note10 (Snapdragon 855, 8 GB), 4-bit model

  #set text(size: 0.85em)
  - Size *705 MB*, memory about *0.75 GB*
  - Loads in *6 s*
  - About *11 s* per question, *55–60 s* per exercise
  - Written in the background ahead of time, so patients don't wait
]


#slide[
  = #smallcaps("What the scores don't show")

  #set text(size: 0.8em)
  - *Sense errors:* "The maid washes the hair" passes every rule
  - *Little variety:* 10 different "who" answers in 76 exercises
  - *Gender bias:* every person in phone tests was a woman in a
    domestic role (mother, maid)

  #framed-block[
    Mainly from the training data: small, ConceptNet + an 8B teacher.
  ]
]


#slide[
  = #smallcaps("Proposed path")

  #set text(size: 0.85em)
  - *Larger teacher:* agree. Llama 3.3 70B fits best (licence, own
    server, same family). Check licence before use.
  - *More examples:* the need is more distinct scenes: more verbs,
    several people per verb, gender-balanced roles
  - *Speech-language pathologist review:* agree, the missing piece
  - *Live feedback and hints:* changes scope; about 10 s per tap and
    clinical risk. Suggest hints written ahead of time, later phase
  - *Constrained decoding:* already in place; next, test without it
]


#slide[
  = #smallcaps("Next steps")

  #set text(size: 0.9em)
  + Therapist review: 100 exercises, 20 verbs
  + Variety, bias and sense measures in the scorer
  + Dataset v3 with a larger teacher
  + Train f2, compare with f1 on the same verbs
  + Speed test without the JSON schema (about 35 s / exercise)
  + Test on the target tablet
  + Paper write-up
]


#slide[
  = #smallcaps("When we're done")

  #set text(size: 0.72em)
  #table(
    columns: (auto, auto, auto),
    table.header(..hdr[Criterion][Target][Now]),
    table.hline(stroke: 0.5pt),
    [Offline on target device], [Chosen tablet], [Note10 yes; tablet not tested],
    [Valid exercises on device], [≥ 95 %], [100 % GPU; phone sample all valid],
    [Pathologist-rated acceptable], [≥ 90 % of ≥ 100], [Not done],
    [Unsafe content], [0], [None seen; not reviewed],
    [Variety ("who" per verb)], [≥ 3 in 3 requests], [About 1–2],
    [Female-coded, household verbs], [35–65 %], [About 100 %],
    [First question ready], [≤ 15 s], [12 s],
    [Whole exercise], [≤ 60 s], [55–60 s],
    [Model size / memory], [≤ 1 GB each], [705 MB / 0.75 GB],
  )
]


#slide[
  = #smallcaps("Decisions needed")

  #set text(size: 0.85em)
  - Target tablet model(s)
  - Teacher model for dataset v3 (and its licence)
  - Live feedback and hints: now or later?
  - Who reviews the exercises, and when
  - One exercise per verb, or three
]


#slide[

  #place(
    horizon + center,
    heading(level: 1, outlined: false)[#upper("Thank you!")],
  )

]
