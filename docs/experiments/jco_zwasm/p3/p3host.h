/* Minimal WASI 0.3 host for a wasm2c-compiled, sync-lifted (wasi-libc style) command: streams, futures, waitable sets,
 * stdio, clocks. One task, one component instance, no threads. A sketch to test feasibility, not a complete host. */
#pragma once
#include <stdint.h>
#include "wasm-rt.h"
typedef uint8_t u8; typedef uint32_t u32; typedef uint64_t u64;
void p3_set_memory(wasm_rt_memory_t *(*get)(void));
u64 p3_stream_new(void); void p3_stream_drop_readable(u32); void p3_stream_drop_writable(u32);
u32 p3_stream_write(u32, u32, u32); u32 p3_stream_read(u32, u32, u32); u32 p3_stream_cancel(u32);
u32 p3_future_read(u32, u32); void p3_future_drop_readable(u32);
u32 p3_ws_new(void); void p3_ws_join(u32, u32); void p3_ws_drop(u32); u32 p3_ws_wait(u32, u32); u32 p3_ws_poll(u32, u32);
u32 p3_subtask_cancel(u32); void p3_noop1(u32);
u32 p3_get_sp(void); void p3_set_sp(u32); u32 p3_get_tls(void); void p3_set_tls(u32);
void p3_stdin_read_via_stream(u32); u32 p3_stdout_write_via_stream(u32); u32 p3_stderr_write_via_stream(u32);
void p3_option_none(u32); u64 p3_monotonic_now(void); u32 p3_wait_for(u64); u32 p3_wait_until(u64); void p3_system_now(u32);
extern int p3_stats[8];
