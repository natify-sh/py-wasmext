/* The glue that is the same for every module: the traps and how a call of WebAssembly code is guarded, and the fingerprint of the layout
   of the structs of the wasm2c runtime that two extensions share. No Python.h here (nor in the <name>_glue.h that includes it): a
   host that is not Python (the shared library, the executable) uses these files as they are. See "Design: C first" in DESIGN.md.

   A function of the glue that the module exports is called as `result f(void *instance, parameters..., int *trapped)`: `*trapped` is 0,
   or the code of the trap (a WASM_RT_TRAP_* of the runtime, or one of those below) and the result is then undefined. A host function that
   the module imports has the same form, but there `*trapped` is only nonzero or not: the host keeps what it needs to report the error
   (Python keeps its exception), and the frames of the module are unwound with WASMEXT_TRAP_HOST, as the protocol of errors says. */
#ifndef WASMEXT_GLUE_H
#define WASMEXT_GLUE_H

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "wasm-rt.h"
#include "wasm-rt-impl.h"
#include "wasm-rt-exceptions.h"
#ifndef _WIN32
#include <signal.h>
#endif

/* the codes of traps that are not the runtime's */
#define WASMEXT_TRAP_HOST ((wasm_rt_trap_t)0x7000)       /* a host function failed and kept its error (Python: the exception is already set) */
#define WASMEXT_TRAP_NO_MEMORY ((wasm_rt_trap_t)0x7001)  /* the copy of the runtime that wasmext brings cannot allocate a memory */
#define WASMEXT_TRAP_ENDED ((wasm_rt_trap_t)0x7002)      /* the call ended the WASI program (proc_exit, proc_raise): `wasi_end` says how; the instance can be called again */
#define WASMEXT_TRAP_CLOSED ((wasm_rt_trap_t)0x7004)     /* the store of the instance is closed: nothing is called any more (0x7003 is the library's LINK_ERROR) */
/* A host function that is the export of another instance answers a trap of that instance as WASMEXT_TRAP_LINKED + its code: the caller then traps with
   that code (the trap goes through, as in WebAssembly); any other nonzero answer is a failure of the host (WASMEXT_TRAP_HOST). */
#define WASMEXT_TRAP_LINKED 0x20000
#define WASMEXT_TRAP_OF(TRAPPED) \
    ((TRAPPED) >= WASMEXT_TRAP_LINKED ? (wasm_rt_trap_t)((TRAPPED) - WASMEXT_TRAP_LINKED) : WASMEXT_TRAP_HOST)

/* How a WASI program ended, as `<name>_wasi_end` answers it: by proc_exit / wasi:cli/exit (the code is the guest's `exit_code`) or by proc_raise (the number of the signal). */
#define WASMEXT_END_NONE 0
#define WASMEXT_END_EXIT 1
#define WASMEXT_END_SIGNAL 2

/* Which signals of proc_raise (WASI 0.1, numbers 1 to 30) end the program. fusedwasi does not decide it: the guest has a hook `signal`, and this is wasmext's answer, as a process would
   behave: a signal that is ignored when nothing handles it (the child, continue, urgent data, the size of the window) or that stops a process (stop, and the ones of a terminal)
   is answered with success and the program goes on; any other ends it. */
static inline int wasmext_signal_ends(uint32_t number) { return !(number == 0 || (number >= 16 && number <= 22) || number == 27); }

/* A fingerprint of the layout of the structs of the wasm2c runtime that modules share, for the maintainers: it is in every record and in the stack of traps, and
   it changes by itself when a new WABT changes a layout. It is not a gate of the link of an export (the layout is checked when a module is built, WASMEXT_LAYOUT);
   only the stack of traps compares it, because the buffer of a jump (wasm_rt_jmp_buf) is a type of the platform that a check by relations cannot pin. */
