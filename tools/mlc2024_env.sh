# Environment for compiling models and building the Android engine with the SAME MLC version the app's
# current engine came from (MLC LLM Android release Android-09262024). RESEARCH_LOG Entry 7.
# Usage: source tools/mlc2024_env.sh   (from the vnest project root)
#
# Source: git worktree ~/Documents/research/mlc-llm-2024 at mlc-llm 7561c96d (2024-09-26, "[Android] Update Andorid APK"),
#         TVM submodule mlc-ai/relax 2912b0fc (same as the app's tvm4j_core.jar).
# TVM built from source: Release, LLVM 18 linked dynamically (static linking needs libPolly.a, not in Ubuntu's llvm-18-dev).
# MLC host library built from source: Release, no GPU backends.
# Python env: .venv-mlc2024 (Python 3.12, numpy<2, torch 2.15.0).

VNEST_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
export MLC_LLM_SOURCE_DIR=$HOME/Documents/research/mlc-llm-2024
export TVM_SOURCE_DIR=$MLC_LLM_SOURCE_DIR/3rdparty/tvm
export TVM_LIBRARY_PATH=$TVM_SOURCE_DIR/build
export MLC_LIBRARY_PATH=$MLC_LLM_SOURCE_DIR/build
export LD_LIBRARY_PATH=$TVM_LIBRARY_PATH:$MLC_LIBRARY_PATH${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
export PYTHONPATH=$TVM_SOURCE_DIR/python:$MLC_LLM_SOURCE_DIR/python${PYTHONPATH:+:$PYTHONPATH}

export ANDROID_NDK=$HOME/Android/Sdk/ndk/28.2.13676358
export TVM_NDK_CC=$ANDROID_NDK/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android24-clang
export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64

export PATH=$HOME/.cargo/bin:$VNEST_ROOT/.venv-mlc2024/bin:$PATH
# Current Rust (1.99) rejects two lines of tokenizers-cpp's 2024 code ("implicit autoref creates a reference to the
# dereference of a raw pointer" is a hard error, not a lint). Fixed in the source by making the reference explicit:
# tools/mlc_patches/tokenizers-cpp_c0fab1e1_explicit_autoref_rust_1.99.patch (apply in 3rdparty/tokenizers-cpp).
# (Pinning Rust 1.81.0 fails instead: tokenizers-cpp has no Cargo.lock, so cargo pulls today's crates, which need newer Rust.)
