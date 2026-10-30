"""Step 3a of layer 1 (docs/specs/S0003-instances.md): the instance and the binding of a module, tested as plain C (tests/c/) over a real wasm2c module.
The C of the descriptor and of the binding is made by wasmext from the model; nothing of Python is in the program that runs."""

# pyright: reportPrivateUsage=false
from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest
from fusedwasi import get_include

from wasmext import parse
from wasmext._binding import generate_binding
from wasmext._descriptor import generate_descriptor
from wasmext._gen import module_prefix  # pyright: ignore[reportPrivateUsage]
from wasmext._model import build_model
from wasmext._natify import (  # pyright: ignore[reportPrivateUsage]
    _RUNTIME_WRAPPERS,
    _export_tags,
    _portable,
    _repair_imported_elements,
    _repair_tail_calls,
)
from wasmext._toolchain import find_toolchain  # pyright: ignore[reportPrivateUsage]

from .c_build import compile_c, supports_flag
from .conftest import SANITIZED

HERE = Path(__file__).parent
C_DIR = HERE / "c"
WASMEXT_C = HERE.parent / "src" / "wasmext" / "c"
EXE = ".exe" if os.name == "nt" else ""

OPS = """(module
  (memory (export "mem") 1)
  (func (export "add") (param i32 i32) (result i32) local.get 0 local.get 1 i32.add)
  (func (export "div") (param i32 i32) (result i32) local.get 0 local.get 1 i32.div_s)
  (func (export "swap") (param i32 i64) (result i64 i32) local.get 1 local.get 0)
  (func (export "nothing"))
  (func (export "mix") (param f32 f64) (result f64) local.get 0 f64.promote_f32 local.get 1 f64.add)
  (global $g (mut i32) (i32.const 5))
  (func (export "g") (result i32) global.get $g)
  (func $s global.get $g i32.const 1 i32.add global.set $g)
  (start $s))"""
SIMD = """(module (func (export "double") (param v128) (result v128) local.get 0 local.get 0 i32x4.add))"""
IMPORTS = """(module
  (import "vec" "inc" (func $inc (param v128) (result v128)))  ;; the modules are not in the order of their names: wasm2c sorts them
  (import "env" "f" (func $f (param i32 i64) (result i32)))
  (import "env" "multi" (func $m (param f32) (result i32 f64)))
  (import "env" "log" (func $log (param i32)))
  (import "env" "again" (func $again (param i32) (result i32)))
  (import "env" "again0" (func $again0 (param i32)))
  (func (export "run") (param i32) (result i32) local.get 0 i64.const 7 call $f)
  (func (export "twice") (param f32) (result i32 f64) local.get 0 call $m)
  (func (export "say") (param i32) local.get 0 call $log)
  (func (export "vec") (param v128) (result v128) local.get 0 call $inc)
  (func (export "viaagain") (param i32) (result i32) local.get 0 call $again)
  (func (export "viaagain0") (param i32) local.get 0 call $again0)
  (func (export "add") (param i32 i32) (result i32) local.get 0 local.get 1 i32.add)
  (func (export "div") (param i32 i32) (result i32) local.get 0 local.get 1 i32.div_s)
  (func $start i32.const 99 call $log)
  (start $start))"""
WASI1 = """(module
  (import "wasi_snapshot_preview1" "fd_write" (func $fd_write (param i32 i32 i32 i32) (result i32)))
  (import "wasi_snapshot_preview1" "proc_exit" (func $proc_exit (param i32)))
  (import "wasi_snapshot_preview1" "proc_raise" (func $proc_raise (param i32) (result i32)))
  (import "wasi_snapshot_preview1" "args_sizes_get" (func $args_sizes_get (param i32 i32) (result i32)))
  (import "wasi_snapshot_preview1" "environ_sizes_get" (func $environ_sizes_get (param i32 i32) (result i32)))
  (import "wasi_snapshot_preview1" "clock_time_get" (func $clock_time_get (param i32 i64 i32) (result i32)))
  (import "wasi_snapshot_preview1" "random_get" (func $random_get (param i32 i32) (result i32)))
  (memory (export "memory") 1)
  (data (i32.const 16) "hi\\0a")
  (data (i32.const 32) "\\10\\00\\00\\00\\03\\00\\00\\00")  ;; an iovec: pointer 16, length 3
  (func (export "hello") (result i32) i32.const 1 i32.const 32 i32.const 1 i32.const 64 call $fd_write)
  (func (export "exit") (param i32) local.get 0 call $proc_exit)
  (func (export "raise") (param i32) (result i32) local.get 0 call $proc_raise)
  (func (export "argc") (result i32) i32.const 128 i32.const 132 call $args_sizes_get drop i32.const 128 i32.load)
  (func (export "environc") (result i32) i32.const 128 i32.const 132 call $environ_sizes_get drop i32.const 128 i32.load)
  (func (export "time") (result i64) i32.const 0 i64.const 1 i32.const 160 call $clock_time_get drop i32.const 160 i64.load)
  (func (export "random") (result i32) i32.const 192 i32.const 4 call $random_get drop i32.const 192 i32.load))"""