#ifndef WASMEXT_RUNTIME
#define WASMEXT_RUNTIME ((uint32_t)(sizeof(wasm_rt_memory_t) * 1000003u ^ offsetof(wasm_rt_memory_t, data) * 8191u ^ \
    offsetof(wasm_rt_memory_t, pages) * 131u ^ offsetof(wasm_rt_memory_t, size) * 17u ^ offsetof(wasm_rt_memory_t, is64) * 7u ^ \
    sizeof(wasm_rt_funcref_table_t) * 65537u ^ offsetof(wasm_rt_funcref_table_t, data) * 4099u ^ \
    offsetof(wasm_rt_funcref_table_t, max_size) * 257u ^ offsetof(wasm_rt_funcref_table_t, size) * 31u ^ \
    sizeof(wasm_rt_funcref_t) * 524309u ^ offsetof(wasm_rt_funcref_t, func_type) * 2053u ^ offsetof(wasm_rt_funcref_t, func) * 67u ^ \
    offsetof(wasm_rt_funcref_t, func_tailcallee) * 11u ^ offsetof(wasm_rt_funcref_t, module_instance) * 5u ^ \
    sizeof(wasm_rt_jmp_buf) * 3u))
#endif

/* The layout of the structs of the wasm2c runtime that modules share, checked when a module is BUILT (not when it is linked): a module reads a memory, a table or
   a funcref that another one made, through its own copy of these structs, so the two must be the same. Every member, its size and its place are checked (the
   next member follows the one before it with at most the padding of 8 bytes), so a runtime that has another member, or none of one (WABT `main` has a memory
   of 48 bytes where 1.0.42 has 56) fails here, with the name of the check in the message of the compiler, whatever the compiler is. The check is by relations, not
   by numbers: it holds for a 32-bit and a 64-bit platform alike. WASMEXT_NO_LAYOUT_CHECK turns it off (for a test that builds with another runtime on purpose). */
#ifndef WASMEXT_NO_LAYOUT_CHECK
#define WASMEXT_MSIZE(T, m) sizeof(((T *)0)->m)
#define WASMEXT_FOLLOWS(T, a, b) \
    (offsetof(T, b) >= offsetof(T, a) + WASMEXT_MSIZE(T, a) && offsetof(T, b) < offsetof(T, a) + WASMEXT_MSIZE(T, a) + 8)
#define WASMEXT_LAYOUT(name, cond) typedef char wasmext_layout_##name[(cond) ? 1 : -1]
WASMEXT_LAYOUT(memory_order,
    offsetof(wasm_rt_memory_t, data) == 0 && WASMEXT_FOLLOWS(wasm_rt_memory_t, data, data_end) && WASMEXT_FOLLOWS(wasm_rt_memory_t, data_end, page_size) &&
    WASMEXT_FOLLOWS(wasm_rt_memory_t, page_size, pages) && WASMEXT_FOLLOWS(wasm_rt_memory_t, pages, max_pages) &&
    WASMEXT_FOLLOWS(wasm_rt_memory_t, max_pages, size) && WASMEXT_FOLLOWS(wasm_rt_memory_t, size, is64));
WASMEXT_LAYOUT(memory_types,
    WASMEXT_MSIZE(wasm_rt_memory_t, data) == sizeof(void *) && WASMEXT_MSIZE(wasm_rt_memory_t, data_end) == sizeof(void *) &&
    WASMEXT_MSIZE(wasm_rt_memory_t, page_size) == 4 && WASMEXT_MSIZE(wasm_rt_memory_t, pages) == 8 && WASMEXT_MSIZE(wasm_rt_memory_t, max_pages) == 8 &&
    WASMEXT_MSIZE(wasm_rt_memory_t, size) == 8 && WASMEXT_MSIZE(wasm_rt_memory_t, is64) == 1);
WASMEXT_LAYOUT(table_order,
    offsetof(wasm_rt_funcref_table_t, data) == 0 && WASMEXT_FOLLOWS(wasm_rt_funcref_table_t, data, max_size) &&
    WASMEXT_FOLLOWS(wasm_rt_funcref_table_t, max_size, size));
