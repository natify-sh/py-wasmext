# The registry of owners (C2b/C2c): a design note

Status: **written 2026-10-28, for the owner's review; nothing of this is built.** It takes what is already decided in [TABLES_PLAN.md](TABLES_PLAN.md) ("Not built, and what it would take") and in [context_concept.md](context_concept.md) (the arena, the locking), and says in one place what the first piece of work is. What is not decided is under "Open".

## The problem, in plain words

A function reference (`funcref`) in the module is two pointers: the code (`func`) and the instance that code belongs to (`module_instance`). **Nothing tells who owns that instance.** If a function of instance A is put in a table that instance B uses, and A is dropped by Python, B calls into freed memory. So whoever receives a bare `funcref` has to find A and keep it alive. Today that is done by hand, in several places, and where it cannot be done the feature is refused.

## What exists today (read in `_gen.py` on 2026-10-28)

- Each instance has two lists: `writers` (the instances that imported a table of this one and may have put functions of their own in it; they live as long as this instance does) and `refs` (the owners of functions this instance was given as parameters).
- `Instance_keep` and `table_writers` keep those lists; `Table.get(i)` finds the owner of a slot by **scanning** the exports of the instances that use the table (the same `func` and `module_instance`).
- Two `funcref`s are equal when `func` and `module_instance` are equal; the hash is made from the same two.
- Refused, with a message: a `funcref` in the signature of an import, a `Function` called with a `funcref` parameter, `externref`, and a host function (made in Python) as a member of a table.

This works between separate stores. It is a chain of keep-alives that every new feature has to extend, and it cannot hold a function that Python itself made, since that has no instance.

## The design (decided in the documents above; this note collects it)

1. **A registry `module_instance -> owner`**, one for each interpreter, kept in the glue of each built module (not in the package `wasmext`) and **shared through a capsule** in the dictionary of the interpreter (`wasmext.owners.v1`), so that modules built apart see the same registry. For a C host it is a plain C structure.
2. An instance **writes itself in when it is made and out when it ends.** An entry is **weak**: the registry keeps nothing alive by itself.
3. Whoever receives a bare `funcref` **looks the owner up and keeps it** (in a `Function`, in `refs`). That replaces the scanning in `Table.get` and the guessing of who has to live.
4. **A host function gets a record** `HostFunction` (the callable and its type), which stands where `module_instance` stands; its `func` is a **trampoline for the type**, made at build time for each type the module declares (a type the module does not declare cannot be made, by the rule of AOT). The record is registered as an owner, so a host function is an owner like any other. An exception in the callable becomes a trap, so such a module needs `share_tables`.
5. **Locking:** one mutex (`WASMEXT_LOCK`/`WASMEXT_UNLOCK`, empty where there are no threads), taken only to look up or to add, never on the path of a call into wasm and **never held across a call outward**.
6. **Inside a store** the members are held strongly until `close` (the arena), so the chains `writers` and `refs` are not needed there. Between stores (and before C7, a store holds one module) the chains remain, now fed by the registry.

## What changes for a user

At first nothing visible: the same behaviour, found by lookup instead of by scanning. The visible change is the next piece of work (C4 and C5), which this one makes possible: a `funcref` in the signature of an import, a `Function` with a `funcref` parameter, host functions in tables, `externref`.

## The first piece of work, in small steps

Each step leaves the tests green and changes one thing.

1. **Tests that say what must hold**, before the code: an owner found for a `funcref` that came from another instance; the owner stays alive while a `funcref` of it is in a table; an entry is gone after the end of the instance; the same on every pair of front ends; the case below.
2. **The registry in the extension**, with the capsule and the lock; `Table.get` uses it. No change of behaviour; the tests of step 1 pass.
3. **The wrapper for ctypes** over the same registry (it must see the registry of the extension, and the other way round).
4. **The C library and the executable** (a plain structure).
5. **The chains retire inside a store.**

## Open

1. **A known gap that touches this** (found 2026-10-28, `tests/test_wasi_across_instances.py`, `test_a_python_callback_in_a_table_function`): the owner is an extension, the user a wrapper for ctypes, the function in the table calls a Python callback, and the call ends in `Trap: Out-of-bounds access`. It does not need WASI. The cause is **not known**; it is the first thing to look at, since it is about state that two front ends share.
2. **The invariant to prove:** an owner is never freed while any table, global or `Function` can still hold one of its `funcref`s. Between stores it rests on `writers` and `refs`; the registry must not weaken that.
3. **Reuse of an address:** an entry is removed when the instance ends; whether a new instance at the same address can meet a stale `funcref` that someone still holds is to be checked against the invariant above.
4. **The capsule across the front ends** (the extension and a wrapper loaded by ctypes) and across interpreters (sub-interpreters, free-threaded builds): designed on paper, **not tried**.
5. Whether the registry is read-only after a store is closed, and what a `funcref` of a closed store means in another store.
