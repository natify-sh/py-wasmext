/* PoC glue for coremark.wasm: imports implemented natively, memory exposed as a memoryview, traps as RuntimeError */
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <time.h>
#include "coremark.h"
#include "wasm-rt-impl.h"

static w2c_coremark inst;
static struct w2c_wiring { int unused; } host;     /* the "wiring" import object */
static PyObject *printed;                          /* bytes the module printed, collected */

/* imports (called by the wasm code) */
u32 w2c_wiring_millis(struct w2c_wiring *w) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return (u32)(t.tv_sec * 1000 + t.tv_nsec / 1000000); }
void w2c_wiring_delay(struct w2c_wiring *w, u32 ms) { (void)ms; }
void w2c_wiring_stopWdt(struct w2c_wiring *w) {}
void w2c_wiring_print(struct w2c_wiring *w, u32 off, u32 len) {
    if ((u64)off + len > inst.w2c_memory.size) wasm_rt_trap(WASM_RT_TRAP_OOB);
    PyObject *b = PyBytes_FromStringAndSize((const char *)inst.w2c_memory.data + off, len);
    if (b) { PyList_Append(printed, b); Py_DECREF(b); }
}

#define CALL0(NAME) \
static PyObject *py_##NAME(PyObject *self, PyObject *noargs) { \
    wasm_rt_trap_t code = (wasm_rt_trap_t)wasm_rt_try(g_wasm_rt_jmp_buf); \
    if (code) { PyErr_SetString(PyExc_RuntimeError, wasm_rt_strerror(code)); return NULL; } \
    w2c_coremark_##NAME(&inst); Py_RETURN_NONE; }
CALL0(setup)
CALL0(loop)

static PyObject *py_memory(PyObject *self, PyObject *noargs) {
    wasm_rt_memory_t *m = w2c_coremark_memory(&inst);
    return PyMemoryView_FromMemory((char *)m->data, (Py_ssize_t)m->size, PyBUF_WRITE);
}
static PyObject *py_output(PyObject *self, PyObject *noargs) {
    PyObject *sep = PyBytes_FromStringAndSize("", 0), *r = PyObject_CallMethod(sep, "join", "O", printed);
    Py_DECREF(sep); PyList_SetSlice(printed, 0, PyList_GET_SIZE(printed), NULL); return r;
}
static PyMethodDef methods[] = {
    {"setup", py_setup, METH_NOARGS, ""}, {"loop", py_loop, METH_NOARGS, ""},
    {"memory", py_memory, METH_NOARGS, "a memoryview of the linear memory (valid until it grows)"},
    {"output", py_output, METH_NOARGS, "bytes printed since the last call"}, {NULL, NULL, 0, NULL}};
static struct PyModuleDef mod = {PyModuleDef_HEAD_INIT, "coremark_ext", NULL, -1, methods};
PyMODINIT_FUNC PyInit_coremark_ext(void) {
    printed = PyList_New(0);
    wasm_rt_init();
    wasm2c_coremark_instantiate(&inst, &host);
    return PyModule_Create(&mod);
}