WASMEXT_LAYOUT(table_types,
    WASMEXT_MSIZE(wasm_rt_funcref_table_t, data) == sizeof(void *) && WASMEXT_MSIZE(wasm_rt_funcref_table_t, max_size) == 4 &&
    WASMEXT_MSIZE(wasm_rt_funcref_table_t, size) == 4);
WASMEXT_LAYOUT(funcref_order,
    offsetof(wasm_rt_funcref_t, func_type) == 0 && WASMEXT_FOLLOWS(wasm_rt_funcref_t, func_type, func) &&
    WASMEXT_FOLLOWS(wasm_rt_funcref_t, func, func_tailcallee) && WASMEXT_FOLLOWS(wasm_rt_funcref_t, func_tailcallee, module_instance));
WASMEXT_LAYOUT(funcref_types,
    WASMEXT_MSIZE(wasm_rt_funcref_t, func_type) == sizeof(void *) && WASMEXT_MSIZE(wasm_rt_funcref_t, func) == sizeof(void (*)(void)) &&
    WASMEXT_MSIZE(wasm_rt_funcref_t, module_instance) == sizeof(void *));
#endif

/* The ABI of wasmext: this record, the capsule that carries it, and the C that every module is built with (this directory). One number made as
   PY_VERSION_HEX of CPython, 0xXXYYZZLS (docs/abi_policy.md): XX (x) goes up when something a module already built relies on is broken, YY (y) when something
   is added that breaks nothing, ZZ (z) for fixes only; L is the level (0xA alpha, 0xB beta, 0xC release candidate, 0xF final) and S the serial of the
   pre-release. Modules link when their x is the same. It is not the version of the package, but at a release they agree in the numeric part. */
#define WASMEXT_ABI_X 0
#define WASMEXT_ABI_Y 0
#define WASMEXT_ABI_Z 1
#define WASMEXT_ABI_LS 0xA3
#define WASMEXT_ABI ((uint32_t)(((uint32_t)WASMEXT_ABI_X << 24) | ((uint32_t)WASMEXT_ABI_Y << 16) | ((uint32_t)WASMEXT_ABI_Z << 8) | WASMEXT_ABI_LS))
#define WASMEXT_VERSION_X(V) ((uint32_t)(V) >> 24)
#define WASMEXT_VERSION_Y(V) (((uint32_t)(V) >> 16) & 0xFFu)
#define WASMEXT_VERSION_Z(V) (((uint32_t)(V) >> 8) & 0xFFu)
#define WASMEXT_STRING_(X) #X
#define WASMEXT_STRING(X) WASMEXT_STRING_(X)

/* The version in which each part of a record appeared: the floor of a record (the lowest version of a reader that can use it) is the highest of the parts
   it has. The capsule names have only x: a name is compared for equality, so it cannot say "at least". */
#define WASMEXT_SINCE_RECORD 0x000001A1u   /* a function, a memory, a global */
#define WASMEXT_SINCE_TABLE 0x000001A1u    /* a table */
#define WASMEXT_SINCE_FUNCREF 0x000001A1u  /* the field funcref: a function that may be put in a table */

/* What another instance reads of an export of this one (a function, a memory or a global): a record that a host passes from the exporter to the
   importer. It is a public interface, versioned by WASMEXT_ABI: a reader checks `abi` (the same x), `floor` (its own version is not below it), and `size`
   (wasmext_export_ok) before it reads a field. The extension for CPython wraps it in a capsule named WASMEXT_EXPORT (x is in the name, so a module
   of another x is not seen); any other host passes the pointer. */
