#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <time.h>
static uint8_t mem[65536];
__attribute__((noinline)) uint32_t kernel(uint32_t n) {
    uint32_t i = 0, acc = 1;
    do {
        acc = acc * 31 + mem[i & 1023] + i;
        mem[(i * 7) & 1023] = (uint8_t)acc;
        i++;
    } while (i < n);
    return acc;
}
int main(int argc, char **argv) {
    uint32_t n = atoi(argv[1]);
    for (int k = 0; k < 3; k++) {
        struct timespec a, b; clock_gettime(CLOCK_MONOTONIC, &a);
        uint32_t r = kernel(n);
        clock_gettime(CLOCK_MONOTONIC, &b);
        double s = (b.tv_sec - a.tv_sec) + (b.tv_nsec - a.tv_nsec) / 1e9;
        printf("result %u  %.3f s  %.1f M iterations/s\n", r, s, n / s / 1e6);
    }
}
