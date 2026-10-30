/* Prints the hash of the layout of the core and of the host, for tests/test_artifacts.py (it compiles this over a copy of the headers with two fields swapped). */
#include <stdio.h>
#include "wasmext_table.h"
#include "wasmext_host.h"

int main(void) {
    printf("%u %u\n", (unsigned)WASMEXT_CORE_LAYOUT, (unsigned)WASMEXT_HOST_LAYOUT);
    return 0;
}