#define WASMEXT_EXPORT "wasmext.export.v" WASMEXT_STRING(WASMEXT_ABI_X)
enum { WASMEXT_FUNC = 0, WASMEXT_TABLE = 1, WASMEXT_MEMORY = 2, WASMEXT_GLOBAL = 3 };
typedef struct {
    uint32_t size;      /* sizeof of this struct for the host that made it */
    uint32_t abi;       /* WASMEXT_ABI of the host that made it: what the exporter provides */
    uint32_t kind;      /* WASMEXT_FUNC, ... */
    uint32_t type;      /* a global: its value type as numbered in the binary format (0x7F is i32); a memory: sizeof(wasm_rt_memory_t) */
    uint32_t flags;     /* bit 0: the global is mutable; bit 1: the memory is 64-bit; bit 2: it is checked with guard pages; bit 3: the function can be called with no Python (no GIL); bit 4: the function is of a module that shares tables (it is built with the stack of entries for traps), so it may be put in a table */
    void *owner;        /* what keeps the exporter alive (Python: the instance, a PyObject *): a reader that keeps the address keeps a reference to it */
    void *address;      /* a global: the pointer to its value; a memory: the wasm_rt_memory_t; a function: the function to call (see below) */
    void *instance;     /* a function: the first argument of that call */
    const char *signature;  /* a function: the parameters, '>', the results (i j f d o) */
    uint32_t runtime;   /* WASMEXT_RUNTIME of the host that made it: the layout of the structs of the wasm2c runtime */
    const void *funcref;  /* a function: the wasm_rt_funcref_t of it (its type, the function, the instance), to put in a table; valid while `owner` is; NULL for the others (added at the end: `size` tells a reader) */
    uint32_t floor;     /* the lowest WASMEXT_ABI of a reader that can use this record (wasmext_export_seal): a reader below it refuses */
    const void *store;  /* the store of the exporter, opaque (added at the end: `size` tells a reader): instances are linked inside one store, as in Wasmtime, because the store frees its members when it is closed; NULL from a host that does not know it */
} wasmext_export;
/* a function is called as `result f(void *instance, parameters..., int *trapped)`: a trap is reported through `trapped` (its code: see above),
   and the result is then undefined; it catches the traps of its own module. */

/* The record is complete when the fields are filled that it has: its floor is the highest version of what it has. Call it last. */
static inline void wasmext_export_seal(wasmext_export *e) {
    uint32_t floor_ = WASMEXT_SINCE_RECORD;
    if (e->kind == WASMEXT_TABLE && WASMEXT_SINCE_TABLE > floor_) floor_ = WASMEXT_SINCE_TABLE;
    if (e->funcref != NULL && WASMEXT_SINCE_FUNCREF > floor_) floor_ = WASMEXT_SINCE_FUNCREF;
    e->floor = floor_;
}

/* Whether this reader can use the record: the same x, a reader not below the floor of the record, the fields of the first version present (a field added
   later is read after a look at `size`). The layout of the runtime of wasm2c is not compared here: it is checked when a module is built (WASMEXT_LAYOUT). */
#define WASMEXT_EXPORT_BASE (offsetof(wasmext_export, floor) + sizeof(uint32_t))
static inline int wasmext_export_ok(const wasmext_export *e) {
    return WASMEXT_VERSION_X(e->abi) == WASMEXT_ABI_X && e->size >= WASMEXT_EXPORT_BASE && WASMEXT_ABI >= e->floor;
}

/* the message of a link that fails: 1 */
static inline int wasmext_link_fail(char *msg, size_t cap, const char *text) {
    snprintf(msg, cap, "%s", text);
    return 1;
}

/* A table of `funcref` that no module owns: the Table of an extension, of a wrapper for ctypes or of a library. In the specification a table belongs to
   the store and an instance only holds its address; wasm2c puts the table of a module into the structure of the instance, but an import is only a pointer to
   a `wasm_rt_funcref_table_t`, so a table made here is imported by a module as the table of another module is. These work over the runtime of the module
   that has them (the structure is the same in every copy: WASMEXT_RUNTIME). `maximum` is WASMEXT_TABLE_NO_MAXIMUM when there is none. */
#define WASMEXT_TABLE_NO_MAXIMUM 0xFFFFFFFFu

