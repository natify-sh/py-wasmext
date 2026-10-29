/* The start function of the module traps: `instantiate` answers its code, the instance can only be freed. Plain C. */
#include <stdio.h>
#include "wasmext_errors.h"
#define WASMEXT_DEFINE_THREAD_STATE
#include "wasmext_instance.h"

#define CAT_(a, b) a##b
#define CAT(a, b) CAT_(a, b)
extern const wasmext_binding CAT(MODULE, _binding);

int main(void) {
    wasmext_store *s = wasmext_store_new();
    wasmext_instance *i = wasmext_instance_new(s, &CAT(MODULE, _binding), NULL);
    int rc = wasmext_instance_instantiate(i);
    if (rc != (int)WASM_RT_TRAP_UNREACHABLE) { fprintf(stderr, "instantiate answered %d\n", rc); return 1; }
    if (wasmext_instance_status(i) != rc) return 1;
    wasmext_val r[1];
    if (wasmext_instance_call(i, 0, NULL, 0, r, 1) != WASMEXT_INST_NOT_INSTANTIATED) return 1;
    wasmext_instance_free(i);
    if (wasmext_store_free(s) != WASMEXT_STORE_OK) return 1;
    puts("ok");
    return 0;
}
