# Custom page sizes: options (a concept)

Status: **a concept, nothing is built.** The way the page size is told to Python and C was decided earlier (it is in [FEATURES.md](FEATURES.md), "Custom page sizes", and is repeated
below); what is *not* decided is how much of it to build and when. This page puts the facts and the ways in one place, so that the work does not start from nothing.

How a fact is known: **[run]** run in a session of this repository (WABT 1.0.42 from `wabt-package`, 2026-10-22), **[read]** read in source code or documentation, **[estimate]** a
judgement, not tried. The proposal was read in the repository `WebAssembly/custom-page-sizes` (commit `61c873a`, 2026-09-29): `proposals/custom-page-sizes/Overview.md` and the spec
tests in `test/core/custom-page-sizes/`. The lesson of [compact imports](FEATURES.md) is applied: the specification is read **before** the behaviour of `wasm2c` is taken as the model, because
WABT 1.0.42 reads the compact import forms differently from the proposal.

## What the proposal says

- A memory type gets a page size. Only two values are valid: **1 byte and 64 KiB** (65536); the encoding is built so that any power of two up to 65536 could be allowed later **[read]**.
- **Binary:** the byte of flags of `limits` gets a bit `0x08`. When it is set, a `u32` **`p`** follows the limits and the page size is `2**p` (`p < 64`). The combinations `0x08`–`0x0F`
  are those of `0x00`–`0x07` (maximum present, shared, 64-bit index) with the new bit. Validation allows only `p = 0` (1 byte) and `p = 16` (64 KiB; written out, it is the default) **[read]**.
- **Text:** `(memory 4 8 (pagesize 1))`; a page size that is not a power of two is malformed, a power of two other than 1 and 65536 is invalid **[read]**, tests in `custom-page-sizes-invalid.wast`.
- The limits, `memory.size` and `memory.grow` stay **in pages of the memory's own size**; no new instruction. Memory type matching needs the **exact same page size**; there is no
  subtyping between sizes **[read]**.
- The limits must fit `2**32 / pagesize` pages (for 1-byte pages of a 32-bit memory that is just under 4 GiB), so the index type is not changed by the page size **[read]**.
- A module may have several memories with different page sizes **[read]**.

## What the tools do

- `wasm2c --enable-custom-page-sizes` translates it: for `(memory 4 8 (pagesize 1))` it writes `wasm_rt_allocate_memory(&mem, 4, 8, 0, 1)`, the last argument being the page size **in
  bytes** **[run]**. The table in the README of WABT has a tick in the column of `wasm2c` for the proposal (and none for function references or compact imports) **[read]**.
- The flag does not change the C of an ordinary module: the C of a module with 64 KiB pages came out the same with the flag as without it (as with compact imports) **[run]**. So the
  flag can be passed always.
- The runtime has the field `page_size` in `wasm_rt_memory_t` **[read]**, and the layout check of wasmext already looks at it (`WASMEXT_LAYOUT` in `wasmext_glue.h`).
- A memory that is not "default 32" (64 KiB pages and a 32-bit index) is **not given guard pages** by the runtime (`wasm_rt_memory_is_default32` in `wasm-rt-mem-impl-helper.inc`), and the
  generated C checks the bounds of its accesses in code (the macros in the C of `wasm2c` have a variant for the default-32 memory that "may do nothing at all" with guard pages and one for the others)
  **[read]**. So a memory with 1-byte pages is safe in a build with guard pages, and its accesses are slower than those of an ordinary memory; the other memories of the module keep guard pages **[estimate]**.
- Not tested here: whether the bounds-checked variant is also chosen for an *imported* memory whose page size the module cannot know when it is translated (the C has a comment about
  "imported or exported" memories); the spec test `custom-page-sizes.wast` imports and exports both sizes.

## What wasmext does today

- The reader refuses it (`_wasm.py`, `limits`: bit `0x08`) with the message *"… wasm2c has no such memory"*. **That message is wrong now**: `wasm2c` has it, behind a flag; it is wasmext that does not
  **[read]**.
- `Limits` has no page size; its comment says "pages (64 KiB)". The exported `memoryview` is made from the size **in bytes** (`mem->size`), so it is right for any page size already; the code
  that keeps a buffer alive while a memory could move already treats another page size as a memory that can move (`memory_can_move`, which tests `page_size != WASM_DEFAULT_PAGE_SIZE`)
  **[read]**.
