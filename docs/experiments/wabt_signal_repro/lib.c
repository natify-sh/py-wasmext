/* A "plugin": one wasm2c module plus its own copy of the runtime, behind two functions. Built twice, as liba.so and libb.so. */
#include <wasm-rt.h>
#include <wasm-rt-exceptions.h>
#include <wasm-rt-impl.h>
#include "NAME.h"
static w2c_NAME inst;
__attribute__((visibility("default"))) void NAME_setup(void) { wasm_rt_init(); wasm2c_NAME_instantiate(&inst); }
/* returns 0 if the call trapped (the trap was caught here), 1 if it returned */
__attribute__((visibility("default"))) int NAME_oob(void) {
    wasm_rt_trap_t code = wasm_rt_impl_try();
    if (code) return 0;
    w2c_NAME_oob(&inst);
    return 1;
}
