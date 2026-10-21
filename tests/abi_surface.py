"""The public surface of the ABI as a dictionary, read from the code, and the comparison of two of them.

The policy is in docs/abi_policy.md. The surface is what a module or a host built apart relies on: the capsule names, the macros, constants, types and
structs of the glue (`wasmext_glue.h`), and the declarations of the C API of a library (`<name>_api.h`) and the stub (`.pyi`, the interface of the extension and of the wrapper for ctypes), which are read from what
wasmext makes for the fixed modules in tests/data (`abi_surface*.wat`), with the name of the module put back as `<name>`. It is declared in abi/current.json; the test fails when the
code and the declaration differ, and says what differs; `python -m tests.abi_surface --update` writes the declaration again.

The reading is meant to be complete: every statement of a header is either read into the surface or is on a short list of what is not part of it (a
`static` function, a preprocessor line that is not a macro), and one that is neither stops the reading with its text, so that a new form of declaration cannot
slip by. Layouts are not computed: the order and the text of the fields are the layout, and a compiler gives the same offsets for the same text.
"""

from __future__ import annotations

import difflib
import json
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
DECLARATION = ROOT / "abi" / "current.json"
DATA = Path(__file__).parent / "data"
FIXTURES = ("abi_surface.wat", "abi_surface_more.wat")  # the modules whose C API is declared
FIXTURE_NAME = "abisurface"

# not part of the contract: the fingerprint of the toolchain and the helpers of the preprocessor
_NOT_PUBLIC = {
    "WASMEXT_RUNTIME",
    "WASMEXT_MSIZE",
    "WASMEXT_FOLLOWS",
    "WASMEXT_LAYOUT",
    "WASMEXT_NO_LAYOUT_CHECK",
    "WASMEXT_STRING",
    "WASMEXT_STRING_",
    "WASMEXT_API",
}

Surface = dict[str, Any]


