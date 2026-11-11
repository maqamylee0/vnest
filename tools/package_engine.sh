#!/bin/bash
# Build the app's MLC engine library (libtvm4j_runtime_packed.so + tvm4j_core.jar) from the compiled models in
# build_mlc/libs2024/, with MLC 2024 (RESEARCH_LOG Entry 7). Does what `mlc_llm package` does for Android, without its
# weight bundling: (1) merge the model .tar files into build/lib/libmodel_android.a and list the model libraries in it,
# (2) run MLC's android/mlc4j/prepare_libs.py, which builds TVM + MLC + tokenizers for arm64 with the NDK and links the models.
# Output: build_mlc/engine2024/build/output/{arm64-v8a/libtvm4j_runtime_packed.so,tvm4j_core.jar}
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/mlc2024_env.sh"
cd "$VNEST_ROOT"
W=build_mlc/engine2024
rm -rf "$W" && mkdir -p "$W/build/lib"

python - "$W/build/lib/libmodel_android.a" build_mlc/libs2024/*.tar <<'EOF'
import sys
from tvm.contrib import cc
out, tars = sys.argv[1], sys.argv[2:]
cc.create_staticlib(out, tars)
libs = sorted(n[:-len("___tvm_dev_mblob")].lstrip("_") for n in cc.get_global_symbol_section_map(out)
              if n.endswith("___tvm_dev_mblob"))
print("model libraries in libmodel_android.a:", libs)
assert len(libs) == len(tars), f"expected {len(tars)} model libraries, found {libs}"
EOF

cd "$W"
python "$MLC_LLM_SOURCE_DIR/android/mlc4j/prepare_libs.py" --mlc-llm-source-dir "$MLC_LLM_SOURCE_DIR"
ls -la build/output build/output/arm64-v8a
sha256sum build/output/arm64-v8a/libtvm4j_runtime_packed.so build/output/tvm4j_core.jar
