# The ABI between built modules: the policy

Status: **built: the number `0xXXYYZZLS`, the `floor` of a record, the declaration of the public surface with its tests, the check of the layout of the runtime when a module is built, and the link by the number of the ABI; not built: the CI against earlier releases (see "How it is checked in the CI"), the mechanism of unstable features, `griffe check`.** What the code does is in "Today" below; the other sections say, for each point, **decided**, **built** or **proposed**. The interface is alpha and nothing has been released (the first version is to be `0.0.1a1`, ABI `0x000001A1`), so what is not built can still change.

The words ABI, record, capsule are those of [README.md](../README.md) ("Public interface") and [DESIGN.md](DESIGN.md). The tables part of the ABI (the field `funcref`, the flag bit 4, the stack of entries for traps) is **provisional** ([context_concept.md](context_concept.md)); see "Unstable features".

## Today

- `WASMEXT_ABI` is one number `0xXXYYZZLS` in `src/wasmext/c/wasmext_glue.h` (now `0x000001A3`, since `0.0.1a3`; the `floor` of a record stays `0x000001A1`, the version in which each part appeared: nothing in the record changed), made of `WASMEXT_ABI_X`, `_Y`, `_Z` and `_LS`; the capsules are `wasmext.export.v0` and `wasmext.traps.v0` (only x is in the name).
- The record `wasmext_export` has `size`, `abi`, `kind`, `type`, `flags`, `owner`, `address`, `instance`, `signature`, `runtime`, `funcref`, `floor`. `floor` is set by the exporter (`wasmext_export_seal`) to the highest `WASMEXT_SINCE_*` of what the record uses. A reader checks `x == WASMEXT_ABI_X && size >= WASMEXT_EXPORT_BASE && WASMEXT_ABI >= floor` (`wasmext_export_ok`); it does not compare the layout of the runtime.
- The layout of the structs of the wasm2c runtime that modules share (`wasm_rt_memory_t`, `wasm_rt_funcref_table_t`, `wasm_rt_funcref_t`) is checked **when a module is built** (`WASMEXT_LAYOUT` in `wasmext_glue.h`): a runtime with another list of members does not build (WABT `main` is one). `WASMEXT_RUNTIME`, a number the C compiler computes from those layouts and from `wasm_rt_jmp_buf`, stays in the record and in the stack of traps as a fingerprint for the maintainers; only `wasmext_traps_use` compares it.
- `abi/current.json` declares the public surface; `tests/test_abi_declaration.py` compares it with the code and with the symbols of a built library; `tests/test_abi.py` holds a fingerprint of all the files of `src/wasmext/c/` (`_abi.py`) and fails when one changes.

What was wrong before this was built (kept as the reason for it):
- the same `WASMEXT_ABI` (then the whole number 1) did not mean the modules link, because the runtime fingerprint was compared for **equality** at link time and depends on the version of WABT. Checked on the headers: WABT 1.0.42 and `main` (commit `0086e24`, 2026-10-21) differ in `wasm_rt_memory_t` (56 and 48 bytes; `pages` at 24 and 16, `size` at 40 and 32, `is64` at 48 and 40), and are the same in `wasm_rt_funcref_table_t`, `wasm_rt_funcref_t` and `wasm_rt_jmp_buf`;
- if the fingerprint was renewed after the compatibility was checked, a module built before the renewal still refused, because the old reader compared for equality;
- the convention of the call of a function of wasm2c (the instance first, `struct wasm_multi_<codes>` for several results) is in no check (still true).

## Alpha does not keep the ABI (decided 2026-10-26)

**While the package is an alpha (`L` = `0xA`), the ABI is not kept strictly.** Everything below (the number, the `floor`, the declaration, the tests, the capsules) is the mechanism for the policy of the later versions; it is built and checked now so that it works on the day the library becomes stable (a beta at the earliest, `L` = `0xB`), but nothing in the alpha is frozen: the library changes all the time, and a stable ABI cannot be fixed while it does. In an alpha:

- a change of the public surface (the C API of a module, the record, the constants, the stub) **may break** what was built before; it does not need a new `x`, `y` or even a new serial;
- the **declaration** `abi/current.json` is still kept equal to the code: the change is made, the declaration is renewed with `python -m tests.abi_surface --update`, and `tests/test_abi_declaration.py` passes again; the file shows in a diff what the alpha changed;
- the **fingerprint** of `src/wasmext/c/` (`_abi.py`) is renewed when those files change, as before;
- the number `WASMEXT_ABI` is raised when a release is made or when two alphas must not link (a serial), not for each change;
- the rules of the next section ("What the ABI is", the table of the version) are what applies **from the first beta**; the tests of the rule (`required_bump`) keep checking that the rule itself is right.

## What the ABI is (decided)

The ABI is the **public contract between modules built apart**, and only that:

- the names of the capsules (`wasmext.export.v<X>`, `wasmext.traps.v<X>`);
- the format of the record and of the stack of entries for traps: the layout of the structs;
- the signatures of the public functions of the glue (the pointers `enter`, `leave`, `trap`, `join`; the functions of `<name>_api.h`: `<name>_export_find`, `<name>_link_*_import<j>`, `<name>_traps`, ...);
- the values: the kinds, the bits of the flags, the codes of the traps, the format of the string `signature`;
- the layout of the structs of the wasm2c runtime that modules share, as a **requirement** on WABT (see "WASMEXT_RUNTIME").

Not in it: the bodies of the functions, the C that the generator writes, the patches of the output of `wasm2c`, the version of WABT, as long as the above do not change.

## The version number (decided)

`WASMEXT_ABI` is one 32-bit number made like `PY_VERSION_HEX` of CPython: **`0xXXYYZZLS`**.

| Part | Is | Changes when |
| --- | --- | --- |
| `XX` (x) | the stable ABI | the contract is **broken**: the capsule, the signatures of the public functions or the structures change in a way a module built before cannot live with. x may break everything |
| `YY` (y) | backward compatible | something is **added**: a field at the bottom of a struct, a new function (also a test one or a preview one), a new structure. y never breaks the old; it may deprecate, or fall back to the new |
| `ZZ` (z) | patch | only fixes: of the generator, of the patches of `wasm2c`, of the dependencies (a new WABT whose compatibility was checked), nothing new |
| `L` | the level | `0xA` alpha, `0xB` beta, `0xC` release candidate, `0xF` final; `dev` is below `0xA` |
| `S` | the serial | `a1` is `0xA1`, `a2` is `0xA2`, `rc3` is `0xC3`, a final release is `0xF0` |

| Package | ABI |
| --- | --- |
| `0.0.1a1` | `0x000001A1` |
| `0.0.1a2` | `0x000001A2` |
| `0.0.1a3` | `0x000001A3` |
| `0.0.1rc1` | `0x000001C1` |
| `0.0.1` | `0x000001F0` |
| `0.0.1.post3` | `0x000001F0` (`postN` is a repackaging of the same code: the ABI is not changed) |
| `0.1.0` | `0x000100F0` |

**The first version is `0.0.1a1` (decided)**, ABI `0x000001A1`.

**The series `v0` (decided).** Inside `0.y.z` the plan is: fix bugs in what works (z) and add what does not break the compatibility (y); nothing is broken. So the rules above hold from the first version, with x = 0, and modules of any two versions of `v0` link (the unstable features below excepted). The capsule is `wasmext.export.v0` through the whole series.

**`v1.0.0` (decided): the context.** The break is planned as one step: `1.0.0` gets the context ([context_concept.md](context_concept.md)) and, with it, the changes that follow (instances bound to a context when they are made, the tables and the references reworked, the record); x becomes 1, the capsule becomes `wasmext.export.v1`, and modules of `v0` and of `v1` do not see each other, on purpose. Everything that is called provisional today (the tables, the stack of entries for traps) is allowed to change at that step and not before.

