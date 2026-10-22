"""Repair, in the C of wasm2c, the element segments that hold an imported function: the module instance of such an entry must be the pointer
`instance->w2c_<import>`, and wasm2c writes `(char*)instance + offsetof(..., w2c_<import>)` (the address of the field; with offset 0 it is the instance itself)."""
import re, sys, pathlib
def patch(text: str) -> str:
    if "RefImportFunc" in text: return text
    text = text.replace("typedef enum { RefFunc, RefNull, GlobalGet } wasm_elem_segment_expr_type_t;",
                        "typedef enum { RefFunc, RefNull, GlobalGet, RefImportFunc } wasm_elem_segment_expr_type_t;")
    text = text.replace("      case RefNull:\n        *dest_val = wasm_rt_funcref_null_value;",
        "      case RefImportFunc:\n        *dest_val = (wasm_rt_funcref_t){\n            src_expr->type, src_expr->func, src_expr->func_tailcallee,\n"
        "            *(void**)((char*)module_instance + src_expr->module_offset)};\n        break;\n      case RefNull:\n        *dest_val = wasm_rt_funcref_null_value;", 1)
    return re.sub(r"\{RefFunc, ([^\n]*?), offsetof\(", r"{RefImportFunc, \1, offsetof(", text)
if __name__ == "__main__":
    for p in sys.argv[1:]:
        f = pathlib.Path(p); t = f.read_text(); n = patch(t)
        if n != t: f.write_text(n); print("patched", p, "entries:", n.count("{RefImportFunc,"))
