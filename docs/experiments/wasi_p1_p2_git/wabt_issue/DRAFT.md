# wasm2c: an imported function in an element segment gets the wrong module instance

**Draft of an issue for WebAssembly/wabt (not posted).** Reproduced on 2026-10-22 with `wasm2c` 1.0.42 (`wabt-package` 1.0.42.0, Linux x86-64, gcc 13). The code that is
responsible is the same on `main` (read on 2026-10-22): `src/c-writer.cc` (the element segments, `case ExprType::RefFunc`, about line 2488) and
`src/template/wasm2c.declarations.c` (`funcref_table_init`).

## What happens

When an active element segment holds an **imported** function, `wasm2c` writes the entry as

```c
{RefFunc, w2c_ie_t0, (wasm_rt_function_ptr_t)wrap_w2c_env_f, {wasm_tailcall_w2c_env_f}, offsetof(w2c_ie, w2c_env_instance)},
```

and `funcref_table_init` makes the entry with `module_instance = (char*)module_instance + src_expr->module_offset`. That is the address of the *field* of the module
instance that holds the pointer to the import's instance, not the pointer. A `call_indirect` of the entry then calls `wrap_w2c_env_f(void* instance, ...)`, which casts its
argument to `struct w2c_env*`, so **the host function gets the wrong pointer**. (For the first field of the struct the offset is 0 and the pointer is the module instance itself.)

The `ref.func` *expression* is right: `c-writer.cc` writes `instance->w2c_<import>` for an imported function, the value of the pointer. Only the element segments are wrong.
Because the entry for a function the module defines has the offset `0`, a dereference in `funcref_table_init` for "offset != 0" would not do either (the import may be the first field).

## Reproduction

`ie.wat`:

```wat
(module
  (import "env" "f" (func $f (param i32) (result i32)))
  (type $t (func (param i32) (result i32)))
  (table 2 2 funcref)
  (elem (i32.const 0) func $f)
  (func (export "run") (param i32) (result i32) local.get 0 i32.const 0 call_indirect (type $t)))
```

```sh
wat2wasm ie.wat -o ie.wasm && wasm2c ie.wasm -o ie.c --module-name=ie
gcc -I wasm2c main.c ie.c wasm2c/wasm-rt-impl.c wasm2c/wasm-rt-mem-impl.c wasm2c/wasm-rt-exceptions-impl.c -o repro && ./repro   # main.c is attached
```

`main.c` instantiates the module with `&env` for the import and checks the pointer that its host function `w2c_env_f(struct w2c_env*, u32)` receives:

```
  host function got module instance 0x7ffd64d8f920, expected 0x55dada68c014
run(5) = 6 (expected 6); host got its own instance: NO
```

The result is right only because the host function here does not look at its first argument. A host that does (every real one: it keeps its state there) reads another structure;
in a host that dispatches through that pointer it jumps to a wrong address and crashes.

## Expected

The host function receives `&env`, the same pointer as when it is called directly.

## A fix that was tried

Give the import its own kind of entry and read the pointer the way `GlobalGet` does: in `c-writer.cc` (where `IsImport(func->name)`) write `RefImportFunc` instead of `RefFunc`, and in the
template

```c
typedef enum { RefFunc, RefNull, GlobalGet, RefImportFunc } wasm_elem_segment_expr_type_t;
...
      case RefImportFunc:
        *dest_val = (wasm_rt_funcref_t){
            src_expr->type, src_expr->func, src_expr->func_tailcallee,
            *(void**)((char*)module_instance + src_expr->module_offset)};
        break;
```

Applied by hand to the generated `ie.c` (4 lines), the reproduction prints `host got its own instance: yes`.

## How it was found

A module made by `meld fuse` (pulseengine/meld, 0.64: it fuses the components of a WebAssembly component into one core module) holds the WASI imports in a table of small thunks (35
entries, filled by an element segment) and calls them with `call_indirect`. Translated with `wasm2c` and run by a host that gets the import's state through the first argument, it crashed at
the first import call; the same module runs in V8 and, after the change above, with `wasm2c`.
