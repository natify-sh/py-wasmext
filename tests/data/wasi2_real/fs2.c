#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <unistd.h>

#define CHECK(x) do { if ((x) < 0) { printf("%s failed: %s\n", #x, strerror(errno)); return 1; } } while (0)

int main(void) {
    int fd = open("/data/f.bin", O_RDWR | O_CREAT | O_TRUNC, 0644);
    CHECK(fd);
    CHECK(pwrite(fd, "0123456789", 10, 0));
    CHECK(pwrite(fd, "AB", 2, 4));
    char buf[16] = {0};
    CHECK(pread(fd, buf, 10, 0));
    printf("pread=%s\n", buf);
    CHECK(lseek(fd, -3, SEEK_END));
    memset(buf, 0, sizeof buf);
    CHECK(read(fd, buf, 3));
    printf("tail=%s\n", buf);
    CHECK(ftruncate(fd, 4));
    struct stat st;
    CHECK(fstat(fd, &st));
    printf("size=%ld\n", (long)st.st_size);
    CHECK(fsync(fd));
    close(fd);
    CHECK(symlink("f.bin", "/data/link"));
    char target[32] = {0};
    CHECK(readlink("/data/link", target, sizeof target - 1));
    printf("readlink=%s\n", target);
    CHECK(link("/data/f.bin", "/data/hard"));
    CHECK(stat("/data/hard", &st));
    printf("nlink=%ld\n", (long)st.st_nlink);
    struct timespec ts[2] = {{1000000000, 0}, {1500000000, 0}};
    CHECK(utimensat(AT_FDCWD, "/data/f.bin", ts, 0));
    CHECK(stat("/data/f.bin", &st));
    printf("mtime=%ld\n", (long)st.st_mtim.tv_sec);
    CHECK(mkdir("/data/d", 0755));
    CHECK(rename("/data/f.bin", "/data/d/g.bin"));
    CHECK(rmdir("/data/d") == 0 ? -1 : 0);  /* not empty: must fail */
    printf("rmdir non-empty fails=%d\n", errno == ENOTEMPTY);
    CHECK(unlink("/data/d/g.bin"));
    CHECK(rmdir("/data/d"));
    CHECK(unlink("/data/link"));
    CHECK(unlink("/data/hard"));
    int rc = open("/data/nope", O_RDONLY);
    printf("open missing=%d enoent=%d\n", rc, errno == ENOENT);
    rc = open("/data/../escape", O_RDONLY);
    printf("escape refused=%d\n", rc < 0);
    return 0;
}