- The check when a memory is linked (`_gen.py`, and the library in `_shared.py`) compares `mem->pages` with the minimum and `mem->max_pages` with the maximum of the importer; both are page
  counts, so the sizes of the page of the two memories have to be compared **first** **[read]**.
- `inspect` prints the limits in "pages" **[read]**.

## Decided earlier: how the page size is told

It is a property of the type of the memory of a module, known when the C is made, not of an instance (from [FEATURES.md](FEATURES.md)):
- C: `#define <NAME>_MEMORY_<MEM>_PAGE_SIZE` in `<name>_api.h`;
- Python: a constant of the module, `module.__memory_page_sizes__ = {"mem": 65536}` (a dunder name, which cannot clash with an export), typed in the `.pyi` and the same in the wrapper for ctypes;
- linking a memory with another page size is a `LinkError`.

Nothing of this is built.

## The ways

### A. The smallest useful step

1. The reader takes the bit `0x08` and `p`, checks `p` is 0 or 16 (and `p < 64`), and keeps the page size in `Limits` (in bytes, with 65536 as the default).
2. `wasm2c` is given `--enable-custom-page-sizes`.
3. A link between two memories compares the page sizes first (`mem->page_size`, a field the importer already has a pointer to), and a difference is a `LinkError`; the messages count
   in pages of the memory's own size.
4. `inspect` says the page size when it is not 64 KiB; the message of the refusal that remains (shared memory, other sizes) is made true.

No change in the ABI, since the page size is read from the runtime's own memory struct, which the layout check already covers **[estimate]**. Python sees a `memoryview` of bytes as before;
the constant `__memory_page_sizes__` and the `#define` are left for the day somebody needs to read the page size from the outside.

### B. All of it as decided earlier

A, and the constant for Python (the extension, the wrapper for ctypes, the `.pyi`) and the `#define` in the C API. The `#define` is a new constant of the public surface, so it is a change
that [abi_policy.md](abi_policy.md) and `abi/current.json` / `tests/test_abi_declaration.py` have to follow (a new constant is an addition, not a break; the exact bump to be read there).
More files change and the tests of the four front ends are needed, but it is the whole of what was designed.

### C. Only make the refusal true

Change the message so that it says *"the module has a custom page size: `wasm2c` can translate it with a flag, wasmext does not support it yet"*, and build nothing. Cost: a line. It
removes the false statement whatever else is chosen.

### D. Rewrite to 64 KiB pages

Not possible: `memory.size` and `memory.grow` return page counts, and a 1-byte page memory of 4 bytes would have to look as 4 pages, not 0. Not an option.

## What I would choose (a recommendation, not a decision)

C immediately (it corrects a false message), then A when a module needs it, and B only if somebody has to read the page size from Python or from C. The reason: Python already gets the bytes
it wants, and the page size is only needed to read the `memory.size` that a function of the module returns.

## Tests when it is built

- A module with `(pagesize 1)`: `memory.size`, `memory.grow` (counts of bytes), the exported `memoryview` of 4 bytes, an access one byte past the end traps; an explicit `(pagesize 65536)`
  (the same as the default); a 64-bit memory with 1-byte pages; two memories of different sizes in one module.
- A memory imported with the other page size is a `LinkError`; with the same size it is shared, and `grow` is seen by both.
- The modules and the invalid cases of the proposal's own tests (`custom-page-sizes.wast`, `custom-page-sizes-invalid.wast`, `memory_max.wast`, `memory_max_i64.wast`): the binary ones taken to the
  reader of wasmext as it was done for compact imports, and the results of `wasm2c` **compared with the proposal**, not the other way round.
- In the extension, the library, the program and `wasmimport` (as `tests/test_compact_imports.py` does), and `inspect`.
- The speed of an access to a 1-byte-page memory against an ordinary one: not measured; a note in [FEATURES.md](FEATURES.md) when it is.

## To find out before choosing

1. Is the bounds-checked variant used for an imported memory in a build with guard pages (see "What the tools do")? A test with two modules and a 1-byte page memory shared between them answers it.
2. Does any real producer emit the proposal's memories (small embedded targets, state machines in the motivation)? A consumer decides whether A is worth doing.
3. Whether the set of valid sizes is final: the text read here says "exactly two valid page sizes" and that it may be relaxed to any power of two up to 65536 later, which the binary form (`p` as a power) already allows.