WASI2 = """(module
  (import "wasi:cli/exit@0.2.0" "exit" (func $exit (param i32)))
  (import "wasi:clocks/monotonic-clock@0.2.0" "now" (func $now (result i64)))
  (import "wasi:random/random@0.2.0" "get-random-u64" (func $rand (result i64)))
  (import "wasi:cli/environment@0.2.0" "get-arguments" (func $args (param i32)))
  (import "wasi:cli/stdout@0.2.0" "get-stdout" (func $stdout (result i32)))
  (import "wasi:io/streams@0.2.0" "[method]output-stream.blocking-write-and-flush" (func $write (param i32 i32 i32 i32)))
  (memory (export "memory") 1)
  (data (i32.const 16) "hi\\0a")
  (global $heap (mut i32) (i32.const 4096))
  (func (export "cabi_realloc") (param i32 i32 i32 i32) (result i32) (local $p i32)
    global.get $heap local.get 2 i32.add i32.const 1 i32.sub i32.const 0 local.get 2 i32.sub i32.and local.tee 4
    local.get 3 i32.add global.set $heap
    local.get 4)
  (func (export "exit") (param i32) local.get 0 call $exit)
  (func (export "now") (result i64) call $now)
  (func (export "rand") (result i64) call $rand)
  (func (export "argc") (result i32) i32.const 256 call $args i32.const 260 i32.load)
  (func (export "hello") (result i32) call $stdout i32.const 16 i32.const 3 i32.const 512 call $write i32.const 512 i32.load8_u))"""
MEMORY_GLOBALS = """(module
  (memory (export "mem") 1 4)
  (data (i32.const 8) "wasm")
  (global $gm (export "gm") (mut i32) (i32.const 5))
  (global (export "gc") i64 (i64.const 9))
  (global (export "gf") (mut f32) (f32.const 1.5))
  (global (export "gd") (mut f64) (f64.const 2.5))
  (global (export "gv") (mut v128) (v128.const i32x4 1 2 3 4))
  (func (export "grow") (param i32) (result i32) local.get 0 memory.grow)
  (func (export "load") (param i32) (result i32) local.get 0 i32.load8_u)
  (func (export "store") (param i32 i32) local.get 0 local.get 1 i32.store8)
  (func (export "bump") (result i32) global.get $gm i32.const 1 i32.add global.set $gm global.get $gm))"""
MEMORY64 = """(module
  (memory (export "mem") i64 1 4)
  (func (export "grow") (param i32) (result i32) local.get 0 i64.extend_i32_u memory.grow i32.wrap_i64)
  (func (export "load") (param i32) (result i32) local.get 0 i64.extend_i32_u i32.load8_u)
  (func (export "store") (param i32 i32) local.get 0 i64.extend_i32_u local.get 1 i32.store8))"""
