#include <stdio.h>
#include "ie.h"
struct w2c_env { int marker; };
static struct w2c_env env = {42};
static int direct_calls_ok = 1;
u32 w2c_env_f(struct w2c_env* e, u32 x) {
  if (e != &env) { direct_calls_ok = 0; printf("  host function got module instance %p, expected %p\n", (void*)e, (void*)&env); }
  return x + 1;
}
int main(void) {
  wasm_rt_init();
  w2c_ie inst;
  wasm2c_ie_instantiate(&inst, &env);
  u32 r = w2c_ie_run(&inst, 5);   /* local.get 0; i32.const 0; call_indirect: calls $f through the table */
  printf("run(5) = %u (expected 6); host got its own instance: %s\n", r, direct_calls_ok ? "yes" : "NO");
  return direct_calls_ok ? 0 : 1;
}
