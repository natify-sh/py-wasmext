#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
int main(void) {
    struct timespec a, b; clock_gettime(CLOCK_MONOTONIC, &a);
    usleep(20000);
    clock_gettime(CLOCK_MONOTONIC, &b);
    long ms = (b.tv_sec - a.tv_sec) * 1000 + (b.tv_nsec - a.tv_nsec) / 1000000;
    printf("slept >= 20ms: %s (%ld ms)\n", ms >= 20 ? "yes" : "no", ms);
    char line[128] = {0};
    if (fgets(line, sizeof line, stdin)) printf("stdin: %s", line); else printf("stdin: EOF\n");
    fprintf(stderr, "to stderr\n");
    time_t t = time(NULL); printf("year >= 2026: %s\n", t > 1767225600 ? "yes" : "no");
    return 0;
}
