/* The scenario of tests/test_wasi_p2_cli.py, in C: a fake memory, a bump allocator for cabi_realloc, pipes for the descriptor streams. */
#include <inttypes.h>
#include "wasi_p2_cli.h"

static void trap(wasi_p2_state *s, const char *m) {
    if (s->exited) printf("EXIT %u\n", s->exit_code);
    else printf("TRAP %s\n", m);
    exit(0);
}

static uint32_t bump(wasi_p2_state *s, uint32_t comp, uint32_t old_ptr, uint32_t old_size, uint32_t align, uint32_t new_size) {
    uint32_t *next = (uint32_t *)s->user;
    (void)comp, (void)old_ptr, (void)old_size;
    uint32_t ptr = (*next + align - 1) / align * align;
    *next = ptr + new_size;
    return ptr;
}

static uint8_t memory[256];

static void dump(const char *what) {
    printf("%s ", what);
    for (int i = 0; i < 256; i++) printf("%02x", memory[i]);
    printf("\n");
}

int main(int argc, char **argv) {
    const char *scenario = argc > 1 ? argv[1] : "main";
    uint32_t next = 160;
    static const char *const args[] = {"prog", "-x"}, *const names[] = {"A", "LONG"}, *const values[] = {"1", "value"};
    wasi_p2_state s;
    wasi_p2_init(&s);
    s.trap = trap;
    s.user = &next;
    s.realloc = bump;
    s.args = args, s.arg_count = 2;
    s.env_names = names, s.env_values = values, s.env_count = 2;
    s.initial_cwd = "/work";
    wasi_p2_set_memory(&s, 0, memory, sizeof memory);
    memcpy(memory + 120, "hello", 5);
    wasi_p2_fd_stream *fin = NULL, *fout = NULL;
    int out_pipe[2] = {-1, -1};
    if (!strcmp(scenario, "main")) {
        s.terminals = WASI_P2_TERMINAL_STDOUT;
        uint32_t hi = wasi_p2_memory_input_new(&s, (const uint8_t *)"in!", 3), ho;
        wasi_p2_buffer_output *bo = wasi_p2_buffer_output_new(&s, 100, &ho);
        s.std[0] = wasi_p2_table_get(&s, hi, WASI_P2_KIND_INPUT_STREAM)->obj;
        s.std[1] = &bo->base;
        printf("handles %u %u\n", hi, ho);
        wasi_cli_environment_get_arguments(&s, 0, 0), dump("arguments");
        wasi_cli_environment_get_environment(&s, 0, 16), dump("environment");
        wasi_cli_environment_initial_cwd(&s, 0, 40), dump("cwd");
        wasi_cli_terminal_stdin_get_terminal_stdin(&s, 0, 56), dump("terminal stdin");
        wasi_cli_terminal_stdout_get_terminal_stdout(&s, 0, 64), dump("terminal stdout");
        wasi_cli_terminal_output_terminal_output_drop(&s, wasi_p2_load_u32(&s, 0, 68));
        uint32_t a = wasi_cli_stdin_get_stdin(&s), b = wasi_cli_stdout_get_stdout(&s), c = wasi_cli_stdout_get_stdout(&s);
        printf("std handles %u %u %u\n", a, b, c);
        wasi_io_streams_output_stream_write(&s, 0, b, 120, 5, 80), dump("write");
        wasi_io_streams_output_stream_drop(&s, b);
        wasi_io_streams_output_stream_write(&s, 0, c, 120, 5, 88), dump("write after the other handle was dropped");
        wasi_io_streams_output_stream_drop(&s, c);
        wasi_io_streams_input_stream_read(&s, 0, a, 10, 96), dump("read");
        wasi_io_streams_input_stream_drop(&s, a);
        printf("stderr %u\n", wasi_cli_stderr_get_stderr(&s));
        printf("stdout ");
        for (uint64_t i = 0; i < bo->len; i++) printf("%02x", bo->buf[i]);
        printf("\n");
        wasi_p2_free(&s);
        wasi_p2_buffer_output_release(bo);
        return 0;
    } else if (!strcmp(scenario, "fd")) {
        int in_pipe[2];
        if (pipe(in_pipe) || pipe(out_pipe)) return 2;
        if (write(in_pipe[1], "pipe!", 5) != 5) return 2;
        close(in_pipe[1]);
        fin = wasi_p2_fd_input_new(&s, in_pipe[0]);
        fout = wasi_p2_fd_output_new(&s, out_pipe[1]);
        s.std[0] = fin, s.std[1] = fout;
        uint32_t a = wasi_cli_stdin_get_stdin(&s), b = wasi_cli_stdout_get_stdout(&s);
        printf("std handles %u %u\n", a, b);
        wasi_io_streams_input_stream_read(&s, 0, a, 16, 0), dump("read");
        wasi_io_streams_input_stream_read(&s, 0, a, 16, 16), dump("read at the end");
        wasi_io_streams_output_stream_blocking_write_and_flush(&s, 0, b, 120, 5, 32), dump("write");
        close(out_pipe[1]);
        uint8_t got[16];
        ssize_t n = read(out_pipe[0], got, sizeof got);
        printf("pipe ");
        for (ssize_t i = 0; i < n; i++) printf("%02x", got[i]);
        printf("\n");
        close(in_pipe[0]);
        close(out_pipe[0]);
    } else if (!strcmp(scenario, "exit_ok")) {
        wasi_cli_exit_exit(&s, 0);
    } else if (!strcmp(scenario, "exit_err")) {
        wasi_cli_exit_exit(&s, 1);
    } else if (!strcmp(scenario, "exit_code")) {
        wasi_cli_exit_exit_with_code(&s, 0x1ff);
    }
    wasi_p2_free(&s);
    free(fin);
    free(fout);
    return 0;
}
