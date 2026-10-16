/* hand-written glue for the PoC: what a generator would emit for simple.wasm (export add(i32,i32)->i32) */
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include "simple.h"
#include "wasm-rt-impl.h"

static w2c_simple inst;

static PyObject *py_add(PyObject *self, PyObject *args) {
    unsigned int a, b;
    if (!PyArg_ParseTuple(args, "II", &a, &b)) return NULL;
    wasm_rt_trap_t code = (wasm_rt_trap_t)wasm_rt_try(g_wasm_rt_jmp_buf);
    if (code) { PyErr_SetString(PyExc_RuntimeError, wasm_rt_strerror(code)); return NULL; }
    u32 r = w2c_simple_add(&inst, a, b);
    return PyLong_FromUnsignedLong(r);
}

static PyMethodDef methods[] = {{"add", py_add, METH_VARARGS, "add(i32, i32) -> i32"}, {NULL, NULL, 0, NULL}};
static struct PyModuleDef mod = {PyModuleDef_HEAD_INIT, "simple_ext", NULL, -1, methods};

PyMODINIT_FUNC PyInit_simple_ext(void) {
    wasm_rt_init();
    wasm2c_simple_instantiate(&inst);
    return PyModule_Create(&mod);
}
