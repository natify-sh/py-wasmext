/* The C API of the WebAssembly module engine, made by wasmext: do not edit. No Python in it; any host language that can call C can use the library. */
#ifndef WASMEXT_API_ENGINE_H
#define WASMEXT_API_ENGINE_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
#ifndef WASMEXT_API
#if defined(_WIN32) && defined(WASMEXT_BUILDING)
#define WASMEXT_API __declspec(dllexport)
#elif defined(_WIN32)
#define WASMEXT_API __declspec(dllimport)
#else
#define WASMEXT_API __attribute__((visibility("default")))
#endif
#endif

/* The codes that a call answers (0 is success): those of the runtime of wasm2c (see the _trap_message of the module) and these. */
#define ENGINE_TRAP_HOST 0x7000  /* a host function answered with a failure; its error is the host's */
#define ENGINE_TRAP_NO_MEMORY 0x7001
#define ENGINE_TRAP_ENDED 0x7002  /* the WASI program is over: engine_wasi_end says how */
#define ENGINE_LINK_ERROR 0x7003  /* an import was not set before engine_instantiate */
#define ENGINE_HOOK_TRAP 0x10000  /* what a hook of WASI answers for a failure of its own (a positive number below it is an errno of WASI) */

typedef struct engine_t engine_t;

#define ENGINE_TRAP_LINKED 0x20000  /* a function that is the export of another instance answers a trap of that instance as this + its code: the caller traps with the code */
/* What an instance gives of an export for another to import (a function, a memory or a global): the record of wasmext, private and versioned; it is passed by
   pointer from the exporter (`_export_find`) to the importer (`_link_*`). `owner` is whatever keeps the exporter alive (the host's own business). */
typedef struct {
    uint32_t size, version, kind, type, flags;
    void *owner, *address, *instance;
    const char *signature;
    uint32_t runtime;
} engine_export;

/* The configuration of WASI (every field may be 0): arguments, `NAME=value` strings, directories as `host::guest` (the guest name is `/` when it is left out),
   and hooks for the standard streams, the clocks, the random bytes and sleeping: a hook answers 0, an errno of WASI, or HOOK_TRAP; without one the core uses descriptors 0, 1 and 2 and the system. */
typedef struct {
    const char *const *args; size_t nargs;  /* NULL: the name of the module; not NULL with nargs 0: no arguments */
    const char *const *env; size_t nenv;
    const char *const *dirs; size_t ndirs;
    const int *dirs_readonly;  /* NULL, or a flag for each dir: 1 for a directory that the program cannot change */
    int (*stdin_read)(void *user, uint8_t *buf, size_t cap, size_t *got);
    int (*stdout_write)(void *user, int fd, const uint8_t *buf, size_t n);  /* fd 1 or 2 */
    int (*clock)(void *user, uint32_t id, uint64_t *ns);  /* id: the clock of WASI (0 realtime, 1 monotonic, 2 and 3 of the process and the thread); without it the system's */
    int (*random)(void *user, uint8_t *buf, size_t n);  /* without it the system's source */
    int (*sleep)(void *user, uint64_t ns);  /* without it the core sleeps in slices of 100 ms */
    void *user;
} engine_config;

/* A new instance (imports not set, not instantiated); NULL with `*error` (an errno) when it cannot be made. */
WASMEXT_API engine_t *engine_new(const engine_config *config, int *error);
WASMEXT_API void engine_free(engine_t *m);
/* The first call into the library from a thread sets that thread up for traps (the runtime of wasm2c does it for the thread that made the instance); a host thread that is going away may call this to give that back. */
WASMEXT_API void engine_thread_free(void);
WASMEXT_API int engine_instantiate(engine_t *m);  /* 0, or the code of a trap (or ENGINE_LINK_ERROR) */
WASMEXT_API const char *engine_trap_message(int code);
WASMEXT_API int engine_trap_is_exception(int code);  /* whether a code is that of an exception of WebAssembly that nothing caught */
/* How the WASI program ended: 0 not yet, 1 proc_exit (`*value` is the code), 2 proc_raise (the signal), 3 a trap of a command. */
WASMEXT_API int engine_wasi_end(engine_t *m, uint32_t *value);

/* the import env.log: set it before engine_instantiate; a failure of the function is `*trapped` nonzero (and its own error, kept by the host) */
typedef int32_t (*engine_import0_fn)(void *user, int32_t a0, int *trapped);
WASMEXT_API void engine_set_import0(engine_t *m, engine_import0_fn function, void *user);

/* the import env.log: the function of another instance (its record from `_export_find`); 0, or 1 with the message of the LinkError */
WASMEXT_API int engine_link_import0(engine_t *m, const engine_export *e, char *message, size_t capacity);

/* An exception of WebAssembly that nothing caught ends a call with the trap code of the runtime for it (see engine_trap_message); then the tag (its index in the module)
   and the values, as the last call left them. */
typedef struct { int type; union { int32_t i32; int64_t i64; float f32; double f64; } as; } engine_value;  /* type: 0x7F i32, 0x7E i64, 0x7D f32, 0x7C f64 */
WASMEXT_API int engine_exception(engine_t *m, int *tag, engine_value *values, size_t capacity, size_t *count);
/* add(i32, i32) -> i32: 0, or the code of the trap */
WASMEXT_API int engine_add(engine_t *m, int32_t a0, int32_t a1, int32_t *r0);
/* twice(i32) -> i32, i32: 0, or the code of the trap */
WASMEXT_API int engine_twice(engine_t *m, int32_t a0, int32_t *r0, int32_t *r1);
/* call_log(i32) -> i32: 0, or the code of the trap */
WASMEXT_API int engine_call_log(engine_t *m, int32_t a0, int32_t *r0);
/* boom(i32) -> nothing: 0, or the code of the trap */
WASMEXT_API int engine_boom(engine_t *m, int32_t a0);
/* trap() -> nothing: 0, or the code of the trap */
WASMEXT_API int engine_trap(engine_t *m);
/* the memory mem: its bytes (valid until the module grows it) and their number */
WASMEXT_API uint8_t *engine_memory_mem(engine_t *m, size_t *size);
/* pin (1) or unpin (0) the memory mem: while it is pinned, `memory.grow` answers -1 where the runtime moves a memory that grows (no guard pages, memory64), so the bytes stay where they are; pins count. */
WASMEXT_API void engine_memory_mem_pin(engine_t *m, int pin);

/* The record of the export `name` for another instance to import (`engine_link_*` of the other library): 0, or 1 when there is no such export. `owner` is kept in the
   record, for whoever has to keep this instance alive. The record is valid as long as this instance is. */
WASMEXT_API int engine_export_find(engine_t *m, const char *name, void *owner, engine_export *out);

#ifdef __cplusplus
}
#endif
#endif
