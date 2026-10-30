/* Check (a) of the "C first" plan for layer 1 (docs/layers.md): the static headers of the core are compiled strictly (-Wall -Wextra -Werror; the pytest builds have the warnings
   off, for the C of wasm2c) with no Python on the include path, every header that a front end includes. Extend it with each step. */
#define WASMEXT_DEFINE_THREAD_STATE
#include "wasmext_descriptor.h"
#include "wasmext_errors.h"
#include "wasmext_rlock.h"
#include "wasmext_registry.h"
#include "wasmext_store.h"
#include "wasmext_host.h"
#include "wasmext_instance.h"
#include "wasmext_table.h"
int main(void) { return 0; }
