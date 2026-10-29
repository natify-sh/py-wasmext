/* A binding that answers every WASI function of the table is compiled and linked: the typed functions, the headers and the signatures are right. Nothing runs. */
#define WASMEXT_DEFINE_THREAD_STATE
#include <stdio.h>
#include "wasmext_instance.h"

#define CAT_(a, b) a##b
#define CAT(a, b) CAT_(a, b)
extern const wasmext_binding CAT(MODULE, _binding);

int main(void) {
    const wasmext_binding *b = &CAT(MODULE, _binding);
    if (b->descriptor->n_imports < 40 || b->import_slot == NULL || b->wasi_end == NULL) return 1;
    puts("ok");
    return 0;
}
