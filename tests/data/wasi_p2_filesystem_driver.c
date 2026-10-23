/* The scenario of tests/test_wasi_p2_filesystem.py, in C, on a tree that the test makes (argv[2] is its root): the output is compared with the Python host's. */
#include <inttypes.h>
#include "wasi_p2_filesystem.h"

static wasi_p2_state s;
static uint8_t memory[4096];

static void trap(wasi_p2_state *st, const char *m) { (void)st; printf("TRAP %s\n", m); exit(0); }
static uint64_t wall(wasi_p2_state *st) { (void)st; return 1700000000123456789ULL; }
static uint32_t bump(wasi_p2_state *st, uint32_t comp, uint32_t old_ptr, uint32_t old_size, uint32_t align, uint32_t new_size) {
    uint32_t *next = (uint32_t *)st->user;
    (void)comp, (void)old_ptr, (void)old_size;
    uint32_t ptr = (*next + align - 1) / align * align;
    *next = ptr + new_size;
    return ptr;
}

static void show(const char *label, uint32_t off, uint32_t n) {
    printf("%s %u:", label, off);
    for (uint32_t i = 0; i < n; i++) printf("%02x", memory[off + i]);
    printf("\n");
}
static uint32_t u32(uint32_t off) { return wasi_p2_load_u32(&s, 0, off); }
static uint64_t u64(uint32_t off) { return (uint64_t)u32(off) | (uint64_t)u32(off + 4) << 32; }
static void clear(uint32_t off, uint32_t n) { memset(memory + off, 0, n); }
static uint32_t path(const char *text, size_t n) {
    memcpy(memory + 1000, text, n);
    return (uint32_t)n;
}
/* a stat result at `r`: the error, or type, link count, size */
static void statline(const char *label, uint32_t r) {
    if (memory[r]) printf("%s err %u\n", label, memory[r + 8]);
    else printf("%s type %u nlink %" PRIu64 " size %" PRIu64 "\n", label, memory[r + 8], u64(r + 16), u64(r + 24));
}
static void times(const char *label, uint32_t r) {
    printf("%s atime %" PRIu64 ".%u mtime %" PRIu64 ".%u\n", label, u64(r + 8 + 32), u32(r + 8 + 40), u64(r + 8 + 56), u32(r + 8 + 64));
}

#define FS(fn, ...) wasi_filesystem_types_##fn(&s, 0, __VA_ARGS__)
#define IO(fn, ...) wasi_io_streams_##fn(&s, 0, __VA_ARGS__)

static void read_all(const char *label, uint32_t h, uint64_t len, uint64_t off) {
    clear(220, 16);
    FS(descriptor_read, h, len, off, 220);
    show(label, 220, 16);
    if (!memory[220]) show("  data", u32(224), u32(228));
}

static void stat_paths(uint32_t hd) {
    static const struct { const char *p; uint32_t flags; } cases[] = {
        {"sub/f", 1}, {"ln/f", 1}, {"abs/passwd", 1}, {"up", 1}, {"../x", 1}, {"sub/../sub/f", 1}, {"/etc", 1}, {"loop1", 1}, {"deep/f", 1},
        {"nope", 1}, {"sub/f/x", 1}, {"", 1}, {"sub/", 1}, {"sub/f/", 1}, {"ln", 0}, {"ln", 1}, {"ln/", 0}, {"sub/..", 1}, {"sub/../..", 1}, {"lkout/", 0}, {"lkout", 0}, {"lkout/.", 1},
    };
    for (size_t i = 0; i < sizeof cases / sizeof *cases; i++) {
        uint32_t n = path(cases[i].p, strlen(cases[i].p));
        clear(200, 120);
        FS(descriptor_stat_at, hd, cases[i].flags, 1000, n, 200);
        printf("[%s] ", cases[i].p);
        statline("stat", 200);
    }
    char longname[301];
    memset(longname, 'a', 300), longname[300] = 0;
    uint32_t n = path(longname, 300);
    clear(200, 120);
    FS(descriptor_stat_at, hd, 1, 1000, n, 200);
    statline("[long] stat", 200);
}