LINK_MODULES = {
    "lib": """(module
  (memory (export "mem") 1 4)
  (global $counter (export "counter") (mut i32) (i32.const 10))
  (global (export "ver") i64 (i64.const 7))
  (func (export "add") (param i32 i32) (result i32) local.get 0 local.get 1 i32.add)
  (func (export "div") (param i32 i32) (result i32) local.get 0 local.get 1 i32.div_s)
  (func (export "swap") (param i32 i64) (result i64 i32) local.get 1 local.get 0)
  (func (export "vec") (param v128) (result v128) local.get 0 local.get 0 i32x4.add)
  (func (export "log") (param i32))
  (func (export "get_counter") (result i32) global.get $counter))""",
    "app": """(module
  (import "libx" "add" (func $add (param i32 i32) (result i32)))
  (import "libx" "div" (func $div (param i32 i32) (result i32)))
  (import "libx" "swap" (func $swap (param i32 i64) (result i64 i32)))
  (import "libx" "vec" (func $vec (param v128) (result v128)))
  (import "libx" "mem" (memory 1 4))
  (import "libx" "counter" (global $counter (mut i32)))
  (import "libx" "ver" (global $ver i64))
  (import "env" "k" (global $k i32))
  (func (export "call_add") (param i32 i32) (result i32) local.get 0 local.get 1 call $add)
  (func (export "call_div") (param i32 i32) (result i32) local.get 0 local.get 1 call $div)
  (func (export "call_swap") (param i32 i64) (result i64 i32) local.get 0 local.get 1 call $swap)
  (func (export "call_vec") (param v128) (result v128) local.get 0 call $vec)
  (func (export "peek") (param i32) (result i32) local.get 0 i32.load8_u)
  (func (export "poke") (param i32 i32) local.get 0 local.get 1 i32.store8)
  (func (export "inc") (result i32) global.get $counter i32.const 1 i32.add global.set $counter global.get $counter)
  (func (export "get_ver") (result i64) global.get $ver)
  (func (export "get_k") (result i32) global.get $k)
  (func (export "grow") (param i32) (result i32) local.get 0 memory.grow))""",
    "tiny": '(module (memory (export "mem") 0 4))',
    "big": '(module (memory (export "mem") 1 8))',
}
TABLE_MODULES = {
    "owner": """(module
  (type $t (func (result i32)))
  (type $add (func (param i32 i32) (result i32)))
  (table $tab (export "tab") 4 8 funcref)
  (func $seven (export "seven") (result i32) i32.const 7)
  (func (export "bad") (result i32) unreachable)
  (func (export "one") (param i32) (result i32) local.get 0)
  (func (export "call") (param i32) (result i32) local.get 0 call_indirect (type $t))
  (func (export "size") (result i32) table.size $tab)
  (func (export "grow") (param i32) (result i32) ref.null func local.get 0 table.grow $tab)
  (func (export "add") (param i32 i32) (result i32) local.get 0 local.get 1 i32.add)
  (func (export "swap") (param i32 i64) (result i64 i32) local.get 1 local.get 0)
  (func (export "mix") (param f32 f64) (result f64) local.get 0 f64.promote_f32 local.get 1 f64.add)
  (func (export "nothing"))
  (func (export "vec") (param v128) (result v128) local.get 0 local.get 0 i32x4.add)
  (func (export "calladd") (param i32 i32 i32) (result i32) local.get 1 local.get 2 local.get 0 call_indirect (type $add))
  (func (export "ident") (param funcref) (result funcref) local.get 0)
  (func (export "pair") (param funcref funcref) (result funcref funcref) local.get 1 local.get 0)
  (func (export "isnull") (param funcref) (result i32) local.get 0 ref.is_null)
  (func (export "get") (param i32) (result funcref) local.get 0 table.get $tab)
  (func (export "put") (param i32 funcref) local.get 0 local.get 1 table.set $tab)
  (elem (i32.const 0) $seven))""",
    "user": """(module
  (type $t (func (result i32)))
  (import "own_u" "tab" (table $tab 2 funcref))
  (func $nine (export "nine") (result i32) i32.const 9)
  (func (export "add") (param i32 i32) (result i32) local.get 0 local.get 1 i32.add i32.const 100 i32.add)
  (func (export "div") (param i32 i32) (result i32) local.get 0 local.get 1 i32.div_s)
  (func (export "swap") (param i32 i64) (result i64 i32) local.get 1 local.get 0)
  (func (export "mix") (param f32 f64) (result f64) local.get 1 local.get 0 f64.promote_f32 f64.sub)
  (func (export "nothing"))
  (func (export "vec") (param v128) (result v128) local.get 0)
  (func (export "mul4") (param i32 i32 i32 i32) (result i32) local.get 0 local.get 1 i32.mul local.get 2 i32.mul local.get 3 i32.mul)
  (elem (i32.const 1) $nine)
  (func (export "call") (param i32) (result i32) local.get 0 call_indirect $tab (type $t))
  (func (export "size") (result i32) table.size $tab))""",
    "trapper": """(module
  (import "own_t" "tab" (table $tab 2 funcref))
  (func $ten (result i32) i32.const 10)
  (elem (i32.const 3) $ten)
  (func $boom unreachable)
  (start $boom))""",
    "hostf": """(module
  (import "env" "visit" (func $visit (param funcref) (result funcref)))
  (func (export "via") (param funcref) (result funcref) local.get 0 call $visit)
  (func (export "tell") (param funcref)  local.get 0 drop))""",
    "strict": '(module (import "own_s" "tab" (table 8 funcref)) (func (export "f")))',
    "capped": '(module (import "own_c" "tab" (table 1 2 funcref)) (func (export "f")))',
}
EXTERN_MODULES = {
    "xr": """(module
  (import "xenv" "visit" (func $visit (param externref) (result externref)))
  (func (export "id") (param externref) (result externref) local.get 0)
  (func (export "pair") (param externref externref) (result externref externref) local.get 1 local.get 0)
  (func (export "isnull") (param externref) (result i32) local.get 0 ref.is_null)
  (func (export "via") (param externref) (result externref) local.get 0 call $visit)
  (func (export "mixed") (param i32 externref f64) (result f64 externref) local.get 2 local.get 1)
  (table $t (export "t") 4 8 externref)
  (func (export "tget") (param i32) (result externref) local.get 0 table.get $t)
  (func (export "tset") (param i32 externref) local.get 0 local.get 1 table.set $t)
  (func (export "tsize") (result i32) table.size $t)
  (func (export "tgrow") (param i32) (result i32) ref.null extern local.get 0 table.grow $t))""",
    "xu": """(module
  (import "xown" "t" (table $t 2 externref))
  (func (export "tget") (param i32) (result externref) local.get 0 table.get $t)
  (func (export "tset") (param i32 externref) local.get 0 local.get 1 table.set $t)
  (func (export "tsize") (result i32) table.size $t))""",
    "xt": '(module (import "xtown" "t" (table 2 externref)) (func $boom unreachable) (start $boom))',
    "xf": '(module (import "xfown" "t" (table 1 funcref)) (func (export "f")))',
    "xs": '(module (import "xsown" "t" (table 8 externref)) (func (export "f")))',
    "xc": '(module (import "xcown" "t" (table 1 2 externref)) (func (export "f")))',
}
REF_LINK_MODULES = {
    "rlib": """(module
  (type $t (func (result i32)))
  (table $tab (export "tab") 4 8 funcref)
  (func $seven (export "seven") (result i32) i32.const 7)
  (func (export "fident") (param funcref) (result funcref) local.get 0)
  (func (export "eident") (param externref) (result externref) local.get 0)
  (func (export "mixed") (param i32 funcref externref i64) (result externref i64 funcref i32) local.get 2 local.get 3 local.get 1 local.get 0)
  (func (export "getf") (result funcref) ref.func $seven)
  (func (export "boom") (param externref) (result externref) unreachable)
  (func (export "isnull") (param funcref) (result i32) local.get 0 ref.is_null)
  (func (export "mfr") (result funcref i32) ref.func $seven i32.const 1))""",
    "rapp": """(module
  (type $t (func (result i32)))
  (import "libr" "fident" (func $fi (param funcref) (result funcref)))
  (import "libr" "eident" (func $ei (param externref) (result externref)))
  (import "libr" "mixed" (func $mx (param i32 funcref externref i64) (result externref i64 funcref i32)))
  (import "libr" "getf" (func $gf (result funcref)))
  (import "libr" "boom" (func $bm (param externref) (result externref)))
  (import "libr" "isnull" (func $isn (param funcref) (result i32)))
  (import "libr" "mfr" (func $mfr (result funcref i32)))
  (table $tab (export "tab") 4 8 funcref)
  (func $nine (export "nine") (result i32) i32.const 9)
  (func (export "fi") (param funcref) (result funcref) local.get 0 call $fi)
  (func (export "ei") (param externref) (result externref) local.get 0 call $ei)
  (func (export "mx") (param i32 funcref externref i64) (result externref i64 funcref i32) local.get 0 local.get 1 local.get 2 local.get 3 call $mx)
  (func (export "gf") (result funcref) call $gf)
  (func (export "bm") (param externref) (result externref) local.get 0 call $bm)
  (func (export "isn") (param funcref) (result i32) local.get 0 call $isn)
  (func (export "fnine") (result funcref) ref.func $nine call $fi)
  (func (export "mf") (result funcref i32) call $mfr)
  (func (export "callslot") (param i32) (result i32) local.get 0 call_indirect (type $t)))""",
    "rbad": """(module
  (import "libb" "eident" (func (param funcref) (result funcref)))
  (import "libb2" "fident" (func (param externref) (result externref)))
  (func (export "f")))""",
}
REF_GLOBAL_MODULES = {
    "rg": """(module
  (type $t0 (func (result i32)))
  (table $t 1 funcref)
  (global $gx (export "gx") (mut externref) (ref.null extern))
  (global $gf (export "gf") (mut funcref) (ref.null func))
  (func $f (export "f") (result i32) i32.const 5)
  (func (export "setgf") ref.func $f global.set $gf)
  (func (export "callgf") (result i32) i32.const 0 global.get $gf table.set $t i32.const 0 call_indirect (type $t0))
  (func (export "getgx") (result externref) global.get $gx)
  (func (export "setgx") (param externref) local.get 0 global.set $gx))""",
    "ri": """(module
  (type $t0 (func (result i32)))
  (import "gown" "gx" (global $gx (mut externref)))
  (import "gown" "gf" (global $gf (mut funcref)))
  (import "genv" "ix" (global $ix externref))
  (import "genv" "if" (global $if funcref))
  (table $t 1 funcref)
  (func $g (export "g") (result i32) i32.const 7)
  (func (export "getgx") (result externref) global.get $gx)
  (func (export "setgx") (param externref) local.get 0 global.set $gx)
  (func (export "setgf") ref.func $g global.set $gf)
  (func (export "callgf") (result i32) i32.const 0 global.get $gf table.set $t i32.const 0 call_indirect (type $t0))
  (func (export "getix") (result externref) global.get $ix)
  (func (export "getif") (result funcref) global.get $if))""",
    "rt": """(module
  (import "gtown" "gf" (global $gf (mut funcref)))
  (func $h (export "h") (result i32) i32.const 9)
  (func $s ref.func $h global.set $gf unreachable)
  (start $s))""",
}
TAG_MODULES = {
    "ta": """(module
  (type $f (func))
  (tag $t (param i32 i64))
  (table $tab (export "tab") 2 funcref)
  (export "t" (tag $t))
  (func $thrower (type $f) i32.const 7 i64.const 9 throw $t)
  (elem (i32.const 0) $thrower)
  (func (export "call_slot") (param i32) local.get 0 call_indirect (type $f)))""",
    "tb": """(module
  (type $f (func))
  (import "tgx" "t" (tag $t (param i32 i64)))
  (import "tgy" "tab" (table $tab 2 funcref))
  (func (export "catch_slot") (param i32) (result i32 i64)
    (block $h (result i32 i64)
      (try_table (catch $t $h)
        local.get 0 call_indirect (type $f))
      i32.const -1 i64.const -1))
  (func (export "call_slot") (param i32) local.get 0 call_indirect (type $f)))""",
    "tc": """(module
  (type $f (func))
  (import "tgyc" "tab" (table $tab 2 funcref))
  (tag $t (param i32 i64))
  (export "t" (tag $t))
  (func (export "catch_slot") (param i32) (result i32 i64)
    (block $h (result i32 i64)
      (try_table (catch $t $h)
        local.get 0 call_indirect (type $f))
      i32.const -1 i64.const -1))
  (tag $priv)
  (func (export "throw_priv") throw $priv)
  (func (export "self_catch") (result i32)
    (block $h (result i32 i64)
      (try_table (catch $t $h) i32.const 11 i64.const 1 throw $t)
      i32.const -1 i64.const -1)
    drop))""",
    "th": """(module
  (import "tenv" "h" (func $h))
  (tag $t (param i32 i64))
  (export "t" (tag $t))
  (tag $p (param i32))
  (func (export "throw_p") (param i32) local.get 0 throw $p)
  (func (export "catch_p") (result i32)
    (block $b (result i32)
      (try_table (catch $p $b) call $h)
      i32.const -1))
  (func (export "run") (result i32 i64)
    (block $b (result i32 i64)
      (try_table (catch $t $b) call $h)
      i32.const -1 i64.const -1))
  (func (export "plain") call $h))""",
    "td": """(module (tag $t (param i32 i64)) (export "t" (tag $t)) (func (export "f")))""",
    "te": """(module (import "tgz" "t" (tag (param i32))) (func (export "f")))""",
}
# 8a-3 (S0008): tags made by the host. Every import module name is its own (an imported tag is a global of the program, one for each name)
_HSELF = """(module
  (import "{g}" "t" (tag $t (param i32 i64)))
  (func (export "self_catch") (result i32)
    (block $h (result i32 i64)
      (try_table (catch $t $h) i32.const 11 i64.const 1 throw $t)
      i32.const -1 i64.const -1)
    drop))"""
