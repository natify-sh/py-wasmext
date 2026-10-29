/* Tests of wasmext_errors.h in plain C, over the runtime of wasm2c (no module, no Python). */
#include <stdio.h>
#include <string.h>
#include "wasmext_errors.h"

static int failures;
#define CHECK(COND) do { if (!(COND)) { fprintf(stderr, "%s:%d: check failed: %s\n", __FILE__, __LINE__, #COND); failures++; } } while (0)

static void expect(int code, int kind) {
    wasmext_error_info info = wasmext_error_describe(code);
    CHECK(info.kind == kind);
    CHECK(info.text != NULL && info.text[0] != 0);
}

int main(void) {
    expect((int)WASMEXT_TRAP_HOST, WASMEXT_ERR_HOST);
    expect((int)WASMEXT_TRAP_NO_MEMORY, WASMEXT_ERR_NOMEM);
    expect((int)WASMEXT_TRAP_ENDED, WASMEXT_ERR_ENDED);
    expect((int)WASMEXT_TRAP_LINK_ERROR, WASMEXT_ERR_LINK);
    expect((int)WASMEXT_TRAP_CLOSED, WASMEXT_ERR_CLOSED);
    expect((int)WASM_RT_TRAP_UNCAUGHT_EXCEPTION, WASMEXT_ERR_UNCAUGHT);
    expect((int)WASM_RT_TRAP_OOB, WASMEXT_ERR_TRAP);
    expect((int)WASM_RT_TRAP_DIV_BY_ZERO, WASMEXT_ERR_TRAP);
    /* the text of a trap of the runtime is the runtime's own */
    CHECK(strcmp(wasmext_error_describe((int)WASM_RT_TRAP_OOB).text, wasm_rt_strerror(WASM_RT_TRAP_OOB)) == 0);
    /* the codes of wasmext do not collide with each other */
    {
        int codes[] = {(int)WASMEXT_TRAP_HOST, (int)WASMEXT_TRAP_NO_MEMORY, (int)WASMEXT_TRAP_ENDED, (int)WASMEXT_TRAP_LINK_ERROR, (int)WASMEXT_TRAP_CLOSED};
        for (int i = 0; i < 5; i++)
            for (int j = i + 1; j < 5; j++) CHECK(codes[i] != codes[j]);
    }
    if (failures) return 1;
    puts("ok");
    return 0;
}
