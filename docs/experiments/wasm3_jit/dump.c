// Dump the metacode of a function with the names of the operations (a work copy of wasm3 is linked in).
#include <stdio.h>
#include <stdlib.h>
#include "wasm3.h"
#include "m3_env.h"
#include "m3_function.h"
extern const char *jit_opname(const void *);
int main(int argc, char **argv) {
    FILE *f = fopen(argv[1], "rb"); fseek(f, 0, SEEK_END); long len = ftell(f); fseek(f, 0, SEEK_SET);
    unsigned char *buf = malloc(len); if (fread(buf, 1, len, f) != (size_t)len) return 3; fclose(f);
    IM3Environment env = m3_NewEnvironment(); IM3Runtime rt = m3_NewRuntime(env, 64 * 1024, NULL);
    IM3Module mod; if (m3_ParseModule(env, &mod, buf, len)) return 4; if (m3_LoadModule(rt, mod)) return 4;
    IM3Function fn; if (m3_FindFunction(&fn, rt, argv[2])) return 4;
    unsigned n = 0;
    for (const unsigned long *p = (const unsigned long *)fn->compiled; n < 400; p++, n++) {
        const char *nm = jit_opname((const void *)*p);
        if (nm) printf("\n%-26s", nm); else printf("  %#lx", *p & 0xffffffffUL);
        if (nm && !__builtin_strcmp(nm, "Return")) break;
    }
    printf("\n");
}
