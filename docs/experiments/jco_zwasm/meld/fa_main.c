/* meld-fused guest+provider (one core module, two memories) via wasm2c, WASI by zwasm's host */
#include <stdio.h>
#include <string.h>
#include "fa.h"
#include "fa_glue_args.h"
int main(int argc, char **argv) {
  static w2c_fa I;
  if (zw_init()) return 100;
  wasm_rt_init();
  wasm2c_fa_instantiate(&I, GLUE_INST_ARGS);
  if (glue_init(&I)) return 101;
  for (int i = 1; i < argc; i++) {
    u32 n = (u32)strlen(argv[i]);
    u32 p = w2c_fa_cabi_realloc0x241(&I, 0, 0, 1, n);
    memcpy(w2c_fa_memory0x240(&I)->data + p, argv[i], n);
    u32 ret = w2c_fa_demo0x3Atext0x2Fapi0x4000x2E10x2E00x23greet(&I, p, n);
    u8 *m = w2c_fa_memory0x240(&I)->data; u32 sp, sl; memcpy(&sp, m + ret, 4); memcpy(&sl, m + ret + 4, 4);
    printf("greet(%s) -> %.*s\n", argv[i], (int)sl, (char *)m + sp);
    w2c_fa_cabi_post_demo0x3Atext0x2Fapi0x4000x2E10x2E00x23greet(&I, ret);
  }
  wasm2c_fa_free(&I); wasm_rt_free();
  return 0;
}
