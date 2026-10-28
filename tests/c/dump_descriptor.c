/* Reads the descriptor of a module through `DESCRIBE()` and writes it as the canonical text of wasmext._model.ModuleModel.dump(). Plain C. */
#include <inttypes.h>
#include <stdio.h>
#include "wasmext_descriptor.h"

const wasmext_descriptor *DESCRIBE(void);

static void q(wasmext_str s) {
  putchar('"');
  for (uint32_t i = 0; i < s.n; i++) {
    unsigned char b = (unsigned char)s.p[i];
    if (b > 0x20 && b < 0x7F && b != '"' && b != '\\') putchar(b);
    else printf("\\x%02x", b);
  }
  putchar('"');
}

static void limits(const wasmext_limits *l) {
  printf("%" PRIu64 " ", l->min);
  if (l->has_max) printf("%" PRIu64, l->max); else printf("-1");
  printf(" %d %d", l->shared, l->is64);
}

static void functype(const wasmext_functype *f) {
  putchar('(');
  for (uint32_t i = 0; i < f->n_params; i++) printf(i ? " %d" : "%d", f->params[i]);
  printf(")->(");
  for (uint32_t i = 0; i < f->n_results; i++) printf(i ? " %d" : "%d", f->results[i]);
  putchar(')');
}

static const char *const kinds[] = {"func", "table", "memory", "global", "tag"};

int main(void) {
  const wasmext_descriptor *d = DESCRIBE();
  if (d->version != WASMEXT_DESCRIPTOR_VERSION || d->size != sizeof(wasmext_descriptor)) {
    fprintf(stderr, "descriptor version %u size %u\n", d->version, d->size);
    return 2;
  }
  printf("module "); q(d->name); putchar('\n');
  printf("flags %u\nstart %" PRId64 "\n", d->flags, d->start);
  for (uint32_t i = 0; i < d->n_memories; i++) { printf("memory %u ", i); limits(&d->memories[i]); putchar('\n'); }
  for (uint32_t i = 0; i < d->n_tables; i++) {
    printf("table %u %d ", i, d->tables[i].elem); limits(&d->tables[i].limits); putchar('\n');
  }
  for (uint32_t i = 0; i < d->n_globals; i++) printf("global %u %d %d\n", i, d->globals[i].type, d->globals[i].is_mutable);
  for (uint32_t i = 0; i < d->n_tags; i++) { printf("tag %u ", i); functype(&d->tags[i]); putchar('\n'); }
  for (uint32_t i = 0; i < d->n_imports; i++) {
    const wasmext_import_desc *m = &d->imports[i];
    printf("import %s ", kinds[m->kind]); q(m->module); putchar(' '); q(m->name);
    printf(" %u %d ", m->index, m->core);
    switch (m->kind) {
      case WASMEXT_DESC_FUNC: case WASMEXT_DESC_TAG: functype(&m->type); break;
      case WASMEXT_DESC_TABLE: printf("%d ", d->tables[m->index].elem); limits(&d->tables[m->index].limits); break;
      case WASMEXT_DESC_MEMORY: limits(&d->memories[m->index]); break;
      default: printf("%d %d", d->globals[m->index].type, d->globals[m->index].is_mutable); break;
    }
    putchar('\n');
  }
  for (uint32_t i = 0; i < d->n_exports; i++) {
    const wasmext_export_desc *e = &d->exports[i];
    printf("export %s ", kinds[e->kind]); q(e->name); printf(" %u ", e->index);
    switch (e->kind) {
      case WASMEXT_DESC_FUNC: case WASMEXT_DESC_TAG: functype(&e->type); break;
      case WASMEXT_DESC_TABLE: printf("%d ", d->tables[e->index].elem); limits(&d->tables[e->index].limits); break;
      case WASMEXT_DESC_MEMORY: limits(&d->memories[e->index]); break;
      default: printf("%d %d", d->globals[e->index].type, d->globals[e->index].is_mutable); break;
    }
    if (e->param_names) {
      printf(" names");
      for (uint32_t k = 0; k < e->type.n_params; k++) {
        putchar(' ');
        if (e->param_names[k].p) q(e->param_names[k]); else putchar('-');
      }
    }
    putchar('\n');
  }
  return 0;
}