The ABI number is **not derived** from the version of the package by the build, and it is not the version of the package, but at a release the two agree in the numeric part: the number is in the header and is changed in the commit that changes the contract; on a tag, the CI is to check (not built) that the numeric part of the tag is not below the ABI, and equals it if the contract was changed in that release. A bump of the major of the package for a change that is not in the ABI (the command line, a key of `pyproject.toml`) does **not** raise x. (Taking the ABI automatically from the tag was considered: the major of the package would then break the linking of modules for a change of the command line, and the header, which is in the fingerprint of `test_abi.py`, would change with every commit.)

## The capsule and the linking rule (decided)

- The name of a capsule has **only x**: `wasmext.export.v<X>`. The name is compared for equality (`PyCapsule_IsValid`), so it cannot say "at least"; modules of another x do not see each other at all.
- A reader links when: the x of the record is its own x; its own version is not below the `floor` of the record (it understands the record); `size` covers the fields of the first version (a later field is read after a look at `size`). The layout of the runtime of wasm2c is not compared here: it is checked when a module is built.
- z takes no part in the rule (it is for messages).
- **Unstable features** (see below) are linked only when the whole version is **equal** (`LS` included), not "at least".

## The floor (built)

Two numbers of the form `0xXXYYZZLS` travel with a record: `abi` (what the exporter provides; the field exists) and `floor` (the lowest version of a **reader** that can use the record safely; a new field at the end). The floor is not written by hand: the header has a table "feature -> the version it appeared in",

```c
#define WASMEXT_SINCE_FUNC     0x000001A1   /* in the first version */
#define WASMEXT_SINCE_FUNCREF  0x000001A1   /* in the first version; unstable: it will change at 1.0.0 */
#define WASMEXT_SINCE_EXAMPLE  0x000100F0   /* what a later y would add: written when it is added */
```

and the function that makes a record sets `floor` to the highest `SINCE` of the features the record uses (for an unstable one, to its own `abi`). The importer's own "what I need" is made the same way from what it imports.

## The record: how a field is added (decided; `size` and `floor` are built)

A **field added at the bottom** of a struct (also of the capsule) does not need a new name of the capsule: an old reader sees a `size` larger than its `sizeof` and does not read the tail; a new reader looks at `size` before the new field and takes a default if it is not there; if an old reader would do wrong without the field, the exporter raises `floor` above the old reader's version and the old reader refuses with a message. The rules of the readers: never write into a record, never copy by the `sizeof` of one's own type (`min(size, own)`), never index an array of records by one's own `sizeof`, add only at the end and never into padding, never change the meaning of an existing field (that is x).

**Slots were considered and are not taken (decided).** A record of `{id, value}` slots read with an accessor (as `PyType_Slot` of the stable ABI of CPython) would take the layout away from the reader, but what it protects is a reader that does not follow the rules above, and in `v0` that is only code that this repository tests: the declaration (the next section) fails on a field that moved or changed, the `size` and the `floor` tell an old reader what it can read, and the tests of the old readers against the new writers (the CI against earlier releases, not built yet) are to check it on real code. If the record is changed for the context at `1.0.0` the question can be asked again then; nothing here prepares for it.

**Singletons of an interpreter** (`wasmext_traps`, in the dictionary of the interpreter): the first module loaded puts its struct there, so a newer module may find a shorter one; it checks `size`, then works without the new pointers or refuses because of the floor.

## Unstable features (decided; not built: there is no `UNSTABLE` flag in the code yet)

A feature in y that is not settled (the tables and the stack of entries for traps, today) is marked `UNSTABLE` for its kind of record and for its `SINCE`; it may break between any two versions that differ, and is linked only when the whole version is equal. The stable kinds (a function, a global, a memory) need only the same x and the floor. In `v0` the tables and the stack of entries are not changed in a way that breaks them either (the plan above); they are called unstable because `1.0.0` will break them, and the flag is there for a new preview feature that may still change inside `v0`.

