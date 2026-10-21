/* The CoreMark port for a WebAssembly module with no libc: wasm32-freestanding, built by ../build_wasm.py.
   Derived from the `barebones` port of https://github.com/eembc/coremark (Apache-2.0). The module imports the two
   functions of the host: wiring.millis (the clock) and wiring.print (bytes to the host's stdout). */
#ifndef CORE_PORTME_H
#define CORE_PORTME_H

#define HAS_FLOAT 1
#define HAS_TIME_H 0
#define USE_CLOCK 0
#define HAS_STDIO 0
#define HAS_PRINTF 0

#define COMPILER_VERSION "zig cc (clang), wasm32"
#define COMPILER_FLAGS "-O3"
#define MEM_LOCATION "STATIC"

typedef signed short ee_s16;
typedef unsigned short ee_u16;
typedef signed int ee_s32;
typedef double ee_f32;
typedef unsigned char ee_u8;
typedef unsigned int ee_u32;
typedef ee_u32 ee_ptr_int;
typedef unsigned int ee_size_t;
#define NULL ((void *)0)

#define align_mem(x) (void *)(4 + (((ee_ptr_int)(x)-1) & ~3))

#define CORETIMETYPE ee_u32
typedef ee_u32 CORE_TICKS;

#define SEED_METHOD SEED_VOLATILE
#define MEM_METHOD MEM_STATIC
#define MULTITHREAD 1
#define USE_PTHREAD 0
#define USE_FORK 0
#define USE_SOCKET 0
#define MAIN_HAS_NOARGC 1
#define MAIN_HAS_NORETURN 0

/* `main` is called by the exported `setup` (port.c): the name of the module's own entry is free. */
#define main coremark_main

extern ee_u32 default_num_contexts;
int ee_printf(const char *fmt, ...);
void uart_send_char(char c);

typedef struct CORE_PORTABLE_S {
    ee_u8 portable_id;
} core_portable;

void portable_init(core_portable *p, int *argc, char *argv[]);
void portable_fini(core_portable *p);

#if !defined(PROFILE_RUN) && !defined(PERFORMANCE_RUN) && !defined(VALIDATION_RUN)
#if (TOTAL_DATA_SIZE == 1200)
#define PROFILE_RUN 1
#elif (TOTAL_DATA_SIZE == 2000)
#define PERFORMANCE_RUN 1
#else
#define VALIDATION_RUN 1
#endif
#endif

#endif
