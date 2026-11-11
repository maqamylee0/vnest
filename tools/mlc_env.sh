# Environment for building MLC LLM models and the Android engine from source (RESEARCH_LOG Entry 7).
# Usage: source tools/mlc_env.sh   (from the vnest project root)
#
# Source: ~/Documents/research/mlc-llm at main 44fd06d0 (2026-10-30), TVM submodule 629cc658,
# TVM compiler built from source with LLVM 18 (3rdparty/tvm/build, Release, static LLVM).

export MLC_LLM_SOURCE_DIR=$HOME/Documents/research/mlc-llm
export TVM_SOURCE_DIR=$MLC_LLM_SOURCE_DIR/3rdparty/tvm
export TVM_LIBRARY_PATH=$TVM_SOURCE_DIR/build/lib
# This TVM version finds libtvm_runtime / libtvm_tirx_compiler via LD_LIBRARY_PATH (not TVM_LIBRARY_PATH)
export LD_LIBRARY_PATH=$TVM_LIBRARY_PATH${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
# MLC host library (libmlc_llm_module.so), built from source in $MLC_LLM_SOURCE_DIR/build (Release, no GPU backends)
export MLC_LIBRARY_PATH=$MLC_LLM_SOURCE_DIR/build
export PYTHONPATH=$TVM_SOURCE_DIR/python:$TVM_SOURCE_DIR/3rdparty/tvm-tirx/python:$MLC_LLM_SOURCE_DIR/python${PYTHONPATH:+:$PYTHONPATH}

export ANDROID_NDK=$HOME/Android/Sdk/ndk/28.2.13676358
export TVM_NDK_CC=$ANDROID_NDK/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android24-clang
export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64

VNEST_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
export PATH=$HOME/.cargo/bin:$VNEST_ROOT/.venv-mlc/bin:$PATH
