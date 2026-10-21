#include <stdio.h>
#include <string.h>
#include "fb.h"
#include "fb_glue_args.h"
int main(void) {
  static w2c_fb I;
  if (zw_init()) return 100;
  wasm_rt_init();
  wasm2c_fb_instantiate(&I, GLUE_INST_ARGS);
  if (glue_init(&I)) return 101;
  u32 ret = w2c_fb_demo0x3Acx0x2Fapp0x4000x2E10x2E00x23run0x2Dall(&I);
  u8 *m = w2c_fb_memory0x240(&I)->data; u32 sp, sl; memcpy(&sp, m + ret, 4); memcpy(&sl, m + ret + 4, 4);
  printf("%.*s\n", (int)sl, (char *)m + sp);
  w2c_fb_cabi_post_demo0x3Acx0x2Fapp0x4000x2E10x2E00x23run0x2Dall(&I, ret);
  glue_stats();
  wasm2c_fb_free(&I); wasm_rt_free();
  return 0;
}
