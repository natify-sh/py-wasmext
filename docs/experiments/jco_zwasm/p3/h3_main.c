#include <stdio.h>
#include "h3.h"
#include "h3_args.h"
#include "p3host.h"
static w2c_h3 I;
static wasm_rt_memory_t *m(void) { return w2c_h3_memory(&I); }
int main(void) {
  wasm_rt_init();
  p3_set_memory(m);
  wasm2c_h3_instantiate(&I, INST_ARGS);
  /* the component's lift of run is wit-component's fixup "hook0": task hook 0, run, task hook 1 */
  w2c_h3_0x5F_wasm_task_hook(&I, 0);
  u32 r = w2c_h3_wasi0x3Acli0x2Frun0x4000x2E30x2E00x23run(&I);
  w2c_h3_0x5F_wasm_task_hook(&I, 1);
  fflush(stdout);
  fprintf(stderr, "[p3] run -> %u; stream.write %d (%d bytes), future.read %d, blocked %d, waits %d, events %d\n",
          r, p3_stats[0], p3_stats[1], p3_stats[2], p3_stats[3], p3_stats[4], p3_stats[5]);
  wasm2c_h3_free(&I); wasm_rt_free();
  return (int)r;
}