/* 0 on success; 1 if the table cannot be had (the runtime does not check its allocation: 1.0.42 leaves a NULL, later releases abort()) */
static inline int wasmext_table_new(wasm_rt_funcref_table_t *t, uint32_t initial, uint32_t maximum) {
    wasm_rt_allocate_funcref_table(t, initial, maximum);
    if (initial > 0 && t->data == NULL) {
        t->size = 0;
        return 1;
    }
    return 0;
}

static inline void wasmext_table_free(wasm_rt_funcref_table_t *t) {
    wasm_rt_free_funcref_table(t);
    t->data = NULL;
    t->size = 0;
}

/* the new elements are null; the previous size, or -1 when the table cannot grow that much (its maximum, or memory) */
static inline int64_t wasmext_table_grow(wasm_rt_funcref_table_t *t, uint32_t delta) {
    wasm_rt_funcref_t null_;
    memset(&null_, 0, sizeof null_);
    uint32_t old_ = wasm_rt_grow_funcref_table(t, delta, null_);
    return old_ == 0xFFFFFFFFu ? -1 : (int64_t)old_;
}

/* the record of a table that is not a module's: `owner` is whatever keeps it alive (for Python, the Table), `instance` is none */
static inline void wasmext_table_export(wasmext_export *e, wasm_rt_funcref_table_t *t, void *owner) {
    memset(e, 0, sizeof *e);
    e->size = sizeof *e;
    e->abi = WASMEXT_ABI;
    e->kind = WASMEXT_TABLE;
    e->type = (uint32_t)sizeof(wasm_rt_funcref_table_t);
    e->owner = owner;
    e->address = t;
    e->runtime = WASMEXT_RUNTIME;
    wasmext_export_seal(e);
}

/* the record of a function that is not an export of a module any more but an element of a table (the Function of Python): the funcref is what Table.set puts in a slot */
static inline void wasmext_function_export(wasmext_export *e, const wasm_rt_funcref_t *f, void *owner) {
    memset(e, 0, sizeof *e);
    e->size = sizeof *e;
    e->abi = WASMEXT_ABI;
    e->kind = WASMEXT_FUNC;
    e->flags = 16u;
    e->owner = owner;
    e->instance = f->module_instance;
    e->runtime = WASMEXT_RUNTIME;
    e->funcref = f;
    wasmext_export_seal(e);
}

/* a value of WebAssembly that is not a parameter or a result of a call: the values of an exception that nothing caught (`type` is the
   number of the type in the binary format: 0x7F i32, 0x7E i64, 0x7D f32, 0x7C f64, 0x7B v128, whose 16 bytes are in `o`) */
typedef struct {
    uint8_t type;
    union {
        uint32_t i;
        uint64_t j;
        float f;
        double d;
        uint8_t o[16];
    } as;
} wasmext_value;

/* a trap from a signal handler (an access past the guard pages) leaves the signal blocked: sigsetjmp saves no mask, for speed */
static inline void wasmext_unblock_fault_signals(void) {
#ifndef _WIN32
    sigset_t set_;
    sigemptyset(&set_);
    sigaddset(&set_, SIGSEGV);
    sigaddset(&set_, SIGBUS);
    pthread_sigmask(SIG_UNBLOCK, &set_, NULL);
#endif
}

#ifdef WASMEXT_TRAP_HANDLER
/* Modules that share a table. A function in the table of one module can belong to another, and a trap in it (WASM_RT_TRAP_*) must come back to the call
   that entered WebAssembly code, whichever module's runtime raises it: each extension has its own copy of the runtime of wasm2c, and so its own
   `g_wasm_rt_jmp_buf`, which only a call into that module sets. So such a module is built with WASM_RT_TRAP_HANDLER (`WASMEXT_TRAP_HANDLER` here is the name of the
   function that the runtime calls instead of `longjmp`), and every call into it pushes an entry on one stack that all of these modules share (one stack for each
   thread), and the handler jumps to the innermost entry. An exception that nothing catches goes to the "unwind target" of the copy of the runtime that throws:
   an entry sets the unwind target of every copy that has joined. The stack and the list of copies belong to the first module that is loaded (a host
   gives the others its `wasmext_traps`; see the Python layer for how it is found), and every other module only calls it. */