HOST_TAG_MODULES = {
    "ha": """(module
  (type $f (func))
  (import "hga" "t" (tag $t (param i32 i64)))
  (table $tab (export "tab") 2 funcref)
  (func $thrower (type $f) i32.const 7 i64.const 9 throw $t)
  (elem (i32.const 0) $thrower)
  (func (export "call_slot") (param i32) local.get 0 call_indirect (type $f))
  (func (export "throw_it") i32.const 5 i64.const 6 throw $t))""",
    "hb": """(module
  (type $f (func))
  (import "hgb" "t" (tag $t (param i32 i64)))
  (import "hgbt" "tab" (table $tab 2 funcref))
  (func (export "catch_slot") (param i32) (result i32 i64)
    (block $h (result i32 i64)
      (try_table (catch $t $h)
        local.get 0 call_indirect (type $f))
      i32.const -1 i64.const -1)))""",
    "hh": """(module
  (import "henv" "h" (func $h))
  (import "hgh" "t" (tag $t (param i32 i64)))
  (func (export "run") (result i32 i64)
    (block $b (result i32 i64)
      (try_table (catch $t $b) call $h)
      i32.const -1 i64.const -1)))""",
    "hs": """(module (import "hgs" "t" (tag (param i32))) (func (export "f")))""",
    "hx": _HSELF.replace("{g}", "hgx"),
    "hy": _HSELF.replace("{g}", "hgy"),
    "hz": _HSELF.replace("{g}", "hgz"),
    "ta": TAG_MODULES["ta"],
    "tb": TAG_MODULES["tb"],
}
NO_MEMORY = """(module (memory i64 4294967296) (func (export "f")))"""
START_TRAP = """(module (func $s unreachable) (start $s) (func (export "f") (result i32) i32.const 1))"""


