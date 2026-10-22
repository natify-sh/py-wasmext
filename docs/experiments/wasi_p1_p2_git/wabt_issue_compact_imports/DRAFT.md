# Compact imports: the encoding 0x7E is decoded differently from the proposal and its spec tests

**Draft of an issue for WebAssembly/wabt (not posted).** Reproduced on 2026-10-22 with `wasm-validate` and `wasm2c` 1.0.42 (`wabt-package` 1.0.42.0, Linux x86-64). The code of `main`
(`src/binary-reader.cc`, `ReadImportSection`, read on 2026-10-22) reads the encoding in the same way.

## What the proposal says

[compact-import-section, Overview.md](https://github.com/WebAssembly/compact-import-section/blob/main/proposals/compact-import-section/Overview.md):

```
imports ::== nm1:name nm2:name externtype                                   ;; single-item encoding (existing)
           | nm1:name nm:name 0x7F list(nm2:name externtype)  -- if nm = ""  ;; compact encoding 1
           | nm1:name nm:name 0x7E externtype list(nm2:name)  -- if nm = ""  ;; compact encoding 2
```

So the encoding 2 is: the module name, an empty name, `0x7E`, **one `externtype`** (the kind and its type, for a function `0x00 typeidx`), and then a list of item names (a count, and the names). The reference
interpreter of the proposal agrees (`interpreter/binary/decode.ml`, `imports`: `let xt = externtype s in vec (fun s -> let nm = name s in Import (module_name, nm, xt))`).

## What `wasm-validate` and `wasm2c` do

They read, for `0x7E`, the **kind** (not the type), then the count, and then, for each name, the name **and a type** (`ReadImport(module_name, field_name, kind)` reads the signature index of a function). The code (1.0.42 and `main`):

```cpp
if (kind_u8 == 0x7E) {
  // Read the import kind once and re-used for each of num_compact_imports
  CHECK_RESULT(ReadExternalKind(&kind, "compact import kind", "import"));
  CHECK_RESULT(ReadCount(&num_compact_imports, "compact import count"));
  for (Index j = 0; j < num_compact_imports; ++j) {
    CHECK_RESULT(ReadStr(&field_name, "compact import field name"));
    CHECK_RESULT(ReadImport(..., field_name, kind));     // reads the type of this import
  }
}
```

That is `kind count (name type)*` where the proposal has `kind type count name*`: the type is read after the count and once for every name, instead of before the count and once. A group with no names (which the
proposal allows) is read as having a count where the type is, and a group with several names is read with a type after each.

## Reproduction

The second module of the spec test `test/core/compact-import-section/binary-compact-imports.wast` of the proposal (attached: `spec_0x7e.wasm`, 61 bytes; imports module `a` with two functions `b` and `c` of type 0 in a group of the encoding 2, after
an empty group for module `x`):

```
00 61 73 6d 01 00 00 00 01 05 01 60 00 01 7f 02 13 02 01 78 00 7e 00 00 00 01 61 00 7e 00 00 02 01 62 01 63 03 02 01 00 07 08 01 04 74 65 73 74 00 02 0a 09 01 07 00 10 00 10 01 6a 0b
```

```
$ wasm-validate --enable-compact-imports spec_0x7e.wasm
0000023: error: unfinished section (expected end: 0x24)
```

(`wasm2c --enable-compact-imports` gives the same.) The first module of that file, in the encoding 0x7F (`spec_0x7f.wasm`), is read correctly.

## Expected

The module is valid and its imports are `a.b` and `a.c`, both `(func (type 0))`; `assert_return (invoke "test") (i32.const 0xff)` in the spec test, with the modules `a` and `""` registered.

## A fix

Read the `externtype` once, then the names, then make an import for each name with the type that was read: as `ReadImport` both reads the type and makes the callbacks, it has to be split in two (read the type into a
small structure; then call `OnImport…` for each name). In the interpreter `decode.ml` it is `let xt = externtype s in vec (fun s -> Import (module_name, name s, xt))`.

## Also

- In 1.0.42 the loop was `while (i < num_imports)` where `num_imports` is the number in front of the section and `i` counts **imports**, but the proposal makes that number the number of **entries** (a group is one entry, and may
  have no imports). `main` already counts entries (`for (entry < num_entries)`). Only noticed by reading the code of 1.0.42 (not run): the loop ends as soon as that many imports are read, so an entry after a group is left unread when the number in front counts entries.
- The README of WABT has compact imports ticked for the binary format and validation, not for `wasm2c`; the bug is in the reader that all of them share.

## How it was found

Writing a reader of the import section from the proposal for another tool, and testing it on the spec modules and on the output of `wasm-validate` / `wasm2c`; the encoding 0x7F agreed, the encoding 0x7E did not.
