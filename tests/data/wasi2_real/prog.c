#include <dirent.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <sys/stat.h>

int main(int argc, char **argv) {
    printf("argc=%d argv0=%s\n", argc, argv[0]);
    for (int i = 1; i < argc; i++) printf("arg %d=%s\n", i, argv[i]);
    const char *e = getenv("GREETING");
    printf("GREETING=%s\n", e ? e : "(unset)");
    char line[128];
    if (fgets(line, sizeof line, stdin)) printf("stdin line: %s", line);
    FILE *f = fopen("/data/out.txt", "w");
    if (!f) { perror("fopen w"); return 3; }
    fprintf(f, "written by wasip2\n");
    fclose(f);
    f = fopen("/data/out.txt", "r");
    if (!f) { perror("fopen r"); return 4; }
    char buf[64] = {0};
    fgets(buf, sizeof buf, f);
    fclose(f);
    printf("read back: %s", buf);
    mkdir("/data/sub", 0777);
    DIR *d = opendir("/data");
    if (!d) { perror("opendir"); return 5; }
    struct dirent *ent;
    int n = 0;
    while ((ent = readdir(d))) if (ent->d_name[0] != '.') n++;
    closedir(d);
    printf("entries=%d\n", n);
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    printf("clock ok=%d\n", t.tv_sec >= 0);
    fprintf(stderr, "to stderr\n");
    return 0;
}
