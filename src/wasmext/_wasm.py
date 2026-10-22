"""A reader of the WebAssembly binary format: what generating a Python extension from a module needs to know.

    module = parse(Path("add.wasm").read_bytes())
    module.func_exports()        # [("add", FuncType(params=("i32", "i32"), results=("i32",)))]
    module.imports               # [Import(module="wiring", name="millis", kind="func", type=FuncType(...)), ...]

The signatures of the imports and exports, the memories, tables and globals; not the code (`wasm2c` translates that).
The names of parameters come from the "name" section when there is one. Sections that carry code or data are skipped after a check of their framing. Raises `WasmError` for anything that is not
a well-formed module of the core specification (with the multi-memory, memory64, extended-const and compact-imports proposals) and for
the value types it does not know (GC references, exceptions).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final, Literal, TypeVar

__all__ = [
    "Export",
    "FuncType",
    "GlobalType",
    "Import",
    "Limits",
    "Module",
    "TableType",
    "ValType",
    "WasiFlavor",
    "WasmError",
    "expand_compact_imports",
    "parse",
    "wasi_flavor",
]

ValType = Literal["i32", "i64", "f32", "f64", "v128", "funcref", "externref"]
ExternKind = Literal["func", "table", "memory", "global", "tag"]
WasiFlavor = Literal["component", "fused", "core-0.1", "core-0.2", "core-0.3", "none", "unknown"]
_T = TypeVar("_T")

_VALTYPES: Final[dict[int, ValType]] = {
    0x7F: "i32",
    0x7E: "i64",
    0x7D: "f32",
    0x7C: "f64",
    0x7B: "v128",
    0x70: "funcref",
    0x6F: "externref",
}
_KINDS: Final[tuple[ExternKind, ...]] = ("func", "table", "memory", "global", "tag")

# What to tell about a flavor that wasmext does not run by itself (WASI 0.1 is built into the module; the others are not).
WASI_HINTS: Final[dict[str, str]] = {
    "core-0.2": "imports WASI 0.2 (wasi:*@0.2): it is built, but wasmext does not answer those calls; the host has to (docs/WASI_COMPONENTS.md)",
    "core-0.3": "imports WASI 0.3 (wasi:*@0.3): it is built, but wasmext does not answer those calls; the host has to (docs/WASI_COMPONENTS.md)",
    "fused": "made by `meld fuse` from components: it is built, but any WASI 0.2/0.3 calls it makes are for the host to answer (docs/WASI_COMPONENTS.md)",
}

_MAGIC: Final = b"\0asm"
_VERSION: Final = b"\x01\x00\x00\x00"
_COMPACT_EACH: Final = 0x7F  # compact imports: after the module, a name and a type (with its kind) for each import
_COMPACT_KIND: Final = (
    0x7E  # compact imports: after the module, one type (with its kind) for the group, then a name for each import
)
_COMPONENT_VERSION: Final = b"\x0d\x00\x01\x00"  # the version field of a component (a module has 1)

# The order in which sections may appear (the id of the section -> its place); the tag section sits before the
# globals, the data count before the code. Custom sections (0) may be anywhere.
_TYPE, _IMPORT, _FUNCTION, _TABLE, _MEMORY, _GLOBAL, _EXPORT, _START = 1, 2, 3, 4, 5, 6, 7, 8
_ELEMENT, _CODE, _DATA, _DATA_COUNT, _TAG = 9, 10, 11, 12, 13
_ORDER: Final[dict[int, int]] = {
    _TYPE: 1,
    _IMPORT: 2,
    _FUNCTION: 3,
    _TABLE: 4,
    _MEMORY: 5,
    _TAG: 6,
    _GLOBAL: 7,
    _EXPORT: 8,
    _START: 9,
    _ELEMENT: 10,
    _DATA_COUNT: 11,
    _CODE: 12,
    _DATA: 13,
}


class WasmError(ValueError):
    """The bytes are not a WebAssembly module this reader understands."""


@dataclass(frozen=True, slots=True)
class FuncType:
    params: tuple[ValType, ...]
    results: tuple[ValType, ...]


@dataclass(frozen=True, slots=True)
class Limits:
    """The size of a memory or a table: in pages (64 KiB) or elements."""

    min: int
    max: int | None = None
    shared: bool = False
    is64: bool = False


@dataclass(frozen=True, slots=True)
class TableType:
    elem: ValType
    limits: Limits


@dataclass(frozen=True, slots=True)
class GlobalType:
    type: ValType
    mutable: bool


@dataclass(frozen=True, slots=True)
class Import:
    module: str
    name: str
    kind: ExternKind
    # A function (and a tag) comes with its signature, a memory with its limits.
    type: FuncType | TableType | Limits | GlobalType


@dataclass(frozen=True, slots=True)
class Export:
    name: str
    kind: ExternKind
    index: int  # in the index space of its kind: the imports first, then what the module defines


@dataclass(slots=True)
class Module:
    types: list[FuncType] = field(default_factory=list[FuncType])
    imports: list[Import] = field(default_factory=list[Import])
    functions: list[FuncType] = field(default_factory=list[FuncType])  # defined here, not imported
    tables: list[TableType] = field(default_factory=list[TableType])
    memories: list[Limits] = field(default_factory=list[Limits])
    globals: list[GlobalType] = field(default_factory=list[GlobalType])
    tags: list[FuncType] = field(
        default_factory=list[FuncType]
    )  # defined here, not imported: the types of the values of an exception
    exports: list[Export] = field(default_factory=list[Export])
    start: int | None = None
    # From the "name" section, which is only a help for people: function index -> {local index -> name}; the parameters are the first locals.
    local_names: dict[int, dict[int, str]] = field(default_factory=dict[int, dict[int, str]])
    custom: list[str] = field(default_factory=list[str])  # the names of the custom sections, in order
    # Compact imports: where the import section is in the binary (from its id byte to its end), and, if some entry of it is compact, its body
    # written with ordinary imports (see `expand_compact_imports`).
    import_section: tuple[int, int] | None = None
    plain_imports: bytes | None = None

    def _imported(self, kind: ExternKind) -> list[FuncType | TableType | Limits | GlobalType]:
        return [i.type for i in self.imports if i.kind == kind]

    @property
    def all_functions(self) -> list[FuncType]:
        """The function index space: imported functions, then defined ones."""
        return [t for t in self._imported("func") if isinstance(t, FuncType)] + self.functions

    @property
    def all_memories(self) -> list[Limits]:
        return [t for t in self._imported("memory") if isinstance(t, Limits)] + self.memories

    @property
    def all_tables(self) -> list[TableType]:
        return [t for t in self._imported("table") if isinstance(t, TableType)] + self.tables

    @property
    def all_globals(self) -> list[GlobalType]:
        return [t for t in self._imported("global") if isinstance(t, GlobalType)] + self.globals

    @property
    def all_tags(self) -> list[FuncType]:
        """The tag index space: imported tags, then defined ones (the signature of a tag has parameters and no results)."""
        return [t for t in self._imported("tag") if isinstance(t, FuncType)] + self.tags

    def func_exports(self) -> list[tuple[str, FuncType]]:
        """The exported functions with their signatures, in the order of the export section."""
        funcs = self.all_functions
        return [(e.name, funcs[e.index]) for e in self.exports if e.kind == "func"]

    def param_names(self, func_index: int) -> tuple[str | None, ...]:
        """The names the "name" section gives to the parameters of a function, `None` for one it does not name."""
        named = self.local_names.get(func_index, {})
        count = len(self.all_functions[func_index].params)
        return tuple(named.get(i) for i in range(count))

    def memory_exports(self) -> list[tuple[str, Limits]]:
        memories = self.all_memories
        return [(e.name, memories[e.index]) for e in self.exports if e.kind == "memory"]

    def global_exports(self) -> list[tuple[str, GlobalType]]:
        gl = self.all_globals
        return [(e.name, gl[e.index]) for e in self.exports if e.kind == "global"]

    def table_exports(self) -> list[tuple[str, TableType]]:
        tables = self.all_tables
        return [(e.name, tables[e.index]) for e in self.exports if e.kind == "table"]

    def func_imports(self) -> list[Import]:
        return [i for i in self.imports if i.kind == "func"]


class _Reader:
    """A cursor over `data[pos:end]`."""

    def __init__(self, data: bytes, pos: int = 0, end: int | None = None) -> None:
        self.data = data
        self.pos = pos
        self.end = len(data) if end is None else end

    def at_end(self) -> bool:
        return self.pos >= self.end

    def byte(self) -> int:
        if self.pos >= self.end:
            raise WasmError(f"unexpected end of data at offset {self.pos}")
        b = self.data[self.pos]
        self.pos += 1
        return b

    def take(self, n: int) -> bytes:
        if n < 0 or self.pos + n > self.end:
            raise WasmError(f"{n} bytes wanted at offset {self.pos}, {self.end - self.pos} left")
        chunk = self.data[self.pos : self.pos + n]
        self.pos += n
        return chunk

    def skip(self, n: int) -> None:
        self.take(n)

    def uleb(self, bits: int = 32) -> int:
        """An unsigned LEB128 integer of at most `bits` bits."""
        result = 0
        shift = 0
        while True:
            b = self.byte()
            result |= (b & 0x7F) << shift
            shift += 7
            if not b & 0x80:
                break
            if shift >= bits + 7:
                raise WasmError(f"LEB128 integer too long at offset {self.pos}")
        if result >> bits:
            raise WasmError(f"LEB128 integer does not fit {bits} bits at offset {self.pos}")
        return result

    def sleb(self, bits: int) -> int:
        """A signed LEB128 integer of at most `bits` bits."""
        result = 0
        shift = 0
        while True:
            b = self.byte()
            result |= (b & 0x7F) << shift
            shift += 7
            if not b & 0x80:
                break
            if shift >= bits + 7:
                raise WasmError(f"LEB128 integer too long at offset {self.pos}")
        if b & 0x40:
            result -= 1 << shift
        if not -(1 << (bits - 1)) <= result < 1 << (bits - 1):
            raise WasmError(f"LEB128 integer does not fit {bits} bits at offset {self.pos}")
        return result

    def name(self) -> str:
        raw = self.take(self.uleb())
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WasmError(f"a name is not valid UTF-8 at offset {self.pos}") from exc

    def vec(self, item: Callable[[], _T]) -> list[_T]:
        # Every item takes at least a byte: a count beyond what is left is a lie, not a reason to allocate.
        count = self.uleb()
        if count > self.end - self.pos:
            raise WasmError(f"a vector of {count} items at offset {self.pos}, {self.end - self.pos} bytes left")
        return [item() for _ in range(count)]

    def sub(self, size: int) -> _Reader:
        start = self.pos
        self.skip(size)
        return _Reader(self.data, start, start + size)

    def valtype(self) -> ValType:
        code = self.byte()
        try:
            return _VALTYPES[code]
        except KeyError:
            reference = (
                " (a reference type of the GC proposal, which wasm2c does not support)"
                if code in (0x63, 0x64, 0x6A, 0x6B, 0x6C, 0x6D, 0x6E, 0x71, 0x72, 0x73, 0x74)
                else ""
            )
            raise WasmError(f"unsupported value type 0x{code:02x} at offset {self.pos - 1}{reference}") from None

    def reftype(self) -> ValType:
        t = self.valtype()
        if t not in ("funcref", "externref"):
            raise WasmError(f"{t} is not a reference type (offset {self.pos - 1})")
        return t

    def limits(self) -> Limits:
        flags = self.byte()
        if flags & 0x08:
            raise WasmError(
                f"a memory with a custom page size (the custom-page-sizes proposal) is not supported: wasm2c has no such memory (offset {self.pos - 1})"
            )
        if flags & ~0x07:
            raise WasmError(f"unknown limits flags 0x{flags:02x} at offset {self.pos - 1}")
        is64 = bool(flags & 0x04)
        bits = 64 if is64 else 32
        low = self.uleb(bits)
        high = self.uleb(bits) if flags & 0x01 else None
        return Limits(low, high, shared=bool(flags & 0x02), is64=is64)

    def const_expr(self) -> None:
        """Read a constant expression to its `end`: the value is not needed, the length is."""
        while True:
            op = self.byte()
            if op == 0x0B:  # end
                return
            if op == 0x41:  # i32.const
                self.sleb(32)
            elif op == 0x42:  # i64.const
                self.sleb(64)
            elif op == 0x43:  # f32.const
                self.skip(4)
            elif op == 0x44:  # f64.const
                self.skip(8)
            elif op in (0x23, 0xD2):  # global.get, ref.func
                self.uleb()
            elif op == 0xD0:  # ref.null
                self.reftype()
            elif op == 0xFD:  # v128.const
                if self.uleb() != 0x0C:
                    raise WasmError(f"unsupported SIMD opcode in a constant expression at offset {self.pos}")
                self.skip(16)
            elif op in (0x6A, 0x6B, 0x6C, 0x7C, 0x7D, 0x7E):  # i32/i64 add, sub, mul (extended-const)
                pass
            else:
                raise WasmError(f"unsupported opcode 0x{op:02x} in a constant expression at offset {self.pos - 1}")


def parse(data: bytes) -> Module:
    """Read the type, import, function, table, memory, global, tag, export and start sections of a binary module."""
    if data[:4] != _MAGIC:
        raise WasmError("not a WebAssembly binary: the magic number is missing")
    if data[4:8] == _COMPONENT_VERSION:
        raise WasmError(
            "this is a WebAssembly component, not a core module; take the core modules out with `wasm-tools component unbundle`, "
            "or fuse a composed component with `meld fuse` (see docs/WASI_COMPONENTS.md)"
        )
    if data[4:8] != _VERSION:
        raise WasmError(f"unsupported WebAssembly binary version {data[4:8].hex() or '(none)'}")
    reader = _Reader(data, 8)
    module = Module()
    last = 0
    code_count = 0
    while not reader.at_end():
        section_start = reader.pos
        section_id = reader.byte()
        body = reader.sub(reader.uleb())
        if section_id == 0:  # custom: the name and then anything
            custom = body.name()
            module.custom.append(custom)
            if custom == "name":
                module.local_names = _local_names(body)
            continue
        if section_id not in _ORDER:
            raise WasmError(f"unknown section id {section_id}")
        if _ORDER[section_id] <= last:
            raise WasmError(f"section {section_id} is out of order or repeated")
        last = _ORDER[section_id]
        if section_id == _IMPORT:
            module.import_section = (section_start, reader.pos)
        if section_id == _CODE:
            code_count = body.uleb()  # the bodies are for wasm2c
        else:
            _section(module, section_id, body)
    if code_count != len(module.functions):
        raise WasmError(f"{len(module.functions)} functions declared, {code_count} bodies in the code section")
    _check_indices(module)
    return module


def wasi_flavor(data: bytes) -> WasiFlavor:
    """What kind of WASI file `data` is, from its bytes alone.

    `component`: a component (version field `0d 00 01 00`), which wasmext does not read. `fused`: a core module with a custom
    section `meld.*`, made by `meld fuse` from components. `core-0.1`, `core-0.2`, `core-0.3`: a core module whose imports (or,
    failing those, exports) are of `wasi_snapshot_preview1` / `wasi_unstable`, or of `wasi:*@0.2.x` / `wasi:*@0.3.x`; the newest wins.
    `none`: a core module that uses no WASI. `unknown`: not a module wasmext can read.
    """
    if data[:4] == _MAGIC and data[4:8] == _COMPONENT_VERSION:
        return "component"
    try:
        module = parse(data)
    except WasmError:
        return "unknown"
    if any(name.startswith("meld.") for name in module.custom):
        return "fused"
    versions = {
        _wasi_version(name) for name in [*(i.module for i in module.imports), *(e.name for e in module.exports)]
    }
    for flavor in ("core-0.3", "core-0.2", "core-0.1"):
        if flavor in versions:
            return flavor
    return "none"


def _wasi_version(name: str) -> str:
    if name in ("wasi_snapshot_preview1", "wasi_unstable"):
        return "core-0.1"
    if name.startswith("wasi:"):
        _, _, version = name.partition("@")
        if version.startswith("0.2."):
            return "core-0.2"
        if version.startswith("0.3."):
            return "core-0.3"
    return ""


def _local_names(r: _Reader) -> dict[int, dict[int, str]]:
    """The names of locals in the "name" section (subsection 2). The section is a hint: if it is malformed, there are no names (the
    specification does not let it invalidate the module)."""
    names: dict[int, dict[int, str]] = {}
    try:
        while not r.at_end():
            kind = r.byte()
            part = r.sub(r.uleb())
            if kind == 2:
                _local_name_map(part, names)
    except WasmError:
        return {}
    return names


def _local_name_map(part: _Reader, names: dict[int, dict[int, str]]) -> None:
    def pair() -> tuple[int, str]:
        return part.uleb(), part.name()

    def function() -> tuple[int, list[tuple[int, str]]]:
        return part.uleb(), part.vec(pair)

    for func_index, local_map in part.vec(function):
        names[func_index] = dict(local_map)


def _section(module: Module, section_id: int, body: _Reader) -> None:
    if section_id == _TYPE:
        module.types = body.vec(lambda: _functype(body))
    elif section_id == _IMPORT:
        module.imports, module.plain_imports = _imports(body, module.types)
    elif section_id == _FUNCTION:
        module.functions = body.vec(lambda: _typeref(body, module.types))
    elif section_id == _TABLE:
        module.tables = body.vec(lambda: _table(body))
    elif section_id == _MEMORY:
        module.memories = body.vec(body.limits)
    elif section_id == _GLOBAL:
        module.globals = body.vec(lambda: _global(body))
    elif section_id == _EXPORT:
        module.exports = body.vec(lambda: _export(body))
    elif section_id == _START:
        module.start = body.uleb()
    elif section_id == _TAG:
        module.tags = body.vec(lambda: _tag(body, module.types))
    else:  # element, data, data count: the framing is all that is checked
        return
    if not body.at_end():
        raise WasmError(f"section {section_id} has {body.end - body.pos} unread bytes at offset {body.pos}")


def _functype(r: _Reader) -> FuncType:
    form = r.byte()
    if form in (0x4E, 0x4F, 0x50, 0x5E, 0x5F):  # rec, sub final, sub, struct, array
        raise WasmError(
            f"the module uses the types of the GC proposal (struct, array, sub, rec: form 0x{form:02x} at offset {r.pos - 1}), which wasm2c does not support"
        )
    if form != 0x60:
        raise WasmError(f"unsupported type form 0x{form:02x} at offset {r.pos - 1}")
    params = tuple(r.vec(r.valtype))
    results = tuple(r.vec(r.valtype))
    return FuncType(params, results)


def _typeref(r: _Reader, types: list[FuncType]) -> FuncType:
    index = r.uleb()
    if index >= len(types):
        raise WasmError(f"type index {index} is out of range ({len(types)} types)")
    return types[index]


def _table(r: _Reader) -> TableType:
    # A table with an initialiser is 0x40 0x00 reftype limits expr (function references / GC proposals).
    if r.pos < r.end and r.data[r.pos] == 0x40:
        r.byte()
        if r.byte() != 0x00:
            raise WasmError(f"malformed table type at offset {r.pos - 1}")
        table = TableType(r.reftype(), r.limits())
        r.const_expr()
        return table
    return TableType(r.reftype(), r.limits())


def _global(r: _Reader) -> GlobalType:
    gt = _globaltype(r)
    r.const_expr()
    return gt


def _globaltype(r: _Reader) -> GlobalType:
    value = r.valtype()
    flag = r.byte()
    if flag not in (0, 1):
        raise WasmError(f"unknown global mutability 0x{flag:02x} at offset {r.pos - 1}")
    return GlobalType(value, bool(flag))


def _imports(r: _Reader, types: list[FuncType]) -> tuple[list[Import], bytes | None]:
    """The import section: its imports, and, if any of its entries was a compact one, the body of the section written out with ordinary imports.

    As the proposal reads it (`proposals/compact-import-section/Overview.md`, the decoder of its interpreter and `binary-compact-imports.wast`): the number in front counts the
    entries (a group is one, and may hold no imports), not the imports."""
    entries = r.vec(lambda: _import(r, types))
    found = [item for group, _ in entries for item in group]
    plain: bytes | None = None
    if any(compact for _, compact in entries):
        plain = _leb(len(found)) + b"".join(_name_bytes(imp.module) + _name_bytes(imp.name) + raw for imp, raw in found)
    return [imp for imp, _ in found], plain


def _import(r: _Reader, types: list[FuncType]) -> tuple[list[tuple[Import, bytes]], bool]:
    """One entry of the import section: the imports it makes, each with the bytes of its type, and whether it is a compact one.

    A module name and an empty name followed by 0x7F is a module with (name, type) for each import; followed by 0x7E, a module with one type and a
    name for each import. The byte after the empty name is not LEB128, and the empty name may be written in more bytes than one."""
    module = r.name()
    name = r.name()
    mark = r.data[r.pos] if r.pos < r.end else None
    if name == "" and mark == _COMPACT_EACH:
        r.byte()
        return r.vec(lambda: _item(r, module, r.name(), types)), True
    if name == "" and mark == _COMPACT_KIND:
        r.byte()
        kind, type_, raw = _externtype(r, types)
        return r.vec(lambda: (Import(module, r.name(), kind, type_), raw)), True
    return [_item(r, module, name, types)], False


def _item(r: _Reader, module: str, name: str, types: list[FuncType]) -> tuple[Import, bytes]:
    kind, type_, raw = _externtype(r, types)
    return Import(module, name, kind, type_), raw


def _externtype(
    r: _Reader, types: list[FuncType]
) -> tuple[ExternKind, FuncType | TableType | Limits | GlobalType, bytes]:
    """The kind of an import and its type, and the bytes they were written in."""
    start = r.pos
    code = r.byte()
    if code >= len(_KINDS):
        raise WasmError(f"unknown import kind {code} at offset {r.pos - 1}")
    kind = _KINDS[code]
    if kind == "func":
        type_ = _typeref(r, types)
    elif kind == "table":
        type_ = TableType(r.reftype(), r.limits())
    elif kind == "memory":
        type_ = r.limits()
    elif kind == "global":
        type_ = _globaltype(r)
    else:
        if r.byte() != 0x00:  # tag: an attribute byte, then the type of the exception
            raise WasmError(f"unknown tag attribute at offset {r.pos - 1}")
        type_ = _typeref(r, types)
    return kind, type_, r.data[start : r.pos]


def _leb(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _name_bytes(text: str) -> bytes:
    raw = text.encode("utf-8")
    return _leb(len(raw)) + raw


def expand_compact_imports(data: bytes, module: Module) -> bytes:
    """`data`, which `module` was read from, with the import section written with ordinary imports. A module with none that are compact comes back as it is.

    WABT 1.0.42 (and `main`) reads the form 0x7E and the number in front of the section differently from the proposal, so what `wasm2c` is given
    is the module with ordinary imports, whatever the version of WABT."""
    if module.plain_imports is None or module.import_section is None:
        return data
    start, end = module.import_section
    return data[:start] + bytes([_IMPORT]) + _leb(len(module.plain_imports)) + module.plain_imports + data[end:]


def _tag(r: _Reader, types: list[FuncType]) -> FuncType:
    if r.byte() != 0x00:  # an attribute byte (0: an exception), then the type of its values
        raise WasmError(f"unknown tag attribute at offset {r.pos - 1}")
    return _typeref(r, types)


def _export(r: _Reader) -> Export:
    name = r.name()
    code = r.byte()
    if code >= len(_KINDS):
        raise WasmError(f"unknown export kind {code} at offset {r.pos - 1}")
    return Export(name, _KINDS[code], r.uleb())


def _check_indices(module: Module) -> None:
    """Exports and the start function must name something that exists."""
    spaces: dict[ExternKind, int] = {
        "func": len(module.all_functions),
        "table": len(module.all_tables),
        "memory": len(module.all_memories),
        "global": len(module.all_globals),
        "tag": len(module.all_tags),
    }
    for e in module.exports:
        if 0 <= spaces[e.kind] <= e.index:
            raise WasmError(f"export {e.name!r}: {e.kind} index {e.index} is out of range")
    if module.start is not None and module.start >= spaces["func"]:
        raise WasmError(f"start function index {module.start} is out of range")