## WASMEXT_RUNTIME (built: the role, step A and step B)

**Decided:** `WASMEXT_RUNTIME` is a **fingerprint for the maintainers**, not a gate of the contract: when it changes (a new WABT), the checks of "How it is checked" are run by hand; if the old and the new link and work, the expected value is renewed, and the ABI is left alone (z, or y if something was added) or raised (x, if it was broken). A change of the version of WABT is never released without that check.

**Built (step A):** the protection against a runtime whose layout is not the one the ABI promises is made **when a module is built**: `wasmext_glue.h` checks, with a compile-time array of size 1 or -1 (`WASMEXT_LAYOUT`), every member of `wasm_rt_memory_t`, `wasm_rt_funcref_table_t` and `wasm_rt_funcref_t`: its size and that the next member follows it with at most 8 bytes of padding. It is by relations, not numbers, so it holds on 32-bit and 64-bit platforms alike. A runtime with another member list (WABT `main` has no `data_end` and `page_size` in a memory) fails to compile, also for a toolchain given by `WASMEXT_WABT` (`tests/test_abi.py` builds the glue against such a runtime and expects the refusal). `WASMEXT_NO_LAYOUT_CHECK` turns it off.

**Built (step B):** the number compared when an export is linked is the number of the ABI: `runtime == WASMEXT_RUNTIME` is no longer in `wasmext_export_ok` (a reader checks x, the `floor` and `size`). The field `runtime` stays in the record, and `WASMEXT_RUNTIME` stays as a fingerprint for the maintainers (`tests/test_features.py` builds a module with another fingerprint and links it). One comparison is kept on purpose: the stack of traps (`wasmext_traps_use`) still compares it, because the buffer of a jump (`wasm_rt_jmp_buf`) is a type of the platform whose layout a check by relations cannot pin, and the entries of the stack are read by every module. Not done: the check by the kind of the record (a link of a function does not read the structs of a memory); with the layout checked at the build it protects nothing more.

## The declaration of the public API (built)

`abi/current.json` declares the public surface; `tests/abi_surface.py` reads the same from the code; `tests/test_abi_declaration.py` compares them.

What is in the declaration:
- the version (`WASMEXT_ABI`, the number `0xXXYYZZLS`) and the names of the two capsules;
- of `wasmext_glue.h` (`glue`) and of the `<name>_api.h` of a library (`api`): the macros with a value (not `WASMEXT_RUNTIME`, which is a fingerprint of the toolchain), the names and parameters of the macros with parameters (not their bodies), the constants of the enums, the text of each `typedef` (**a pointer to a function** too: the callback of an import), the structs with their fields **in order and as text** (the layout is the order and the text: a compiler gives the same offsets for the same text, so no offsets are computed and no compiler is needed), the opaque types (`typedef struct m_t m_t;`) and the exported functions with their signatures;
- of what the generator makes for the fixed modules of `tests/data` (`abi_surface.wat`: a function with several results, a function with a `funcref`, a memory, mutable and constant globals, an exported and an imported `funcref` table, an imported function and global; `abi_surface_more.wat`: a `v128` in a signature, a 64-bit memory, an imported memory, a tag, several results): the header (with the name of the module put back as `<name>`, so it declares the shape of the C API and not the names a user gives) and the **stub** (`.pyi`, the interface of the extension and of the wrapper for ctypes), line by line. A change of the generator that changes any of it shows as a difference;
- the reading is meant to be **complete**: every statement of a header is read or is on the short list of what is not part of the surface (a `static` function, a preprocessor line that is not a macro); any other stops the reading with its text, so a new form of declaration cannot slip by (it did once: the pointer to a function was missed).