def _clean(text: str) -> str:
    """The text without comments, with a macro that goes over several lines on one line."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", " ", text)
    return re.sub(r"\\\r?\n", " ", text)


def _norm(text: str) -> str:
    return " ".join(text.split())


def _statements(code: str) -> list[str]:
    """The top-level statements of C without preprocessor lines: split at the `;` outside braces and parentheses. A definition with a body
    (`static inline int f(void) { ... }`) ends at its closing brace."""
    out: list[str] = []
    depth = 0
    current: list[str] = []
    for char in code:
        if char == "}" and depth == 0:
            continue  # the end of `extern "C" {`, whose beginning was taken out
        current.append(char)
        if char in "{(":
            depth += 1
        elif char in "})":
            depth -= 1
            if char == "}" and depth == 0 and _starts_a_definition("".join(current)):
                out.append(_norm("".join(current)))
                current = []
        elif char == ";" and depth == 0:
            out.append(_norm("".join(current)[:-1]))
            current = []
    rest = _norm("".join(current))
    if rest:
        out.append(rest)
    return [s for s in out if s]


def _starts_a_definition(text: str) -> bool:
    """Whether the text, which ends at a closing brace of depth 0, is a function or a variable with a body and not a `typedef struct {...} name;` yet to finish."""
    head = _norm(text)
    return (
        bool(re.match(r"(static|extern|WASMEXT_API)\b", head))
        and not head.startswith("typedef")
        and "=" not in head.split("{")[0]
    )


def surface_of(header: str) -> Surface:
    """What a header declares, by kind: `constants` (macros with a value and the members of enums), `macros` (the names and parameters of the macros with
    parameters; the bodies are code), `typedefs` (the text of each), `structs` (the fields, in order), `opaque` (names), `functions` (the signature of each
    that is exported with WASMEXT_API)."""
    text = _clean(header)
    constants: dict[str, str] = {}
    macros: dict[str, str] = {}
    code_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("#"):
            code_lines.append(line)
            continue
        found = re.match(r"#\s*define\s+(\w+)(\([^)]*\))?\s*(.*)$", stripped)
        if found is None:
            continue  # #include, #if, #ifdef, #else, #endif, #undef, #pragma, #error: the structure of the file, not its surface
        name, params, value = found.groups()
        if name in _NOT_PUBLIC or name.endswith("_H"):
            continue
        if params:
            macros.setdefault(name, _norm(params))
        else:
            constants.setdefault(name, _norm(value))
    structs: dict[str, list[str]] = {}
    typedefs: dict[str, str] = {}
    opaque: list[str] = []
    functions: dict[str, str] = {}
    code = re.sub(r'^\s*extern\s+"C"\s*\{\s*$', "", "\n".join(code_lines), flags=re.MULTILINE)
    for statement in _statements(code):
        if statement.startswith(("static ", "extern ")):
            continue  # a function or a variable of the glue: every module has its own, nobody calls another module's
        if statement.startswith("WASMEXT_LAYOUT("):
            continue  # a check of the layout of the runtime at the build of a module: it says nothing that a module relies on
        found = re.fullmatch(r"typedef\s+(struct|union)\s*\w*\s*\{(.*)\}\s*(\w+)", statement)
        if found:
            structs[found.group(3)] = _fields(found.group(2))
            continue
        found = re.fullmatch(r"typedef\s+(struct|union)\s+\w+\s+(\w+)", statement)
        if found:
            opaque.append(found.group(2))
            continue
        found = re.fullmatch(r"typedef\s+.*\(\s*\*\s*(\w+)\s*\)\s*\(.*\)", statement)
        if found:
            typedefs[found.group(1)] = statement  # a pointer to a function
            continue
        found = re.fullmatch(r"typedef\s+.*?(\w+)", statement)
        if found:
            typedefs[found.group(1)] = statement
            continue
        found = re.fullmatch(r"enum\s*\w*\s*\{(.*)\}", statement)
        if found:
            next_value = 0
            for member in found.group(1).split(","):
                if not member.strip():
                    continue
                name, _, value = member.partition("=")
                number = _norm(value) if value.strip() else str(next_value)
                constants[name.strip()] = number
                next_value = (
                    int(number, 0) + 1 if re.fullmatch(r"-?(0[xX][0-9a-fA-F]+|\d+)", number) else next_value + 1
                )
            continue
        found = re.fullmatch(r"WASMEXT_API\s+(.*?)\b(\w+)\s*\((.*)\)", statement)
        if found:
            functions[found.group(2)] = _norm(f"{found.group(1)} {found.group(2)}({found.group(3)})")
            continue
        raise ValueError(f"a form of declaration that the reading of the ABI does not know: {statement[:200]!r}")
    return {
        "constants": constants,
        "macros": macros,
        "typedefs": typedefs,
        "structs": structs,
        "opaque": sorted(set(opaque)),
        "functions": functions,
    }


def _fields(body: str) -> list[str]:
    """The declarations of a struct body, split at the `;` that are not inside a brace or a parenthesis."""
    return _statements(body + ";") if body.strip() else []


def _renamed(value: Any) -> Any:
    """The name of the fixture module put back as `<name>` (and `<NAME>`) in every key and every text."""
    if isinstance(value, str):
        return value.replace(FIXTURE_NAME, "<name>").replace(FIXTURE_NAME.upper(), "<NAME>")
    if isinstance(value, list):
        return [_renamed(item) for item in value]  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
    if isinstance(value, dict):
        return {_renamed(k): _renamed(v) for k, v in value.items()}  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
    return value


def _stub_lines(stub: str) -> list[str]:
    """The lines of a stub, without the blank ones and the trailing spaces."""
    return [line.rstrip() for line in stub.splitlines() if line.strip()]


def extract(generated: dict[str, tuple[str, str]]) -> Surface:
    """The surface of this code: `generated` maps the name of a fixture to the `<name>_api.h` and the stub that wasmext makes for it (its name is `abisurface`)."""
    from wasmext._abi import ABI, ABI_X, C_DIR, capsule_name  # pyright: ignore[reportPrivateUsage]

    return {
        "about": "The public surface of the ABI of wasmext (docs/abi_policy.md), read from the code by tests/abi_surface.py. A difference between it and the code "
        "fails tests/test_abi_declaration.py: check the compatibility by hand, update this file (python -m tests.abi_surface --update) and set the version that fits.",
        "version": {"WASMEXT_ABI": f"0x{ABI:08X}"},
        "capsules": {"export": capsule_name(), "traps": f"wasmext.traps.v{ABI_X}"},
        "glue": surface_of((C_DIR / "wasmext_glue.h").read_text(encoding="utf-8")),
        "api": {
            name: _renamed({**surface_of(header), "stub": _stub_lines(stub)})
            for name, (header, stub) in generated.items()
        },
    }


def generated_of(wasm: bytes) -> tuple[str, str]:
    from wasmext._gen import generate  # pyright: ignore[reportPrivateUsage]
    from wasmext._wasm import parse  # pyright: ignore[reportPrivateUsage]

    glue = generate(parse(wasm), f"pkg.{FIXTURE_NAME}")
    if not glue.api_header:
        raise RuntimeError("a fixture of the ABI has no C API: " + "; ".join(glue.skipped))
    return glue.api_header, glue.stub


def dumps(surface: Surface) -> str:
    return json.dumps(surface, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def diff(declared: Surface, now: Surface) -> str:
    return "".join(
        difflib.unified_diff(
            dumps(declared).splitlines(keepends=True),
            dumps(now).splitlines(keepends=True),
            "abi/current.json (declared)",
            "the code (now)",
            n=2,
        )
    )


_ORDER = {"none": 0, "y": 1, "x": 2}


def _parts(surface: Surface) -> dict[str, Surface]:
    return {"glue": surface["glue"], **{f"api[{name}]": part for name, part in surface["api"].items()}}


def changes(old: Surface, new: Surface) -> list[tuple[str, str]]:
    """What differs between two surfaces, one line for each: (the version it needs, what happened). "x": something that a module built before relies
    on is gone or is different (a constant, a signature, a field that moved or changed, a struct, a capsule name); "y": something was added (a constant, a
    function, a struct, a field at the end of a struct)."""
    found: list[tuple[str, str]] = []
    if old["capsules"] != new["capsules"]:
        found.append(("x", f"the names of the capsules changed: {old['capsules']} -> {new['capsules']}"))
    before_parts, after_parts = _parts(old), _parts(new)
    for label in before_parts.keys() - after_parts.keys():
        found.append(("x", f"{label}: the declared part is gone"))
    for label in after_parts.keys() - before_parts.keys():
        found.append(("y", f"{label}: a part is declared that was not"))
    for label in before_parts.keys() & after_parts.keys():
        before, after = before_parts[label], after_parts[label]
        for kind in ("constants", "macros", "typedefs", "functions"):
            for name, value in before[kind].items():
                if name not in after[kind]:
                    found.append(("x", f"{label}: {kind[:-1] if kind != 'typedefs' else 'typedef'} {name} was removed"))
                elif after[kind][name] != value:
                    found.append(
                        (
                            "x",
                            f"{label}: {kind[:-1] if kind != 'typedefs' else 'typedef'} {name} changed: {value!r} -> {after[kind][name]!r}",
                        )
                    )
            for name in after[kind].keys() - before[kind].keys():
                found.append(
                    (
                        "y",
                        f"{label}: {kind[:-1] if kind != 'typedefs' else 'typedef'} {name} was added: {after[kind][name]!r}",
                    )
                )
        if "stub" in before and "stub" in after:
            for line in before["stub"]:
                if line not in after["stub"]:
                    found.append(("x", f"{label}: a line of the stub was removed or changed: {line!r}"))
            for line in after["stub"]:
                if line not in before["stub"]:
                    found.append(
                        ("y", f"{label}: a line of the stub was added (or the new form of a changed one): {line!r}")
                    )
        for name, fields in before["structs"].items():
            now = after["structs"].get(name)
            if now is None:
                found.append(("x", f"{label}: struct {name} was removed"))
            elif now[: len(fields)] == fields:
                for field in now[len(fields) :]:
                    found.append(("y", f"{label}: struct {name} got a field at the end: {field!r}"))
            else:
                old_fields, new_fields = cast("list[str]", fields), cast("list[str]", now)
                lost = Counter(old_fields) - Counter(new_fields)
                got = Counter(new_fields) - Counter(old_fields)
                if not lost and not got:
                    found.append(("x", f"{label}: the fields of struct {name} were put in another order"))
                for field in lost:
                    found.append(("x", f"{label}: struct {name} lost or changed the field {field!r}"))
                for field in got:
                    found.append(("x", f"{label}: struct {name} has a field in the middle or a changed one: {field!r}"))
        for name in after["structs"].keys() - before["structs"].keys():
            found.append(("y", f"{label}: struct {name} was added"))
        for name in set(before["opaque"]) - set(after["opaque"]):
            found.append(("x", f"{label}: the type {name} was removed"))
        for name in set(after["opaque"]) - set(before["opaque"]):
            found.append(("y", f"{label}: the type {name} was added"))
    return found


def required_bump(old: Surface, new: Surface) -> str:
    """What the change from `old` to `new` needs of the version: "x", "y", or "none" (the surface is the same: z, or a serial of a pre-release)."""
    worst = "none"
    for level, _ in changes(old, new):
        if _ORDER[level] > _ORDER[worst]:
            worst = level
    return worst


def describe(old: Surface, new: Surface) -> str:
    lines = [f"  [{level}] {what}" for level, what in changes(old, new)]
    return "\n".join(lines) if lines else "  (nothing in the surface: a change of the text outside it)"


def _build_fixtures() -> dict[str, tuple[str, str]]:
    import wabt_package  # pyright: ignore[reportMissingImports]

    headers: dict[str, tuple[str, str]] = {}
    with tempfile.TemporaryDirectory() as tmp:
        for name in FIXTURES:
            out = Path(tmp) / (name + ".wasm")
            subprocess.run([str(wabt_package.get_executable("wat2wasm")), str(DATA / name), "-o", str(out)], check=True)
            headers[name] = generated_of(out.read_bytes())
    return headers


def main(argv: list[str]) -> int:
    now = extract(_build_fixtures())
    if argv == ["--update"]:
        DECLARATION.parent.mkdir(exist_ok=True)
        DECLARATION.write_text(dumps(now), encoding="utf-8")
        print(f"written: {DECLARATION}")
        return 0
    declared: Surface = json.loads(DECLARATION.read_text(encoding="utf-8"))
    print(describe(declared, now) if declared != now else "the declaration is the code")
    return 1 if declared != now else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