typedef struct wasmext_entry {
    wasm_rt_jmp_buf buf;
    struct wasmext_entry *prev;
} wasmext_entry;

#define WASMEXT_TRAPS "wasmext.traps.v" WASMEXT_STRING(WASMEXT_ABI_X)
typedef struct {
    uint32_t size;     /* sizeof of this struct for the module that made it */
    uint32_t runtime;  /* WASMEXT_RUNTIME of that module: a stack is shared only by modules of the same layout of the runtime and of the jump buffer */
    void (*enter)(wasmext_entry *e);   /* push `e`, and make its buffer the unwind target of every copy of the runtime */
    void (*leave)(wasmext_entry *e);   /* pop `e` (when the call is over, or has come back by a trap), and put the unwind targets back */
    void (*trap)(wasm_rt_trap_t code); /* does not return: jump to the innermost entry with `code` */
    int (*join)(void (*set_unwind_target)(WASM_RT_UNWIND_TARGET *)); /* a copy of the runtime asks to be given the unwind targets: 0, or 1 if there is no room */
} wasmext_traps;

/* The implementation. Every module has it, but only the one that the host picks to publish is used (its function pointers are what the others call): the
   state it keeps (the top of the stack of the thread, the copies of the runtime) is in that module alone. */
#define WASMEXT_MAX_RUNTIMES 64
static WASM_RT_THREAD_LOCAL wasmext_entry *wasmext_top_;
static void (*wasmext_unwinders_[WASMEXT_MAX_RUNTIMES])(WASM_RT_UNWIND_TARGET *);
static volatile int wasmext_unwinder_count_;

static inline int wasmext_unwinders_n_(void) {
#if defined(__GNUC__) || defined(__clang__)
    return __atomic_load_n(&wasmext_unwinder_count_, __ATOMIC_ACQUIRE);
#else
    return wasmext_unwinder_count_;
#endif
}
static void wasmext_traps_enter_(wasmext_entry *e) {
    e->prev = wasmext_top_;
    wasmext_top_ = e;
    for (int i = 0, n = wasmext_unwinders_n_(); i < n; i++) wasmext_unwinders_[i](&e->buf);
}
static void wasmext_traps_leave_(wasmext_entry *e) {
    wasmext_top_ = e->prev;
    for (int i = 0, n = wasmext_unwinders_n_(); i < n; i++) wasmext_unwinders_[i](e->prev != NULL ? &e->prev->buf : NULL);
}
static void wasmext_traps_trap_(wasm_rt_trap_t code) {
    if (wasmext_top_ == NULL) {
        fputs("wasmext: WebAssembly code trapped outside any call into a module\n", stderr);
        abort();
    }
    WASM_RT_LONGJMP(wasmext_top_->buf, code);
}
static int wasmext_traps_join_(void (*set_unwind_target)(WASM_RT_UNWIND_TARGET *)) {
    int n = wasmext_unwinders_n_();
    for (int i = 0; i < n; i++)
        if (wasmext_unwinders_[i] == set_unwind_target) return 0;
    if (n >= WASMEXT_MAX_RUNTIMES) return 1;
    wasmext_unwinders_[n] = set_unwind_target;
#if defined(__GNUC__) || defined(__clang__)
    __atomic_store_n(&wasmext_unwinder_count_, n + 1, __ATOMIC_RELEASE);  /* the entry is written before the count that shows it */
#else
    wasmext_unwinder_count_ = n + 1;
#endif
    return 0;
}
static wasmext_traps wasmext_traps_own_ = {
    sizeof(wasmext_traps), WASMEXT_RUNTIME, wasmext_traps_enter_, wasmext_traps_leave_, wasmext_traps_trap_, wasmext_traps_join_};