What is not in it, on purpose: the `static` functions of the glue (every module has its own copy; nobody calls another module's), the bodies, and anything that depends on the toolchain.

The tests:
1. **The declaration against the code** (`test_the_declaration_is_the_code`): any difference, x, y or z, fails the test with a diff and the text "check the compatibility by hand, update the declaration (`python -m tests.abi_surface --update`) and set the version that fits". It was tried: a field added to `wasmext_export` fails it.
2. **What a change needs of the version** (`required_bump(old, new)`, tested on edited copies of the declaration): something removed or changed (a constant, a signature, a field moved or changed, a struct, a capsule name) needs **x**; only things added (a constant, a function, a struct, a field at the end) need **y**; the same surface needs **none**, that is z or a serial of a pre-release. A declaration from a release is compared with the one of now (`abi/<version>.json`, copied on a tag): `test_the_snapshots_of_the_releases_fit_the_version`, **skipped until there is a release**. It compares the number as a whole today; when the version is `0xXXYYZZLS` it will compare the parts.
3. Besides, the **fingerprint of all the files of `c/`** stays (`tests/test_abi.py`, `_abi.py`): it fails on a change that the declaration does not see (a fix inside a function), which then needs at least z or a serial.


Not built: the Python side of the build (`natify`, the options; `griffe check` is the tool to try; the stub is covered above). What version a change needs is decided by the maintainer; nothing enforces a bump of a released version.

## How it is checked in the CI (proposed)

1. **Snapshots of the header (each commit).** At each release the public part of the header is kept (`tests/abi/<version>/wasmext_glue.h`); a test builds a C program in which an "old reader" (compiled against the snapshot) reads a record of the "new writer" (the current header) and the other way round, and checks sizes, offsets and the signatures of the pointers.
2. **The old wasmext against the new (each pull request; always on a tag).** The CI installs the earlier released versions (`pip install wasmext==<version>`) into separate environments, builds fixture modules with them, builds the same with the current one, and links them in one process **both ways**: a function, a global, a memory with `grow`, a table, a trap through a link; and calls them. Linking alone is not enough: a layout can match and the behaviour not. Before the first release this layer compares the current wasmext with itself.
3. **The matrix of WABT (built in part).** `wabt-package` has one release today (1.0.42.0), so there is no second released version to put in a matrix. What exists is a canary for the next one: the workflow `.github/workflows/wabt-main.yml` (once a week and by hand, **not** a check of a pull request) builds WABT from its main branch, makes a `WASMEXT_WABT` directory of it and runs `tests/test_abi.py`, whose test `test_the_runtime_of_the_toolchain_has_the_layout_of_the_abi` fails when the layout of the runtime is not the one the glue checks. **Today it is red, and that is the finding:** WABT `main` (checked at `0086e24`, built and run by hand) has a memory without `data_end` and `page_size` (48 bytes where 1.0.42 has 56), so a module cannot be built with it; the compiler names the member. A red run is the signal for a maintainer to decide: support both layouts (the glue would have to read a memory in a way that holds for both), or keep to the WABT of the wabt-package. When a second release of the wabt-package appears it goes into the matrix of the ordinary jobs, with the oldest supported one.
4. All three systems (Linux, macOS, Windows), because the compiler and the platform enter the layout.

## Tools that exist (status in this repository)

- `abidiff` and `abidw` of libabigail, `abi-compliance-checker`: compare an ABI of the C libraries (ELF and headers). **Not available in the environment where this was written; not tried.** Their limit here: the glue is mostly `static inline` in headers, so a binary shows little of it.
- `griffe check` (compares the public Python API with an earlier tag by the rules of semver): installed in that environment (`uv tool install griffe`), **not run on this repository**. It would cover the Python side (`natify`, `Instance`, the classes), not the capsules or the C.
- The own declaration above covers the capsules and the structs, which these tools do not know.

## Open

- What counts as "a feature" for `SINCE` and `UNSTABLE`. (The table of `SINCE` lives in the header, `WASMEXT_SINCE_*`; a per-item `since` in the declaration and a target macro like `Py_LIMITED_API` were considered and are not taken for now: in `0.0.1` every item has the same version, so they would say nothing.)
