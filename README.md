# VNeST Practice: an on-device model that writes aphasia exercises

Research code for **VNeST Practice**, an Android app that gives adults with aphasia Verb Network Strengthening Treatment
(VNeST) exercises. A small fine-tuned language model, Llama-3.2-1B, writes the exercises **fully offline on the phone**. The
app's code checks every model reply and every patient answer, so feedback never depends on the model.

**Model:** [`emmilly/Llama-3.2-1B-Instruct-VNeST-f1-q4f16_0-MLC`](https://huggingface.co/emmilly/Llama-3.2-1B-Instruct-VNeST-f1-q4f16_0-MLC)
(4-bit, MLC LLM format, about 705 MB). Built with Llama.

> Research use only. The model and its exercises have not been reviewed by a speech-language pathologist. See the known
> problems in the model card and the progress report.

## Start here

| If you want to… | Read |
|---|---|
| Use the model in your own app | [docs/implementing_vnest_exercises_with_the_model.md](docs/implementing_vnest_exercises_with_the_model.md) |
| See where the project stands | [docs/progress_report_2026-11-11.md](docs/progress_report_2026-11-11.md), slides in [presentations/](presentations/) |
| Follow every step, decision and failure | [RESEARCH_LOG.md](RESEARCH_LOG.md) |

## Layout

| Folder | Contents |
|---|---|
| `vnest_app/` | The Flutter app (Android), including the MLC engine bridge in Kotlin |
| `vnest_dataset/` | Dataset scripts and data: v1 (`out/`) and v2 (`out_v2/`, used for training) |
| `notebooks/` | Marimo notebooks: training, evaluation, phone export |
| `common/` | Shared Python module: prompts, scoring, checks |
| `tools/` | Scripts that build the phone models and the MLC engine (MLC LLM 2024) |
| `logs/` | Phone test logs |
| `docs/`, `presentations/` | Reports, guide, slides |

Model weights and checkpoints are on Hugging Face, not in git. The compiled Android engine (`libtvm4j_runtime_packed.so`,
109 MB) is a download on the [engine-mlc2024-v1 release](https://github.com/maqamylee0/vnest/releases/tag/engine-mlc2024-v1):
put it in `vnest_app/android/app/src/main/jniLibs/arm64-v8a/` before building the app.

## Data notes

The dataset is built from ConceptNet and a Llama-3.1-8B-Instruct teacher (see `vnest_dataset/docs/GENERATION.md`).
**Dataset v1 (`vnest_dataset/out/`) contains 2 offensive sentences** that came from ConceptNet slang. They were found in an
audit and removed in v2. Use v2.