@pytest.fixture(scope="module")
def build(wabt: Path, tmp_path_factory: pytest.TempPathFactory) -> Callable[..., Path]:
    """Builds a C test against modules: wat -> wasm -> wasm2c -> the descriptor and the binding of wasmext -> the test and the runtime. `wat` is one module, or a dict
    {name: wat} for several that the test links to each other; `host` is the host of all of them."""
    out = tmp_path_factory.mktemp("instance")
    toolchain = find_toolchain()
    runtime = toolchain.runtime
    simde = [toolchain.include] if toolchain.include is not None and (toolchain.include / "simde").is_dir() else []

    def run(
        wat: str | dict[str, str],
        name: str,
        test: str,
        flags: Sequence[str] = (),
        host: str = "wasm32",
        defines: Sequence[str] = (),
    ) -> Path:
        modules = wat if isinstance(wat, dict) else {name: wat}
        sources = [C_DIR / test]
        for module, text in modules.items():
            (out / f"{module}.wat").write_text(text, encoding="utf-8")
            wasm = out / f"{module}.wasm"
            subprocess.run([wabt / "bin" / "wat2wasm", out / f"{module}.wat", "-o", wasm], check=True)
            subprocess.run(
                [wabt / "bin" / "wasm2c", wasm, "-o", out / f"{module}_w2c.c", f"--module-name={module}"], check=True
            )
            # the C is what the product builds (_prepare of _natify): the repairs of what wasm2c writes, and the table of the tags of the module
            raw = (out / f"{module}_w2c.c").read_bytes()
            repaired = _repair_imported_elements([raw])[0]
            (out / f"{module}_w2c.c").write_bytes(
                _export_tags(_repair_tail_calls(_portable(repaired)), module_prefix(module))
            )
            model = build_model(parse(wasm.read_bytes()), module, host=host)
            (out / f"{module}_descriptor.c").write_text(generate_descriptor(model), encoding="utf-8")
            (out / f"{module}_binding.c").write_text(generate_binding(model), encoding="utf-8")
            sources += [out / f"{module}_binding.c", out / f"{module}_descriptor.c", out / f"{module}_w2c.c"]
        # the runtime is the product's too: wrapped (the allocation of a memory traps, it does not abort; the trap handler and the exceptions as the product has them)
        wrapped: list[Path] = []
        for key in ("impl", "mem", "exceptions"):
            path = out / f"rt_{key}.c"
            path.write_text(_RUNTIME_WRAPPERS[key], encoding="utf-8")
            wrapped.append(path)
        exe = (
            out
            / f"{name}_{Path(test).stem}{'_' + ''.join(c for c in ''.join(flags) if c.isalnum()) if flags else ''}{EXE}"
        )
        compile_c(
            [*sources, *wrapped],
            exe,
            include_dirs=[WASMEXT_C, Path(get_include()), runtime, out, *simde],
            flags=flags,
            defines=[f"MODULE={name}", *defines],
            strict=False,
            std=None,
            threads=True,
            math=True,
        )
        return exe

    return run