int main(int argc, char **argv) {
    const char *scenario = argc > 1 ? argv[1] : "main";
    const char *root = argc > 2 ? argv[2] : ".";
    uint32_t next = 1600;
    struct wasi_p2_preopen pre[2] = {{root, "/", 1}, {root, "/ro", 0}};
    wasi_p2_init(&s);
    s.trap = trap;
    s.user = &next;
    s.realloc = bump;
    s.wall_ns = wall;
    s.preopens = pre, s.preopen_count = 2;
    wasi_p2_set_memory(&s, 0, memory, sizeof memory);
    memcpy(memory + 1500, "hello", 5);
    memcpy(memory + 1510, " world", 6);
    if (!strcmp(scenario, "main")) {
        wasi_filesystem_preopens_get_directories(&s, 0, 0);
        uint32_t lp = u32(0), hd = u32(lp), ro = u32(lp + 12);
        show("dirs", 0, 8), show("dirs", lp, 24), show("names", u32(lp + 4), 1), show("names", u32(lp + 16), 3);
        printf("handles %u %u\n", hd, ro);
        stat_paths(hd);
        uint32_t n;
        /* a link that leads out, with a slash and without symlink-follow, must not be entered */
        n = path("lkout/", 6);
        FS(descriptor_open_at, hd, 0, 1000, n, 2, 1, 200), show("open lkout/ without follow", 200, 8);
        /* open, read */
        n = path("sub/f", 5);
        FS(descriptor_open_at, hd, 1, 1000, n, 0, 1, 200), show("open", 200, 8);
        uint32_t h = u32(204);
        read_all("read", h, 10, 0), read_all("read", h, 10, 2), read_all("read", h, 10, 4), read_all("read", h, 2, 0);
        FS(descriptor_get_type, h, 240), show("type", 240, 2);
        FS(descriptor_get_flags, h, 242), show("flags", 242, 2);
        clear(300, 120);
        FS(descriptor_stat, h, 300), statline("fstat", 300);
        FS(descriptor_read_via_stream, h, 1, 250), show("read_via_stream", 250, 8);
        uint32_t hs = u32(254);
        IO(input_stream_read, hs, 100, 260), show("stream read", 260, 12), show("  data", u32(264), u32(268));
        IO(input_stream_read, hs, 100, 260), show("stream read at the end", 260, 12);
        wasi_io_streams_input_stream_drop(&s, hs);
        FS(descriptor_write, h, 1500, 3, 0, 270), show("write on read-only", 270, 16);
        FS(descriptor_set_size, h, 1, 290), show("set_size on read-only", 290, 2);
        wasi_filesystem_types_descriptor_drop(&s, h);
        /* create and write */
        n = path("sub/new", 7);
        FS(descriptor_open_at, hd, 1, 1000, n, 1, 3, 200), show("create", 200, 8);
        uint32_t hn = u32(204);
        FS(descriptor_write, hn, 1500, 5, 0, 220), show("write", 220, 16);
        FS(descriptor_write_via_stream, hn, 5, 250);
        uint32_t hw = u32(254);
        IO(output_stream_blocking_write_and_flush, hw, 1510, 6, 260), show("stream write", 260, 8);
        wasi_io_streams_output_stream_drop(&s, hw);
        read_all("read back", hn, 100, 0);
        FS(descriptor_append_via_stream, hn, 250);
        uint32_t ha = u32(254);
        IO(output_stream_write, ha, 1500, 5, 260), show("append", 260, 8);
        wasi_io_streams_output_stream_drop(&s, ha);
        read_all("read appended", hn, 100, 0);
        FS(descriptor_set_size, hn, 3, 270), show("set_size", 270, 2);
        read_all("read truncated", hn, 100, 0);
        FS(descriptor_sync, hn, 280), FS(descriptor_sync_data, hn, 284), FS(descriptor_advise, hn, 0, 0, 0, 288);
        show("sync", 280, 10);
        wasi_filesystem_types_descriptor_drop(&s, hn);
        FS(descriptor_open_at, hd, 1, 1000, n, 5, 3, 200), show("exclusive create of an existing file", 200, 8);
        FS(descriptor_open_at, ro, 1, 1000, n, 8, 2, 200), show("truncate on a read-only preopen", 200, 8);
        FS(descriptor_open_at, ro, 1, 1000, n, 1, 1, 200), show("create on a read-only preopen", 200, 8);
        FS(descriptor_open_at, ro, 1, 1000, n, 0, 3, 200), show("write on a read-only preopen", 200, 8);
        FS(descriptor_open_at, ro, 1, 1000, n, 0, 1, 200), show("read on a read-only preopen", 200, 8);
        wasi_filesystem_types_descriptor_drop(&s, u32(204));
        FS(descriptor_get_flags, ro, 240), FS(descriptor_get_flags, hd, 242), show("preopen flags", 240, 4);
        /* directories */
        n = path("sub", 3);
        FS(descriptor_open_at, hd, 1, 1000, n, 2, 1, 200), show("open a directory", 200, 8);
        uint32_t hdir = u32(204);
        FS(descriptor_read_directory, hdir, 220), show("read_directory", 220, 8);
        uint32_t he = u32(224);
        for (int i = 0; i < 5; i++) {
            clear(240, 20);
            FS(directory_entry_stream_read_directory_entry, he, 240);
            show("entry", 240, 20);
            if (memory[244]) show("  name", u32(252), u32(256));
            else break;
        }
        wasi_filesystem_types_directory_entry_stream_drop(&s, he);
        wasi_filesystem_types_descriptor_drop(&s, hdir);
        n = path("sub/f", 5);
        FS(descriptor_open_at, hd, 1, 1000, n, 0, 1, 200);
        h = u32(204);
        FS(descriptor_read_directory, h, 220), show("read_directory of a file", 220, 8);
        wasi_filesystem_types_descriptor_drop(&s, h);
        /* changes */
        n = path("sub/d", 5);
        FS(descriptor_create_directory_at, hd, 1000, n, 300), FS(descriptor_create_directory_at, hd, 1000, n, 302);
        FS(descriptor_create_directory_at, ro, 1000, n, 304);
        FS(descriptor_remove_directory_at, hd, 1000, n, 306), FS(descriptor_remove_directory_at, hd, 1000, n, 308);
        show("mkdir mkdir mkdir(ro) rmdir rmdir", 300, 10);
        n = path("sub/new", 7);
        FS(descriptor_unlink_file_at, hd, 1000, n, 300), FS(descriptor_unlink_file_at, hd, 1000, n, 302);
        show("unlink unlink", 300, 4);
        uint32_t n2 = path("sub/g", 5);
        memcpy(memory + 1100, "sub/g2", 6);
        FS(descriptor_rename_at, hd, 1000, n2, hd, 1100, 6, 310), show("rename", 310, 2);
        memcpy(memory + 1200, "sub/f2", 6);
        n = path("sub/f", 5);
        FS(descriptor_link_at, hd, 0, 1000, n, hd, 1200, 6, 312), show("link", 312, 2);
        clear(320, 120);
        FS(descriptor_stat_at, hd, 1, 1000, n, 320), statline("sub/f after link", 320);
        memcpy(memory + 1300, "f", 1);
        memcpy(memory + 1310, "sub/sl", 6);
        FS(descriptor_symlink_at, hd, 1300, 1, 1310, 6, 314), show("symlink", 314, 2);
        FS(descriptor_readlink_at, hd, 1310, 6, 330), show("readlink", 330, 12), show("  target", u32(334), u32(338));
        FS(descriptor_readlink_at, hd, 1000, n, 330), show("readlink of a file", 330, 8);
        /* identity */
        FS(descriptor_open_at, hd, 1, 1000, n, 0, 1, 200);
        uint32_t a = u32(204);
        FS(descriptor_open_at, hd, 1, 1200, 6, 0, 1, 200);
        uint32_t b = u32(204);
        FS(descriptor_open_at, hd, 1, 1100, 6, 0, 1, 200);
        uint32_t c = u32(204);
        printf("same %u %u\n", wasi_filesystem_types_descriptor_is_same_object(&s, a, b), wasi_filesystem_types_descriptor_is_same_object(&s, a, c));
        FS(descriptor_metadata_hash, a, 400), FS(descriptor_metadata_hash, b, 430), FS(descriptor_metadata_hash, c, 460);
        FS(descriptor_metadata_hash_at, hd, 1, 1000, n, 490);
        printf("hash a==b %d a==c %d a==at %d\n", !memcmp(memory + 408, memory + 438, 16), !memcmp(memory + 408, memory + 468, 16),
               !memcmp(memory + 408, memory + 498, 16));
        /* times */
        FS(descriptor_set_times_at, hd, 1, 1000, n, 2, 1000, 0, 2, 2000, 5, 520), show("set_times_at", 520, 2);
        clear(530, 120);
        FS(descriptor_stat_at, hd, 1, 1000, n, 530), times("times", 530);
        FS(descriptor_set_times, a, 0, 0, 0, 1, 0, 0, 540), show("set_times on a read-only file", 540, 2);
        FS(descriptor_open_at, hd, 1, 1000, n, 0, 3, 200), h = u32(204);
        FS(descriptor_set_times, h, 0, 0, 0, 1, 0, 0, 542), show("set_times", 542, 2);
        clear(530, 120);
        FS(descriptor_stat, h, 530), times("no-change, now", 530);
        /* the rules of the WIT: absolute links, a directory to unlink, the hash follows the contents */
        memcpy(memory + 1400, "abs", 3);
        FS(descriptor_readlink_at, hd, 1400, 3, 600), show("readlink of an absolute link", 600, 8);
        memcpy(memory + 1410, "/etc", 4);
        memcpy(memory + 1420, "sub/sl2", 7);
        FS(descriptor_symlink_at, hd, 1410, 4, 1420, 7, 610), show("symlink to an absolute path", 610, 2);
        FS(descriptor_symlink_at, ro, 1300, 1, 1420, 7, 612), show("symlink on a read-only preopen", 612, 2);
        memcpy(memory + 1430, "sub", 3);
        FS(descriptor_unlink_file_at, hd, 1430, 3, 620), show("unlink of a directory", 620, 2);
        FS(descriptor_metadata_hash_at, hd, 1, 1000, n, 640);
        FS(descriptor_open_at, hd, 1, 1000, n, 0, 2, 200), h = u32(204);
        FS(descriptor_write, h, 1500, 1, 100, 670), show("write past the end", 670, 16);
        wasi_filesystem_types_descriptor_drop(&s, h);
        FS(descriptor_metadata_hash_at, hd, 1, 1000, n, 700);
        printf("hash after a write: same %d\n", !memcmp(memory + 648, memory + 708, 16));
        /* an error with a code */
        FS(descriptor_read_via_stream, hd, 0, 250);
        hs = u32(254);
        IO(input_stream_read, hs, 10, 260), show("read of a directory", 260, 12);
        wasi_filesystem_types_filesystem_error_code(&s, 0, u32(268), 280), show("error code", 280, 2);
    } else if (!strcmp(scenario, "bad_handle")) {
        FS(descriptor_get_flags, 12345, 0);
    } else if (!strcmp(scenario, "outside")) {
        FS(descriptor_stat_at, 1048577, 1, 4090, 100, 0);
    }
    wasi_p2_free(&s);
    return 0;
}
