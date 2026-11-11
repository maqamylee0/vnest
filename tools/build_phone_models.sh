#!/bin/bash
# Convert and compile the on-phone models with MLC 2024 (RESEARCH_LOG Entry 7). Run from the vnest project root.
# Outputs: weights in models/mlc/<id>/, compiled GPU code in build_mlc/libs2024/<lib>.tar, logs in build_mlc/.
# Every model gets an explicit, unique library name (--system-lib-prefix): Llama-1B and Llama-3B would otherwise both be
# "llama_q4f16_0_" and clash inside the one engine library. The app loads models by these names (LlmModel.lib).
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/mlc2024_env.sh"
cd "$VNEST_ROOT"
mkdir -p build_mlc/libs2024

HF_QWEN=models/hf/Qwen2.5-1.5B-Instruct   # Qwen/Qwen2.5-1.5B-Instruct, revision in REVISION

# The same limits as the app's engine settings (LlmService._limits), baked in at compile time for every model. MLC sizes its
# temporary buffer from the compile-time prefill chunk: with gen_config's default 8,192 tokens, Qwen (151,936-token
# vocabulary) needed 11,099 MB and failed to load on the Note10 (4,352 MB GPU memory); runtime overrides can't shrink it.
CTX=2048; CHUNK=256; BATCH=1
LIMITS="context_window_size=$CTX;prefill_chunk_size=$CHUNK;max_batch_size=$BATCH"

compile() {  # compile <mlc-chat-config.json> <library name>
  echo "== compile $2 ($LIMITS)"
  python -m mlc_llm compile "$1" --device android --system-lib-prefix "$2_" --overrides "$LIMITS" \
    -o "build_mlc/libs2024/$2.tar" > "build_mlc/compile2024_$2.log" 2>&1
  grep -E "Total memory usage" "build_mlc/compile2024_$2.log" | sed 's/.*INFO//' || true
}

# Qwen2.5-1.5B in both layouts, from the same original weights: q4f16_1 = "NK", q4f16_0 = "KN" (the layout test)
for Q in q4f16_1 q4f16_0; do
  OUT=models/mlc/Qwen2.5-1.5B-Instruct-$Q-vnest
  if [ ! -f "$OUT/ndarray-cache.json" ]; then
    echo "== convert_weight $Q"; python -m mlc_llm convert_weight $HF_QWEN --quantization $Q --device cpu -o $OUT > build_mlc/convert2024_qwen_$Q.log 2>&1
  fi
  echo "== gen_config $Q"   # always regenerated (cheap), so the config matches the limits above
  python -m mlc_llm gen_config $HF_QWEN --quantization $Q --conv-template qwen2 \
    --context-window-size $CTX --prefill-chunk-size $CHUNK --max-batch-size $BATCH -o $OUT > build_mlc/genconfig2024_qwen_$Q.log 2>&1
  compile $OUT/mlc-chat-config.json qwen2_$Q
done

# Llama-3.2-1B (candidate student) and Llama-3.2-3B (the app's current model): MLC's published q4f16_0 weights
compile models/mlc/Llama-3.2-1B-Instruct-q4f16_0-MLC/mlc-chat-config.json llama1b_q4f16_0
compile models/mlc/Llama-3.2-3B-Instruct-q4f16_0-MLC/mlc-chat-config.json llama3b_q4f16_0

echo "ALL DONE"; ls -la build_mlc/libs2024/
