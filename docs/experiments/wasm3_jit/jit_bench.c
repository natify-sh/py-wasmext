// Prototype: x86-64 template JIT for the metacode of one wasm3 loop. Decodes ops by name, emits native code, patches the Loop op.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <time.h>
#include <sys/mman.h>
#include "wasm3.h"
#include "m3_env.h"
#include "m3_function.h"
extern const char *jit_opname(const void *);

static uint8_t *cb; static size_t cl;
static void B(int n, ...) { __builtin_va_list a; __builtin_va_start(a, n); while (n--) cb[cl++] = (uint8_t)__builtin_va_arg(a, int); __builtin_va_end(a); }
static void D32(uint32_t v) { memcpy(cb + cl, &v, 4); cl += 4; }
#define SL(s) ((uint32_t)((s) * 4))
static void ld(int s) { B(2, 0x8B, 0x83); D32(SL(s)); }        // mov eax,[rbx+s]
static void st(int s) { B(2, 0x89, 0x83); D32(SL(s)); }        // mov [rbx+s],eax
static void alu(int op, int s) { B(2, op, 0x83); D32(SL(s)); } // op eax,[rbx+s]
static void imul(int s) { B(3, 0x0F, 0xAF, 0x83); D32(SL(s)); }
static size_t trap_fix[16]; static int ntrap;
static void bounds(uint32_t off, int size) {   // ecx = eax (+off) ; trap if ecx+size > length
    B(2, 0x89, 0xC1); B(3, 0x48, 0x81, 0xC1); D32(off); B(4, 0x48, 0x8D, 0x51, size); B(3, 0x4C, 0x39, 0xEA);
    B(2, 0x0F, 0x87); trap_fix[ntrap++] = cl; D32(0);
}
static const uint64_t *rd; // stream reader
#define W() ((uint32_t)*rd++)

static void (*next_op_fn)(void); static const void *next_pc;
typedef const void *(*Op)(const void *, uint64_t *, void *, int64_t);
typedef uint64_t (*Native)(uint64_t *sp, uint8_t *mem, uint64_t len);
static Native native;
static const void *JitRun(const void *pc, uint64_t *sp, void *mem, int64_t r0) {
    uint64_t len = *(uint64_t *)((char *)mem + offsetof(M3MemoryHeader, length));
    if (native(sp, (uint8_t *)((M3MemoryHeader *)mem + 1), len)) return m3Err_trapOutOfBoundsMemoryAccess;
    return ((Op)(*(const uint64_t *)next_pc))((const uint64_t *)next_pc + 1, sp, mem, 0);
}

int main(int argc, char **argv) {
    FILE *f = fopen(argv[1], "rb"); fseek(f, 0, SEEK_END); long len = ftell(f); fseek(f, 0, SEEK_SET);
    unsigned char *buf = malloc(len); if (fread(buf, 1, len, f) != (size_t)len) return 3; fclose(f);
    int n = atoi(argv[3]), reps = atoi(argv[4]), usejit = atoi(argv[5]);
    IM3Environment env = m3_NewEnvironment(); IM3Runtime rt = m3_NewRuntime(env, 64 * 1024, NULL);
    IM3Module mod; if (m3_ParseModule(env, &mod, buf, len)) return 4; if (m3_LoadModule(rt, mod)) return 4;
    IM3Function fn; if (m3_FindFunction(&fn, rt, argv[2])) return 4;
    if (usejit) {
        uint64_t *code = (uint64_t *)fn->compiled; int loop = -1, cont = -1;
        for (int i = 0; i < 400; i++) { const char *nm = jit_opname((void *)code[i]); if (!nm) continue;
            if (!strcmp(nm, "Loop") && loop < 0) loop = i; if (!strcmp(nm, "ContinueLoopIf")) { cont = i; break; } }
        cb = mmap(0, 4096, PROT_READ | PROT_WRITE | PROT_EXEC, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        B(1, 0x53); B(2, 0x41, 0x54); B(2, 0x41, 0x55); B(3, 0x48, 0x89, 0xFB); B(3, 0x49, 0x89, 0xF4); B(3, 0x49, 0x89, 0xD5);
        size_t top = cl; rd = code + loop + 1; int nops = 0;
        while (rd < code + cont) {
            const char *nm = jit_opname((void *)*rd++); nops++;
            if (!strcmp(nm, "i32_Multiply_ss")) { int a = W(), b = W(); ld(b); imul(a); }
            else if (!strcmp(nm, "u32_And_ss")) { int a = W(), b = W(); ld(b); alu(0x23, a); }
            else if (!strcmp(nm, "SetSlot_i32")) st(W());
            else if (!strcmp(nm, "i32_Load_u8_r")) { uint32_t o = W(); bounds(o, 1); B(5, 0x41, 0x0F, 0xB6, 0x04, 0x0C); }
            else if (!strcmp(nm, "i32_Add_rs")) alu(0x03, W());
            else if (!strcmp(nm, "u32_And_rs")) alu(0x23, W());
            else if (!strcmp(nm, "i32_Add_rs_f")) { int a = W(), d = W(); alu(0x03, a); st(d); }
            else if (!strcmp(nm, "i32_Add_ss_f")) { int a = W(), b = W(), d = W(); ld(b); alu(0x03, a); st(d); }
            else if (!strcmp(nm, "i32_Store_u8_sr")) { int v = W(); uint32_t o = W(); bounds(o, 1); B(2, 0x8B, 0x93); D32(SL(v)); B(4, 0x41, 0x88, 0x14, 0x0C); }
            else if (!strcmp(nm, "u32_LessThan_ss")) { int a = W(), b = W(); ld(b); alu(0x3B, a); B(3, 0x0F, 0x92, 0xC0); B(3, 0x0F, 0xB6, 0xC0); }
            else { fprintf(stderr, "unsupported op %s\n", nm); return 6; }
        }
        B(2, 0x85, 0xC0); B(2, 0x0F, 0x85); D32((uint32_t)(top - (cl + 4)));      // test eax,eax; jnz top
        B(2, 0x31, 0xC0); B(2, 0x41, 0x5D); B(2, 0x41, 0x5C); B(1, 0x5B); B(1, 0xC3);
        size_t trap = cl; B(5, 0xB8, 1, 0, 0, 0); B(2, 0x41, 0x5D); B(2, 0x41, 0x5C); B(1, 0x5B); B(1, 0xC3);
        for (int i = 0; i < ntrap; i++) { uint32_t rel = (uint32_t)(trap - (trap_fix[i] + 4)); memcpy(cb + trap_fix[i], &rel, 4); }
        native = (Native)cb; next_pc = code + cont + 2; code[loop] = (uint64_t)JitRun;
        fprintf(stderr, "jit: %d ops -> %zu bytes\n", nops, cl);
    }
    for (int k = 0; k < reps; k++) {
        struct timespec a, b; clock_gettime(CLOCK_MONOTONIC, &a);
        M3Result r = m3_CallV(fn, n); if (r) { fprintf(stderr, "call: %s\n", r); return 5; }
        clock_gettime(CLOCK_MONOTONIC, &b);
        unsigned int ret = 0; m3_GetResultsV(fn, &ret);
        double s = (b.tv_sec - a.tv_sec) + (b.tv_nsec - a.tv_nsec) / 1e9;
        printf("result %u  %.3f s  %.1f M iterations/s\n", ret, s, n / s / 1e6);
    }
}