def _run(exe: Path) -> None:
    result = subprocess.run(
        [str(exe)], check=False, capture_output=True, text=True, timeout=300
    )  # a lock that a trap did not let go would hang here
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_calls_of_an_instance(build: Callable[..., Path]) -> None:
    _run(build(OPS, "ops", "test_instance.c"))


def test_a_trap_in_the_start_function(build: Callable[..., Path]) -> None:
    _run(build(START_TRAP, "starttrap", "test_instance_start_trap.c"))


def test_function_imports_by_index(build: Callable[..., Path]) -> None:
    _run(build(IMPORTS, "imports", "test_imports.c"))


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="ThreadSanitizer is checked on Linux")
def test_function_imports_under_sanitizers(build: Callable[..., Path]) -> None:
    if SANITIZED or not supports_flag("-fsanitize=address,undefined"):
        pytest.skip("no sanitizers, or one is on for the whole run")
    _run(
        build(
            IMPORTS,
            "imports",
            "test_imports.c",
            flags=["-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-g"],
        )
    )


@pytest.mark.parametrize(
    ("wat", "host", "message"),
    [
        (
            '(module (import "wasi:cli/exit@0.2.0" "exit" (func (param i32))) (memory (export "memory") 1) (func (export "f")))',
            "wasm32-wasip2",
            "exports cabi_realloc",
        ),
        (
            '(module (import "wasi_snapshot_preview1" "proc_exit" (func (param i32))) (func (export "f")))',
            "wasm32-wasip1",
            "exports its memory",
        ),
        (
            '(module (import "wasi_snapshot_preview1" "no_such_call" (func)) (memory (export "memory") 1) (func (export "f")))',
            "wasm32-wasip1",
            "not a function of wasi_snapshot_preview1",
        ),
        (
            '(module (import "wasi_snapshot_preview1" "fd_close" (func (param i64) (result i32))) (memory (export "memory") 1) (func (export "f")))',
            "wasm32-wasip1",
            "fd_close is",
        ),
    ],
    ids=[
        "wasi-0.2-no-realloc",
        "no-memory",
        "unknown-call",
        "wrong-signature",
    ],
)
def test_what_the_binding_does_not_carry_yet(wabt: Path, tmp_path: Path, wat: str, host: str, message: str) -> None:
    from wasmext._gen import GenError

    (tmp_path / "i.wat").write_text(wat, encoding="utf-8")
    subprocess.run([wabt / "bin" / "wat2wasm", tmp_path / "i.wat", "-o", tmp_path / "i.wasm"], check=True)
    with pytest.raises(GenError, match=message):
        generate_binding(build_model(parse((tmp_path / "i.wasm").read_bytes()), "i", host=host))


