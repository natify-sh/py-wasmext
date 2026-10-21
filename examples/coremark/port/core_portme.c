/* The CoreMark port for a WebAssembly module with no libc (see core_portme.h). */
#include "coremark.h"

#define IMPORT(name) __attribute__((import_module("wiring"), import_name(name)))
IMPORT("millis") extern ee_u32 host_millis(void);
IMPORT("print") extern void host_print(const char *bytes, int length);

#if VALIDATION_RUN
volatile ee_s32 seed1_volatile = 0x3415;
volatile ee_s32 seed2_volatile = 0x3415;
volatile ee_s32 seed3_volatile = 0x66;
#endif
#if PERFORMANCE_RUN
volatile ee_s32 seed1_volatile = 0x0;
volatile ee_s32 seed2_volatile = 0x0;
volatile ee_s32 seed3_volatile = 0x66;
#endif
#if PROFILE_RUN
volatile ee_s32 seed1_volatile = 0x8;
volatile ee_s32 seed2_volatile = 0x8;
volatile ee_s32 seed3_volatile = 0x8;
#endif
volatile ee_s32 seed4_volatile = ITERATIONS;
volatile ee_s32 seed5_volatile = 0;

static CORETIMETYPE start_time_val, stop_time_val;

void start_time(void) { start_time_val = host_millis(); }
void stop_time(void) { stop_time_val = host_millis(); }
CORE_TICKS get_time(void) { return stop_time_val - start_time_val; }
secs_ret time_in_secs(CORE_TICKS ticks) { return ((secs_ret)ticks) / 1000.0; }

ee_u32 default_num_contexts = 1;

void portable_init(core_portable *p, int *argc, char *argv[]) {
    (void)argc;
    (void)argv;
    p->portable_id = 1;
}
void portable_fini(core_portable *p) { p->portable_id = 0; }

/* ee_printf (barebones/ee_printf.c) sends one char at a time: a line goes to the host at once. */
static char line[256];
static int length;
void uart_send_char(char c) {
    line[length++] = c;
    if (c == '\n' || length == (int)sizeof line) {
        host_print(line, length);
        length = 0;
    }
}

/* The entry of the module: the benchmark, once. */
#undef main
extern int coremark_main(void);
__attribute__((export_name("setup"))) void setup(void) { coremark_main(); }

double modf(double x, double *integral) {
    double whole = __builtin_trunc(x);
    *integral = whole;
    return x - whole;
}
