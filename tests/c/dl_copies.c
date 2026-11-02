/* Two copies of ONE artifact built with the default visibility, loaded by dlopen (argv[1], argv[2]: two paths of the same library; argv[3]: "global" or "local"): the table of the runtime of each copy holds
   the functions of THAT copy. If the `wasmext_own_*` functions were exported the dynamic linker would let the first copy's stand for the second's (the entries of the table relocate against them) and the second
   copy would run on the first one's state. tests/test_runtime.py. */
#include <dlfcn.h>
#include <stdio.h>
#include <string.h>
#include "artifact.h"

int main(int argc, char **argv) {
    typedef const artifact_api *(*get_api)(void);
    int mode = RTLD_NOW | (argc > 3 && strcmp(argv[3], "global") == 0 ? RTLD_GLOBAL : RTLD_LOCAL);
    void *h[2];
    const artifact_api *api[2];
    const wasmext_runtime *rt[2];
    size_t first = sizeof(wasmext_runtime_head) / sizeof(void *), slots = sizeof(wasmext_runtime) / sizeof(void *), k, same = 0;
    int i;
    if (argc < 3) return 2;
    for (i = 0; i < 2; i++) {
        h[i] = dlopen(argv[1 + i], mode);
        if (h[i] == NULL) { fprintf(stderr, "dlopen: %s\n", dlerror()); return 2; }
        api[i] = ((get_api)dlsym(h[i], "artifact_a"))();
        rt[i] = (const wasmext_runtime *)api[i]->runtime_id();
    }
    if (api[0]->id == api[1]->id || rt[0] == rt[1]) { fprintf(stderr, "the two copies are one (identity or table)\n"); return 1; }
    for (k = first; k < slots; k++) {
        const void *a = ((const void *const *)rt[0])[k], *b = ((const void *const *)rt[1])[k];
        if (a == b) { fprintf(stderr, "slot %zu of the table is the same function in both copies\n", k); same++; }
    }
    if (same) return 1;
    puts("ok");
    return 0;
}
