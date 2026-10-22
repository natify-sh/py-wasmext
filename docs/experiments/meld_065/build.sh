#!/bin/sh
# meld 0.65.0 against the complex component of docs/experiments/jco_zwasm/complex (the check of meld #512 and #513). Linux x86-64. [run] 2026-10-22.
# Tools (release tarballs, no build): wasi-sdk 34.0, wit-bindgen 0.63.0, wasmtime 50.0.0 (v50.0.1 has no tarball), wasm-tools 1.262.0, meld 0.65.0 and 0.64.0
#   meld: https://github.com/pulseengine/meld/releases/download/v0.65.0/meld-v0.65.0-x86_64-unknown-linux-gnu.tar.gz  (sha256 in SHA256SUMS.txt of the release)
# usage: build.sh SDK WIT_BINDGEN WASMTIME MELD_065 MELD_064      (SDK: the directory of wasi-sdk; the others: the executables)
set -e
SDK=$1; WB=$2; WT=$3; M65=$4; M64=$5
SRC=../jco_zwasm/complex
mkdir -p work && cd work && cp $SRC/* .
$WB c cx.wit --world guest --out-dir gg && $WB c cx.wit --world provider --out-dir gp   # the sources include "gg/guest.h" and "gp/provider.h"
# -mexec-model=reactor: without it each component also exports wasi:cli/run, and `meld fuse --component` writes the export name `run$0` (not valid: see README)
$SDK/bin/clang --target=wasm32-wasip2 -mexec-model=reactor -O1 -I. guest_impl.c gg/guest.c gg/guest_component_type.o -o guestc.wasm
$SDK/bin/clang --target=wasm32-wasip2 -mexec-model=reactor -O1 -I. provider_impl.c gp/provider.c gp/provider_component_type.o -o providerc.wasm
wasm-tools compose guestc.wasm -d providerc.wasm -o cxr.wasm        # deprecated in favour of wac; it wants kebab-case file names
echo "--- unfused";          $WT run --invoke 'run-all()' cxr.wasm
$M64 fuse --component --memory multi cxr.wasm -o cxr.f64.wasm >/dev/null
echo "--- fused, meld 0.64"; $WT run --invoke 'run-all()' cxr.f64.wasm
$M65 fuse --component --memory multi cxr.wasm -o cxr.f65.wasm >/dev/null
echo "--- fused, meld 0.65"; $WT run --invoke 'run-all()' cxr.f65.wasm
