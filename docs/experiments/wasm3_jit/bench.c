// A small driver for wasm3: load a module, call an i32 function with one i32 argument, time it.
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include "wasm3.h"
int main(int argc, char **argv) {
    if (argc < 4) { fprintf(stderr, "usage: bench file.wasm func n [reps]\n"); return 2; }
    FILE *f = fopen(argv[1], "rb"); if (!f) return 3;
    fseek(f, 0, SEEK_END); long len = ftell(f); fseek(f, 0, SEEK_SET);
    unsigned char *buf = malloc(len); if (fread(buf, 1, len, f) != (size_t)len) return 3; fclose(f);
    int n = atoi(argv[3]), reps = argc > 4 ? atoi(argv[4]) : 3;
    IM3Environment env = m3_NewEnvironment();
    IM3Runtime rt = m3_NewRuntime(env, 64 * 1024, NULL);
    IM3Module mod; M3Result r = m3_ParseModule(env, &mod, buf, len); if (r) { fprintf(stderr, "parse: %s\n", r); return 4; }
    r = m3_LoadModule(rt, mod); if (r) { fprintf(stderr, "load: %s\n", r); return 4; }
    IM3Function fn; r = m3_FindFunction(&fn, rt, argv[2]); if (r) { fprintf(stderr, "find: %s\n", r); return 4; }
    for (int k = 0; k < reps; k++) {
        struct timespec a, b; clock_gettime(CLOCK_MONOTONIC, &a);
        r = m3_CallV(fn, n); if (r) { fprintf(stderr, "call: %s\n", r); return 5; }
        clock_gettime(CLOCK_MONOTONIC, &b);
        unsigned int ret = 0; m3_GetResultsV(fn, &ret);
        double s = (b.tv_sec - a.tv_sec) + (b.tv_nsec - a.tv_nsec) / 1e9;
        printf("result %u  %.3f s  %.1f M iterations/s\n", ret, s, n / s / 1e6);
    }
    return 0;
}
