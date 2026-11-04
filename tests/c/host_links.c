/* A host that includes the core headers and uses none of the symbols that only an artifact defines (its thread state, its runtime table, its identity): at -O0 it must still link (tests/test_core_headers_link.py). */
#include "wasmext_table.h"

int main(void) { return 0; }
