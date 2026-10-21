#include "p3host.h"
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

enum { FREE, STREAM_R, STREAM_W, FUTURE_R, WSET };
enum { COMPLETED = 0, DROPPED = 1, CANCELLED = 2 };
#define BLOCKED 0xffffffffu
enum { EV_NONE = 0, EV_STREAM_READ = 2, EV_STREAM_WRITE = 3, EV_FUTURE_READ = 4 };
typedef struct { int sink, source, writer_dropped, reader_dropped; } Stream;
typedef struct { Stream *stream; int pending; u32 ptr; } Future;
typedef struct { int kind; void *obj; u32 set; int ev_code; u32 ev_payload; } Handle;

static Handle H[256];                 /* one table of waitables for the instance, index 0 unused */
static Stream S[64]; static int ns; static Future F[64]; static int nf;
static u32 sp, tls;
static wasm_rt_memory_t *(*getmem)(void);
int p3_stats[8];                      /* 0 stream.write, 1 bytes, 2 future.read, 3 blocked, 4 waits, 5 events */

static u8 *mem(u32 p, u32 n) { wasm_rt_memory_t *m = getmem(); if ((u64)p + n > m->size) wasm_rt_trap(WASM_RT_TRAP_OOB); return m->data + p; }
static u32 put(int kind, void *obj) { for (u32 i = 1; i < 256; i++) if (H[i].kind == FREE) { H[i] = (Handle){kind, obj, 0, EV_NONE, 0}; return i; } wasm_rt_trap(WASM_RT_TRAP_EXHAUSTION); }
static Handle *get(u32 h, int kind) { if (h == 0 || h >= 256 || H[h].kind != kind) { fprintf(stderr, "[p3] bad handle %u (want kind %d)\n", h, kind); wasm_rt_trap(WASM_RT_TRAP_UNREACHABLE); } return &H[h]; }
static void store32(u32 p, u32 v) { memcpy(mem(p, 4), &v, 4); }

void p3_set_memory(wasm_rt_memory_t *(*g)(void)) { getmem = g; }
u32 p3_get_sp(void) { return sp; } void p3_set_sp(u32 v) { sp = v; }
u32 p3_get_tls(void) { return tls; } void p3_set_tls(u32 v) { tls = v; }
void p3_noop1(u32 h) { (void)h; }