def test_a_v128_crosses_as_16_bytes(build: Callable[..., Path]) -> None:
    _run(build(SIMD, "simd", "test_instance_v128.c"))


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="ThreadSanitizer is checked on Linux")
def test_the_instance_under_threadsanitizer(build: Callable[..., Path]) -> None:
    if SANITIZED or not supports_flag("-fsanitize=thread"):
        pytest.skip("no ThreadSanitizer, or another sanitizer is on for the whole run")
    _run(build(OPS, "ops", "test_instance.c", flags=["-fsanitize=thread", "-g"]))


def test_wasi_imports_answered_by_the_host(build: Callable[..., Path]) -> None:
    _run(build(WASI1, "wasi1", "test_wasi_imports.c", host="wasm32-wasip1"))


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="ThreadSanitizer is checked on Linux")
def test_wasi_imports_under_threadsanitizer(build: Callable[..., Path]) -> None:
    if SANITIZED or not supports_flag("-fsanitize=thread"):
        pytest.skip("no ThreadSanitizer, or another sanitizer is on for the whole run")
    _run(build(WASI1, "wasi1", "test_wasi_imports.c", flags=["-fsanitize=thread", "-g"], host="wasm32-wasip1"))


def test_wasi_2_imports_answered_by_the_host(build: Callable[..., Path]) -> None:
    _run(build(WASI2, "wasi2", "test_wasi2_imports.c", host="wasm32-wasip2"))


def test_wasi_2_imports_under_sanitizers(build: Callable[..., Path]) -> None:
    if SANITIZED or not sys.platform.startswith("linux") or not supports_flag("-fsanitize=address,undefined"):
        pytest.skip("no sanitizers, or one is on for the whole run")
    _run(
        build(
            WASI2,
            "wasi2",
            "test_wasi2_imports.c",
            flags=["-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-g"],
            host="wasm32-wasip2",
        )
    )


@pytest.mark.parametrize("host", ["wasm32-wasip1", "wasm32-wasip2"])
def test_a_binding_for_every_function_of_wasi_compiles(build: Callable[..., Path], host: str) -> None:
    """The binding answers all the functions of the table (46 of each snapshot of 0.1, 201 of 0.2) and is compiled and linked as C: the typed functions, the headers, the signatures."""
    from wasmext._gen import _P2_FUNCS, _P2_IMPORTS, _WASI_SIGNATURES  # pyright: ignore[reportPrivateUsage]

    types = {"i": "i32", "j": "i64", "f": "f32", "d": "f64"}
    lines = ["(module"]
    if host == "wasm32-wasip1":
        for module, sigs in _WASI_SIGNATURES.items():
            for name, code in sigs.items():
                params, results = code.split(">")
                lines.append(
                    f'  (import "{module}" "{name}" (func (param {" ".join(types[c] for c in params)}) (result {" ".join(types[c] for c in results)})))'
                )
    else:
        for (module, name), cname in sorted(_P2_IMPORTS.items()):
            _header, _comp, ptypes, rtype = _P2_FUNCS[cname]
            lines.append(f'  (import "{module}@0.2.0" "{name}" (func (param {" ".join(ptypes)}) (result {rtype})))')
        lines.append('  (func (export "cabi_realloc") (param i32 i32 i32 i32) (result i32) i32.const 0)')
    lines.append('  (memory (export "memory") 1))')
    wat = "\n".join(lines).replace("(param )", "").replace("(result )", "")
    _run(build(wat, f"all{host[-1]}", "test_binding_links.c", host=host))


def test_memories_and_globals(build: Callable[..., Path]) -> None:
    _run(build(MEMORY_GLOBALS, "memglob", "test_memory_globals.c"))


def test_a_memory64_that_the_runtime_moves(build: Callable[..., Path]) -> None:
    _run(build(MEMORY64, "mem64", "test_memory_globals.c", defines=["MEMORY64=1"]))


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the sanitizers are checked on Linux")
def test_memories_and_globals_under_sanitizers(build: Callable[..., Path]) -> None:
    if SANITIZED or not supports_flag("-fsanitize=thread") or not supports_flag("-fsanitize=address,undefined"):
        pytest.skip("no sanitizers, or one is on for the whole run")
    # a 32-bit memory with guard pages never moves, so a pin does nothing there: the pins from threads are checked for races on the memory64
    _run(
        build(
            MEMORY_GLOBALS,
            "memglob",
            "test_memory_globals.c",
            flags=["-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-g"],
        )
    )
    _run(build(MEMORY64, "mem64", "test_memory_globals.c", flags=["-fsanitize=thread", "-g"], defines=["MEMORY64=1"]))


