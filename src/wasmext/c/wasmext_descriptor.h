/* The descriptor of a built module: what the module is, as read-only data in the library, readable at run time by any host that can
 * call C. Plain C, no Python, no allocation. A module has `<name>_describe()`, which returns a pointer to it.
 *
 * Names are the WebAssembly names (UTF-8 bytes, with a length: a name may hold a zero byte), never the mangled C names. Value types
 * are the bytes of the binary format (0x7F i32, 0x7E i64, 0x7D f32, 0x7C f64, 0x7B v128, 0x70 funcref, 0x6F externref).
 * A reader checks `version` and `size` before it reads anything else. */
#ifndef WASMEXT_DESCRIPTOR_H
#define WASMEXT_DESCRIPTOR_H

#include <stdint.h>

#define WASMEXT_DESCRIPTOR_VERSION 1u

/* The kinds, in the order of the binary format of the exports. */
enum {
  WASMEXT_DESC_FUNC = 0,
  WASMEXT_DESC_TABLE = 1,
  WASMEXT_DESC_MEMORY = 2,
  WASMEXT_DESC_GLOBAL = 3,
  WASMEXT_DESC_TAG = 4
};

/* wasmext_descriptor.flags */
enum {
  WASMEXT_DESC_SHARE_TABLES = 1u, /* built with the tables shared between instances */
  WASMEXT_DESC_USES_CORE = 2u     /* the core answers some imports (WASI) */
};

typedef struct {
  const char *p;
  uint32_t n;
} wasmext_str;

typedef struct {
  uint32_t n_params, n_results;
  const uint8_t *params, *results;
} wasmext_functype;

typedef struct {
  uint64_t min, max; /* max is meaningful only if has_max */
  uint8_t has_max, shared, is64;
} wasmext_limits;

typedef struct {
  uint8_t elem;
  wasmext_limits limits;
} wasmext_table_desc;

typedef struct {
  uint8_t type, is_mutable;
} wasmext_global_desc;

typedef struct {
  wasmext_str module, name;
  uint8_t kind;
  uint8_t core;   /* 1: the core answers this import, the caller gives nothing */
  uint32_t index; /* in the imports of its kind (also the index in the arrays of memories, tables, globals, tags) */
  wasmext_functype type; /* for a function and a tag; zeros otherwise */
} wasmext_import_desc;

typedef struct {
  wasmext_str name;
  uint8_t kind;
  uint32_t index; /* in the index space of its kind: the imports first, then what the module defines */
  wasmext_functype type;       /* for a function and a tag; zeros otherwise */
  const wasmext_str *param_names; /* NULL, or n_params entries; an unnamed parameter has p == NULL */
} wasmext_export_desc;

typedef struct {
  uint32_t version, size; /* WASMEXT_DESCRIPTOR_VERSION and sizeof of this struct */
  wasmext_str name;       /* the module, as it is imported */
  uint32_t flags;
  uint32_t n_imports;  const wasmext_import_desc *imports;
  uint32_t n_exports;  const wasmext_export_desc *exports;
  uint32_t n_memories; const wasmext_limits *memories;      /* the whole index space: imported first */
  uint32_t n_tables;   const wasmext_table_desc *tables;    /* the same */
  uint32_t n_globals;  const wasmext_global_desc *globals;  /* the same */
  uint32_t n_tags;     const wasmext_functype *tags;        /* the same */
  int64_t start;       /* index of the start function, or -1 */
} wasmext_descriptor;

#endif