u64 p3_stream_new(void) {
  Stream *s = &S[ns++]; *s = (Stream){-1, -1, 0, 0};
  u32 r = put(STREAM_R, s), w = put(STREAM_W, s);
  return ((u64)w << 32) | r;
}
static void complete_futures(Stream *s) {     /* the writer is done: futures on this stream resolve to ok */
  for (u32 i = 1; i < 256; i++)
    if (H[i].kind == FUTURE_R && ((Future *)H[i].obj)->stream == s && ((Future *)H[i].obj)->pending) {
      Future *f = H[i].obj; *mem(f->ptr, 1) = 0; f->pending = 0;     /* result<_, error-code>: ok */
      H[i].ev_code = EV_FUTURE_READ; H[i].ev_payload = COMPLETED; p3_stats[5]++;
    }
}
void p3_stream_drop_writable(u32 w) { Stream *s = get(w, STREAM_W)->obj; s->writer_dropped = 1; H[w].kind = FREE; complete_futures(s); }
void p3_stream_drop_readable(u32 r) { Stream *s = get(r, STREAM_R)->obj; s->reader_dropped = 1; H[r].kind = FREE; }
u32 p3_stream_write(u32 w, u32 ptr, u32 n) {
  Stream *s = get(w, STREAM_W)->obj; p3_stats[0]++;
  if (s->sink >= 0) { ssize_t k = write(s->sink, mem(ptr, n), n); if (k < 0) return DROPPED; p3_stats[1] += (int)k; return ((u32)k << 4) | COMPLETED; }
  if (s->reader_dropped) return DROPPED;
  p3_stats[3]++; fprintf(stderr, "[p3] stream.write with no host reader: guest-to-guest streams not in this sketch\n");
  wasm_rt_trap(WASM_RT_TRAP_UNREACHABLE);
}
u32 p3_stream_read(u32 r, u32 ptr, u32 n) {
  Stream *s = get(r, STREAM_R)->obj;
  if (s->source >= 0) { ssize_t k = read(s->source, mem(ptr, n), n); return k <= 0 ? DROPPED : (((u32)k << 4) | COMPLETED); }
  return DROPPED;
}
u32 p3_stream_cancel(u32 h) { (void)h; return CANCELLED; }
static u32 host_reads(Stream *s, int fd) { s->sink = fd; Future *f = &F[nf++]; *f = (Future){s, 0, 0}; return put(FUTURE_R, f); }
u32 p3_stdout_write_via_stream(u32 r) { Stream *s = get(r, STREAM_R)->obj; H[r].kind = FREE; return host_reads(s, 1); }
u32 p3_stderr_write_via_stream(u32 r) { Stream *s = get(r, STREAM_R)->obj; H[r].kind = FREE; return host_reads(s, 2); }
void p3_stdin_read_via_stream(u32 retptr) {   /* (stream<u8>, future<result<_, error-code>>) */
  Stream *s = &S[ns++]; *s = (Stream){-1, 0, 1, 0};
  Future *f = &F[nf++]; *f = (Future){s, 0, 0};
  store32(retptr, put(STREAM_R, s)); store32(retptr + 4, put(FUTURE_R, f));
}
u32 p3_future_read(u32 fr, u32 ptr) {
  Future *f = get(fr, FUTURE_R)->obj; p3_stats[2]++;
  if (f->stream->writer_dropped) { *mem(ptr, 1) = 0; return COMPLETED; }
  f->pending = 1; f->ptr = ptr; p3_stats[3]++; return BLOCKED;
}
void p3_future_drop_readable(u32 fr) { get(fr, FUTURE_R); H[fr].kind = FREE; }
u32 p3_ws_new(void) { return put(WSET, NULL); }
void p3_ws_join(u32 w, u32 set) { if (w == 0 || w >= 256 || H[w].kind == FREE) wasm_rt_trap(WASM_RT_TRAP_UNREACHABLE); H[w].set = set; }
void p3_ws_drop(u32 set) { get(set, WSET); H[set].kind = FREE; }
static u32 take_event(u32 set, u32 ptr) {
  for (u32 i = 1; i < 256; i++)
    if (H[i].kind != FREE && H[i].set == set && H[i].ev_code != EV_NONE) {
      u32 code = (u32)H[i].ev_code; store32(ptr, i); store32(ptr + 4, H[i].ev_payload); H[i].ev_code = EV_NONE; return code;
    }
  return EV_NONE;
}
u32 p3_ws_wait(u32 set, u32 ptr) {
  p3_stats[4]++; get(set, WSET);
  u32 c = take_event(set, ptr);
  if (c == EV_NONE) { fprintf(stderr, "[p3] waitable-set.wait with nothing pending: deadlock\n"); wasm_rt_trap(WASM_RT_TRAP_UNREACHABLE); }
  return c;
}
u32 p3_ws_poll(u32 set, u32 ptr) { get(set, WSET); return take_event(set, ptr); }
u32 p3_subtask_cancel(u32 h) { (void)h; return 2; }
void p3_option_none(u32 retptr) { *mem(retptr, 1) = 0; }
u64 p3_monotonic_now(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return (u64)t.tv_sec * 1000000000u + (u64)t.tv_nsec; }
void p3_system_now(u32 retptr) { struct timespec t; clock_gettime(CLOCK_REALTIME, &t); u64 s = (u64)t.tv_sec; u32 n = (u32)t.tv_nsec; memcpy(mem(retptr, 8), &s, 8); store32(retptr + 8, n); }
u32 p3_wait_for(u64 ns_) { struct timespec t = {(time_t)(ns_ / 1000000000u), (long)(ns_ % 1000000000u)}; nanosleep(&t, NULL); return 2; /* RETURNED, no subtask */ }
u32 p3_wait_until(u64 when) { u64 now = p3_monotonic_now(); return p3_wait_for(when > now ? when - now : 0); }