/* the stack that this module uses: its own, or the one it was given (the host sets it before the first call, with the module joined to it) */
static const wasmext_traps *wasmext_traps_ = &wasmext_traps_own_;
static inline int wasmext_traps_use(const wasmext_traps *shared) {
    if (shared->size < sizeof(wasmext_traps) || shared->runtime != WASMEXT_RUNTIME) return 1;
    if (shared->join(wasm_rt_set_unwind_target)) return 1;
    wasmext_traps_ = shared;
    return 0;
}
#endif

/* How a call into WebAssembly code marks where a trap comes back to. `wasm_rt_try` is `sigsetjmp(buf, 0)`: it saves no signal mask, which is fast. On macOS
   that is wrong when the trap comes from a signal handler running on the alternate stack of the runtime (an access past the guard pages, the stack running
   out): the `siglongjmp` out of the handler leaves the thread flagged as being on the alternate stack (WABT #2654, golang/go#44501), after which the
   `sigaltstack` of the next `wasm_rt_init` fails (the process aborts) and the next stack overflow is a SIGILL. The runtime itself uses `sigsetjmp(buf, 1)`
   (WASM_RT_SETJMP) for traps for that reason, so where a handler of signals is installed on macOS the entry does the same; elsewhere nothing changes. */
#if defined(__APPLE__) && WASM_RT_INSTALL_SIGNAL_HANDLER
#define WASMEXT_TRY(BUF) WASM_RT_SETJMP(BUF)
#else
#define WASMEXT_TRY(BUF) wasm_rt_try(BUF)
#endif

/* the unwind target is where a `throw` that no `try` of the module catches goes: the trap of this call */
#define WASMEXT_SET_UP_TRAP_() \
    (WASM_RT_SAVE_STACK_DEPTH(), wasm_rt_set_unwind_target(&g_wasm_rt_jmp_buf), (wasm_rt_trap_t)WASMEXT_TRY(g_wasm_rt_jmp_buf))

/* A call of WebAssembly code: `WASMEXT_ENTER(CODE, FAIL)` makes the variable CODE (0 the first time, the trap when the code comes back
   by a trap) and runs FAIL then; `WASMEXT_LEAVE()` after the call. A module that imports something can be called again from inside the call
   (a function of the host can call it): the buffer of the outer call is put back afterwards. A module that imports nothing cannot, and
   saves the copy. */
#define WASMEXT_ENTER_REENTRANT(CODE, FAIL) \
    wasm_rt_jmp_buf saved_jmp_; \
    memcpy(&saved_jmp_, &g_wasm_rt_jmp_buf, sizeof saved_jmp_); \
    wasm_rt_trap_t CODE = WASMEXT_SET_UP_TRAP_(); \
    if (CODE) { \
        wasmext_unblock_fault_signals(); \
        memcpy(&g_wasm_rt_jmp_buf, &saved_jmp_, sizeof saved_jmp_); \
        FAIL; \
    }
#define WASMEXT_LEAVE_REENTRANT() memcpy(&g_wasm_rt_jmp_buf, &saved_jmp_, sizeof saved_jmp_)
#define WASMEXT_ENTER_PLAIN(CODE, FAIL) \
    wasm_rt_trap_t CODE = WASMEXT_SET_UP_TRAP_(); \
    if (CODE) { wasmext_unblock_fault_signals(); FAIL; }
#define WASMEXT_LEAVE_PLAIN() ((void)0)
#ifdef WASMEXT_TRAP_HANDLER
/* The same for a module that shares tables (see above): the entry is on the stack of the call, so there is nothing to save and put back. */
#define WASMEXT_ENTER_SHARED(CODE, FAIL) \
    wasmext_entry entry_; \
    wasmext_traps_->enter(&entry_); \
    wasm_rt_trap_t CODE = (WASM_RT_SAVE_STACK_DEPTH(), (wasm_rt_trap_t)WASMEXT_TRY(entry_.buf)); \
    if (CODE) { \
        wasmext_traps_->leave(&entry_); \
        wasmext_unblock_fault_signals(); \
        FAIL; \
    }
#define WASMEXT_LEAVE_SHARED() wasmext_traps_->leave(&entry_)
#endif

#endif
