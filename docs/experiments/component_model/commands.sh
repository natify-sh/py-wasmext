# The commands of the experiments of the second session, in the order of the report. $SDK, $WT, $WB, $W are the paths of wasi-sdk,
# wasm-tools, wit-bindgen and `wasmext` (see docs/WASI_COMPONENTS.md, "Tools"). Not a script to run as it is: some steps edit a file by hand.

## bindings: wit-bindgen c for both worlds
$WB c wit --world guest    --out-dir gen_guest      # guest.c, guest.h, guest_component_type.o
$WB c wit --world provider --out-dir gen_provider   # provider.c, provider.h, provider_component_type.o

## build, unbundle, natify
for w in guest provider; do
  $SDK/bin/clang --target=wasm32-wasip2 -O1 -mexec-model=reactor -o $w.component.wasm \
      ${w}_impl.c gen_$w/$w.c gen_$w/${w}_component_type.o
  $WT component unbundle $w.component.wasm --module-dir unb_$w -o unb_$w/rest.wasm
  cp unb_$w/unbundled-module0.wasm _$w.wasm     # natify refuses a name with a hyphen
done
$W inspect _provider.wasm      # imports (0) ... result: can be wrapped
$W natify -i -b -q _guest.wasm _provider.wasm

## the adapter in wasm: wat2wasm, inspect, natify
wat2wasm _adapter.wat -o _adapter.wasm    # multi-memory is on by default in WABT 1.0.42 (there is only --disable-multi-memory)
$W inspect _adapter.wasm                  # guest.memory, prov.memory: "ok (the memory of another instance)"; result: can be wrapped
$W natify -i -b -q _adapter.wasm

## the guest memory moved into a holder module (the cycle)
$WT print _guest.wasm > g.wat
# remove "(memory (;0;) 2)" and insert after the last import:
#   (import "env" "memory" (memory (;0;) 2))
$WT parse g2.wat -o _guest2.wasm && $WT validate _guest2.wasm
echo '(module (memory (export "memory") 2))' > _memhold.wat && $WT parse _memhold.wat -o _memhold.wasm
$W natify -i -b -q _guest2.wasm _memhold.wasm

## the short way: the same guest as wasm32-wasip1
$SDK/bin/clang --target=wasm32-wasip1 -O1 -mexec-model=reactor -o _guest_p1.wasm \
    guest_impl.c gen_guest/guest.c gen_guest/guest_component_type.o
$W inspect _guest_p1.wasm
#   imports (6): demo:text/host@0.1.0.lookup, .log,
#                wasi_snapshot_preview1.clock_time_get, fd_close, fd_seek, fd_write
#   exports: memory, _initialize, cabi_realloc, demo:text/api@0.1.0#greet, cabi_post_…#greet
#   result: can be wrapped

## compose and unbundle (part 5.1 of the old report)
cp provider.component.wasm provider.wasm && cp guest.component.wasm guestc.wasm   # compose wants kebab-case names
$WT compose guestc.wasm -d provider.wasm -o composed.wasm   # WARNING: deprecated, use wac
$WT component wit composed.wasm      # imports only wasi:*, exports demo:text/api@0.1.0 (host is wired inside)
$WT component unbundle composed.wasm --module-dir unb_comp -o unb_comp/rest.wasm
#   unbundled-module0.wasm 263 804   (= _guest.wasm)
#   unbundled-module1.wasm  52 279   (= _provider.wasm, byte for byte)
#   rest.wasm               13 427   with 22 "canon lift" / "canon lower"

## jco transpile
npm i @bytecodealliance/jco          # 1.39.0
npx jco transpile composed.wasm -o out --no-typescript
#   out/composed.core.wasm   263 804   (guest)
#   out/composed.core2.wasm   52 279   (provider)
#   out/composed.js          237 555   (glue) + base64-embedded modules

## cross-AOT of Wasmtime
for t in x86_64-unknown-linux-gnu aarch64-unknown-linux-gnu aarch64-apple-darwin aarch64-pc-windows-msvc \
         riscv64gc-unknown-linux-gnu s390x-unknown-linux-gnu i686-unknown-linux-gnu \
         armv7-unknown-linux-gnueabihf pulley32 pulley64; do
  aot composed.wasm x_$t.cwasm $t
done

## CoreMark
uv run --group wasm python examples/coremark/build_wasm.py
aot _core.wasm core.cwasm                    # 53 608
$W natify -i -b -q _core.wasm                # _core.abi3.so: 609 224, 69 184 after strip
python bench.py wasm2c; python bench.py cranelift    # twice each
