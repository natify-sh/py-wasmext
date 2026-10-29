/* A v128 crosses the core as 16 bytes of the order of WebAssembly memory. Plain C. */
#include <stdio.h>
#include "wasmext_instance.h"

#define CAT_(a, b) a##b
#define CAT(a, b) CAT_(a, b)
extern const wasmext_binding CAT(MODULE, _binding);

int main(void) {
    wasmext_store *s = wasmext_store_new();
    wasmext_instance *i = wasmext_instance_new(s, &CAT(MODULE, _binding), NULL);
    wasmext_val a[1], r[1];
    int32_t lanes[4] = {1, -2, 300000, 7}, out[4];
    int index = wasmext_instance_export_find(i, "double", 6, WASMEXT_DESC_FUNC);
    if (index < 0 || wasmext_instance_instantiate(i) != 0) return 1;
    memset(a, 0, sizeof a);
    a[0].type = 0x7B;
    memcpy(a[0].as.v128, lanes, 16); /* little-endian: the order of the lanes in memory */
    if (wasmext_instance_call(i, (uint32_t)index, a, 1, r, 1) != 0 || r[0].type != 0x7B) return 2;
    memcpy(out, r[0].as.v128, 16);
    for (int k = 0; k < 4; k++)
        if (out[k] != lanes[k] * 2) { fprintf(stderr, "lane %d: %d\n", k, out[k]); return 3; }
    wasmext_instance_free(i);
    wasmext_store_free(s);
    puts("ok");
    return 0;
}
