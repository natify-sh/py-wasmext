/* A module whose memory cannot be had: instantiate answers WASMEXT_TRAP_NO_MEMORY (the allocation of a memory traps in the wrapper of the runtime that the product builds; the raw runtime
   would abort the process), the instance is not usable and not a member, and the store closes and frees without a leak or a use after free. */
#define WASMEXT_DEFINE_THREAD_STATE
#include <stdio.h>
#include "wasmext_errors.h"
#include "wasmext_instance.h"

extern const wasmext_binding big_binding;

static int failures;
#define CHECK(COND) do { if (!(COND)) { fprintf(stderr, "%s:%d: check failed: %s\n", __FILE__, __LINE__, #COND); failures++; } } while (0)

int main(void) {
    wasmext_store *s = wasmext_store_new();
    wasmext_instance *i = wasmext_instance_new(s, &big_binding, NULL);
    CHECK(i != NULL);
    CHECK(wasmext_instance_instantiate(i) == (int)WASMEXT_TRAP_NO_MEMORY);
    CHECK(wasmext_error_describe((int)WASMEXT_TRAP_NO_MEMORY).kind == WASMEXT_ERR_NOMEM);
    CHECK(i->instantiated == 0 && i->owner == 0);
    CHECK(wasmext_instance_call(i, 0, NULL, 0, NULL, 0) != 0); /* not usable */
    CHECK(wasmext_instance_free(i) == WASMEXT_STORE_OK); /* never registered: freed by hand */
    CHECK(wasmext_store_close(s) == WASMEXT_STORE_OK && wasmext_store_free(s) == WASMEXT_STORE_OK);
    if (failures) { fprintf(stderr, "%d failed\n", failures); return 1; }
    puts("ok");
    return 0;
}
