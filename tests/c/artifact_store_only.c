/* A file of an artifact that includes wasmext_store.h alone: its stores carry the identity of the store without the instance and the runtime, which a full copy must not take for its own. */
#include "wasmext_store.h"

wasmext_store *artifact_so_new(void) { return wasmext_store_new(); }
int artifact_so_attach(wasmext_store *s, char *why, size_t cap) { return wasmext_store_attach(s, why, cap); }
