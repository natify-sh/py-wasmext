/* Prints WASMEXT_FUSEDWASI_VERSION as the build of the test passed it (tests/test_instance_core.py). */
#define WASMEXT_DEFINE_THREAD_STATE
#include <stdio.h>
#include "wasmext_errors.h"
#include "wasmext_instance.h"  /* the binding of the module needs its definitions */

#define STR_(x) #x
#define STR(x) STR_(x)

int main(void) {
#ifdef WASMEXT_FUSEDWASI_VERSION
    puts(STR(WASMEXT_FUSEDWASI_VERSION));
#else
    puts("undefined");
#endif
    return 0;
}