def test_links_between_instances(build: Callable[..., Path]) -> None:
    _run(build(LINK_MODULES, "links", "test_links.c"))


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the sanitizers are checked on Linux")
def test_links_under_sanitizers(build: Callable[..., Path]) -> None:
    if SANITIZED or not supports_flag("-fsanitize=address,undefined"):
        pytest.skip("no sanitizers, or one is on for the whole run")
    _run(
        build(
            LINK_MODULES,
            "links",
            "test_links.c",
            flags=["-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-g"],
        )
    )


def test_tables_of_funcref(build: Callable[..., Path]) -> None:
    _run(build(TABLE_MODULES, "tables", "test_tables.c"))


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the sanitizers are checked on Linux")
def test_tables_under_sanitizers(build: Callable[..., Path]) -> None:
    if SANITIZED or not supports_flag("-fsanitize=address,undefined") or not supports_flag("-fsanitize=thread"):
        pytest.skip("no sanitizers, or one is on for the whole run")
    _run(
        build(
            TABLE_MODULES,
            "tables",
            "test_tables.c",
            flags=["-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-g"],
        )
    )
    _run(build(TABLE_MODULES, "tables", "test_tables.c", flags=["-fsanitize=thread", "-g"]))


def test_externref_values(build: Callable[..., Path]) -> None:
    _run(build(EXTERN_MODULES, "xr", "test_externref.c"))


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the sanitizers are checked on Linux")
def test_externref_under_sanitizers(build: Callable[..., Path]) -> None:
    if SANITIZED or not supports_flag("-fsanitize=address,undefined") or not supports_flag("-fsanitize=thread"):
        pytest.skip("no sanitizers, or one is on for the whole run")
    _run(
        build(
            EXTERN_MODULES,
            "xr",
            "test_externref.c",
            flags=["-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-g"],
        )
    )
    _run(build(EXTERN_MODULES, "xr", "test_externref.c", flags=["-fsanitize=thread", "-g"]))


def test_links_of_functions_with_references(build: Callable[..., Path]) -> None:
    _run(build(REF_LINK_MODULES, "reflinks", "test_ref_links.c"))


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the sanitizers are checked on Linux")
def test_links_of_functions_with_references_under_sanitizers(build: Callable[..., Path]) -> None:
    if SANITIZED or not supports_flag("-fsanitize=address,undefined"):
        pytest.skip("no sanitizers, or one is on for the whole run")
    _run(
        build(
            REF_LINK_MODULES,
            "reflinks",
            "test_ref_links.c",
            flags=["-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-g"],
        )
    )


def test_globals_of_references(build: Callable[..., Path]) -> None:
    _run(build(REF_GLOBAL_MODULES, "rg", "test_ref_globals.c"))


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the sanitizers are checked on Linux")
def test_globals_of_references_under_sanitizers(build: Callable[..., Path]) -> None:
    if SANITIZED or not supports_flag("-fsanitize=address,undefined"):
        pytest.skip("no sanitizers, or one is on for the whole run")
    _run(
        build(
            REF_GLOBAL_MODULES,
            "rg",
            "test_ref_globals.c",
            flags=["-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-g"],
        )
    )


def test_tags_shared_between_instances(build: Callable[..., Path]) -> None:
    _run(build(TAG_MODULES, "tags", "test_tags.c"))


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the sanitizers are checked on Linux")
def test_tags_under_sanitizers(build: Callable[..., Path]) -> None:
    if SANITIZED or not supports_flag("-fsanitize=address,undefined"):
        pytest.skip("no sanitizers, or one is on for the whole run")
    _run(
        build(
            TAG_MODULES,
            "tags",
            "test_tags.c",
            flags=["-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-g"],
        )
    )


def test_host_tags_belong_to_the_store(build: Callable[..., Path]) -> None:
    _run(build(HOST_TAG_MODULES, "hosttags", "test_host_tags.c"))


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the sanitizers are checked on Linux")
def test_host_tags_under_sanitizers(build: Callable[..., Path]) -> None:
    if SANITIZED or not supports_flag("-fsanitize=address,undefined") or not supports_flag("-fsanitize=thread"):
        pytest.skip("no sanitizers, or one is on for the whole run")
    _run(
        build(
            HOST_TAG_MODULES,
            "hosttags",
            "test_host_tags.c",
            flags=["-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-g"],
        )
    )
    _run(build(HOST_TAG_MODULES, "hosttags", "test_host_tags.c", flags=["-fsanitize=thread", "-g"]))


def test_a_memory_that_cannot_be_had(build: Callable[..., Path]) -> None:
    _run(build({"big": NO_MEMORY}, "nomem", "test_nomemory.c"))
