#!/bin/sh
# Builds the experiment in $WORK: a master `ft` with a runtime of its own, and slaves `ft2` and `ex` with none.
# Needs: wasmext (uv), wabt-package, a C compiler, CPython (PY=path of its python). The modules are ft.wat (../free_threading) and ex.wat (here).
set -eu
: "${WORK:?}" "${PY:?}" "${PROJECT:?}"
HERE=$(cd "$(dirname "$0")" && pwd)
INC_PY=$("$PY" -c "import sysconfig;print(sysconfig.get_paths()['include'])")
SUFFIX=$("$PY" -c "import sysconfig;print(sysconfig.get_config_var('EXT_SUFFIX'))")
WABT=$("$PY" -c "import wabt_package,os;print(os.path.dirname(wabt_package.__file__))")
mkdir -p "$WORK" && cd "$WORK"
build_one() {  # name role wasm
  name=$1; role=$2; wasm=$3
  mkdir -p "$name" && cp "$wasm" "$name/$name.wasm" && (cd "$name" && uv run --project "$PROJECT" wasmext natify $([ "$role" = chain ] || echo --share-tables) -q "$name.wasm")
  c="$name/build/wasmext/$name"
  python3 "$HERE/patch.py" "$role" "$c/${name}_py.c"
  flags="-O2 -fPIC -shared -w -DWASMEXT_TRAP_HANDLER=wasmext_trap_$name -I$c -I$HERE -I$WABT/wasm2c -I$INC_PY"
  if [ "$role" = one ]; then   # the whole runtime inside, its call of sigaction made a no-op; the first module installs the one handler (one_handler.h)
    for r in impl mem exceptions; do gcc $flags -include "$HERE/no_sigaction.h" ${EXTRA_FLAGS:-} -c "$c/${name}_rt_$r.c" -o "$name.$r.o"; done
    gcc $flags ${EXTRA_FLAGS:-} "$c/${name}_py.c" "$c/${name}_w2c.c" "$name.impl.o" "$name.mem.o" "$name.exceptions.o" -o "$name$SUFFIX"
  elif [ "$role" = chain ]; then   # the whole runtime inside and no handler of its own (as for `one`); the module's own chain handler. No shared stack: no WASMEXT_TRAP_HANDLER
    cf=$(echo "$flags" | sed "s/-DWASMEXT_TRAP_HANDLER=[A-Za-z0-9_]*//")${TLS_FLAGS:+ $TLS_FLAGS}
    for r in impl mem exceptions; do gcc $cf -include "$HERE/no_sigaction.h" -c "$c/${name}_rt_$r.c" -o "$name.$r.o"; done
    gcc $cf "$c/${name}_py.c" "$c/${name}_w2c.c" "$name.impl.o" "$name.mem.o" "$name.exceptions.o" -o "$name$SUFFIX"
  elif [ "$role" = dual ]; then   # a runtime of its own (its functions renamed own_*), and the forwarders that choose
    ren=""; for n in init is_initialized init_thread free_thread trap strerror allocate_memory grow_memory free_memory allocate_funcref_table grow_funcref_table free_funcref_table allocate_externref_table grow_externref_table free_externref_table set_unwind_target get_unwind_target load_exception throw exception_tag exception_size exception; do ren="$ren -Dwasm_rt_$n=own_wasm_rt_$n"; done
    for r in impl mem exceptions; do gcc $flags $ren -c "$c/${name}_rt_$r.c" -o "$name.$r.o"; done
    gcc $flags ${EXTRA_FLAGS:-} "$c/${name}_py.c" "$c/${name}_w2c.c" "$HERE/dual_shim.c" "$name.impl.o" "$name.mem.o" "$name.exceptions.o" -o "$name$SUFFIX"
  elif [ "$role" = master ] || [ "$role" = plain ]; then
    gcc $flags "$c/${name}_py.c" "$c/${name}_w2c.c" "$c/${name}_rt_impl.c" "$c/${name}_rt_mem.c" "$c/${name}_rt_exceptions.c" -o "$name$SUFFIX"
  else   # a slave: the C of the module and the glue, and the shim; no file of the runtime
    gcc $flags "$c/${name}_py.c" "$c/${name}_w2c.c" "$HERE/slave_shim.c" -o "$name$SUFFIX"
  fi
}
build_one ft master "${FT_WASM:?}"
build_one ft2 slave "${FT_WASM}"
build_one ex slave "${EX_WASM:?}"
build_one e1 one "${FT_WASM}"
build_one e2 one "${FT_WASM}"
EXTRA_FLAGS="-DWASMEXT_RUNTIME=12345u" build_one e3 one "${FT_WASM}"   # another runtime: it cannot join the stack of entries
build_one e4 plain "${FT_WASM}"   # a module that follows no convention: the default runtime, a handler of its own
build_one c1 chain "${FT_WASM}"
build_one c2 chain "${FT_WASM}"
build_one d1 dual "${FT_WASM}"
build_one d2 dual "${FT_WASM}"
EXTRA_FLAGS="-DWASMEXT_RUNTIME=12345u" build_one d3 dual "${FT_WASM}"   # another runtime (another layout fingerprint): it must not attach
echo built: *"$SUFFIX"
