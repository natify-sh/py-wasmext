#!/bin/sh
# usage: build.sh BIN RT   (BIN: wat2wasm, wasm2c; RT: the wasm2c/ directory of wabt). Makes ./guard ./depth ./sp
set -e
BIN=$1; RT=$2
$BIN/wat2wasm ft.wat -o ft.wasm
$BIN/wasm2c ft.wasm -o ft.c --module-name=ft
SRC="bench.c ft.c $RT/wasm-rt-impl.c $RT/wasm-rt-mem-impl.c $RT/wasm-rt-exceptions-impl.c"
CC="gcc -O2 -I$RT -I. -lpthread"
$CC -o guard $SRC
$CC -DWASM_RT_STACK_DEPTH_COUNT=1 -o depth $SRC
# sp: the runtime takes no option (NONCONFORMING_UNCHECKED) and the prologue of the generated C is the one that checks the address of the frame
python3 - <<'PY'
import re
s = open('ft.c').read()
old = "#else\n#define FUNC_PROLOGUE\n\n#define FUNC_EPILOGUE\n#endif"
assert old in s
new = ("#else\nextern __thread uintptr_t wasmext_stack_limit;\n"
       "#define FUNC_PROLOGUE if (__builtin_expect((uintptr_t)__builtin_frame_address(0) < wasmext_stack_limit, 0)) TRAP(EXHAUSTION);\n\n"
       "#define FUNC_EPILOGUE\n#endif")
open('ft_sp.c', 'w').write(s.replace(old, new, 1))
PY
$CC -DMODE_SP -DWASM_RT_NONCONFORMING_UNCHECKED_STACK_EXHAUSTION=1 -o sp bench.c ft_sp.c $RT/wasm-rt-impl.c $RT/wasm-rt-mem-impl.c $RT/wasm-rt-exceptions-impl.c
