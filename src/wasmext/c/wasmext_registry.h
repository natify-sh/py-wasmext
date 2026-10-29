/* The registry of owners of a store: who the members of the store are, found by the pointer that a `funcref` of wasm2c carries (`module_instance`) and by a handle that
   does not lie. A member lives until the store is closed (as in Wasmtime, whose Store frees its instances only when it is dropped). No Python, no module; the lock is the
   store's (wasmext_store.h wraps these functions), this file is the data. See docs/step4_owners.md.

   The handle `wasmext_owner` is 64 bits: the serial of the store (16 bits), the index of the slot (24) and its generation (24). A slot that is freed and used again has
   another generation, so a stale handle is recognised; a handle of another store has another serial. 0 is none. */
#ifndef WASMEXT_REGISTRY_H
#define WASMEXT_REGISTRY_H

#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#define WASMEXT_REGISTRY_VERSION 1u

typedef uint64_t wasmext_owner;

/* What the store does with a member (any of them may be NULL). `retain` is called once when the member is registered, `release` once at the close, after `close`: they are
   for an object that a front end must keep (a Python object); `unlink` and `close` are for a member that holds resources (an instance): the close first runs `unlink` of every
   member in the reverse order of the registration, so that an importer lets go of what it was linked to, and then `close` of every member in the same order. */
typedef struct {
    void (*retain)(void *object);
    void (*release)(void *object);
    void (*unlink)(void *object);
    void (*close)(void *object);
} wasmext_owner_ops;

typedef struct {
    void *key;
    void *object;
    const wasmext_owner_ops *ops;
    uint64_t sequence; /* the order of registration */
    uint32_t generation;
    uint32_t next_free; /* index + 1 of the next free slot, in a free slot */
    uint8_t used;
} wasmext_slot;

#define WASMEXT_TABLE_EMPTY 0u
#define WASMEXT_TABLE_DELETED 0xFFFFFFFFu
#define WASMEXT_OWNER_MAX_SLOTS (1u << 24)

typedef struct {
    uint32_t version, size; /* of this struct: the record of the store in step 8 carries it, and a reader checks both */
    uint32_t serial;        /* of the store */
    wasmext_slot *slots;
    uint32_t count, capacity;
    uint32_t free_head; /* index + 1 */
    uint64_t sequence;
    uint32_t *table; /* open addressing, index + 1 of a slot; 0 empty, WASMEXT_TABLE_DELETED a removed one */
    uint32_t table_capacity;
    uint32_t deleted; /* removed entries in the table: it is rehashed when they are many, or a search would find no empty place to stop at */
} wasmext_registry;

static inline void wasmext_registry_init(wasmext_registry *r, uint32_t serial) {
    memset(r, 0, sizeof *r);
    r->version = WASMEXT_REGISTRY_VERSION;
    r->size = (uint32_t)sizeof *r;
    r->serial = serial;
}
static inline void wasmext_registry_destroy(wasmext_registry *r) {
    free(r->slots);
    free(r->table);
    memset(r, 0, sizeof *r);
}

static inline uint32_t wasmext_registry_hash_(const void *key) {
    uintptr_t x = (uintptr_t)key;
    x ^= x >> 17;
    x *= (uintptr_t)0x9E3779B97F4A7C15ull;
    x ^= x >> 29;
    return (uint32_t)x;
}

static inline wasmext_owner wasmext_registry_handle_(const wasmext_registry *r, uint32_t index) {
    return ((uint64_t)(r->serial & 0xFFFFu) << 48) | ((uint64_t)index << 24) | r->slots[index].generation;
}

/* the slot of `key` in the table (index in `slots`), or -1 */
static inline int64_t wasmext_registry_lookup_(const wasmext_registry *r, const void *key) {
    uint32_t mask, i;
    if (r->table_capacity == 0) return -1;
    mask = r->table_capacity - 1;
    for (i = wasmext_registry_hash_(key) & mask;; i = (i + 1) & mask) {
        uint32_t t = r->table[i];
        if (t == WASMEXT_TABLE_EMPTY) return -1;
        if (t != WASMEXT_TABLE_DELETED && r->slots[t - 1].used && r->slots[t - 1].key == key) return (int64_t)(t - 1);
    }
}

static inline int wasmext_registry_rehash_(wasmext_registry *r, uint32_t capacity) {
    uint32_t *table = (uint32_t *)calloc(capacity, sizeof(uint32_t));
    uint32_t i, mask = capacity - 1;
    if (table == NULL) return 1;
    for (i = 0; i < r->count; i++) {
        uint32_t j;
        if (!r->slots[i].used) continue;
        for (j = wasmext_registry_hash_(r->slots[i].key) & mask; table[j] != WASMEXT_TABLE_EMPTY; j = (j + 1) & mask) {}
        table[j] = i + 1;
    }
    free(r->table);
    r->table = table;
    r->table_capacity = capacity;
    r->deleted = 0;
    return 0;
}

/* results */
#define WASMEXT_REGISTRY_OK 0
#define WASMEXT_REGISTRY_NOMEM 3
#define WASMEXT_REGISTRY_DUPLICATE 4 /* the key is a member already */
#define WASMEXT_REGISTRY_UNKNOWN 5   /* no member has this key */
#define WASMEXT_REGISTRY_WRONG_STORE 6 /* the handle is of another store */
#define WASMEXT_REGISTRY_STALE 7       /* the handle is of a member that is gone */

static inline int wasmext_registry_add(wasmext_registry *r, void *key, void *object, const wasmext_owner_ops *ops, wasmext_owner *out) {
    uint32_t index, j, mask;
    wasmext_slot *slot;
    if (wasmext_registry_lookup_(r, key) >= 0) return WASMEXT_REGISTRY_DUPLICATE;
    if (r->table_capacity == 0 || (r->count + 1) * 2 > r->table_capacity || r->deleted * 4 > r->table_capacity) {
        uint32_t capacity = r->table_capacity ? r->table_capacity : 16u;
        while ((r->count + 1) * 2 > capacity) capacity *= 2;
        if (wasmext_registry_rehash_(r, capacity)) return WASMEXT_REGISTRY_NOMEM;
    }
    if (r->free_head != 0) {
        index = r->free_head - 1;
        r->free_head = r->slots[index].next_free;
    } else {
        if (r->count == r->capacity) {
            uint32_t capacity = r->capacity ? r->capacity * 2 : 8u;
            wasmext_slot *slots;
            if (capacity > WASMEXT_OWNER_MAX_SLOTS) capacity = WASMEXT_OWNER_MAX_SLOTS;
            if (r->count >= capacity) return WASMEXT_REGISTRY_NOMEM;
            slots = (wasmext_slot *)realloc(r->slots, capacity * sizeof(wasmext_slot));
            if (slots == NULL) return WASMEXT_REGISTRY_NOMEM;
            r->slots = slots;
            r->capacity = capacity;
        }
        index = r->count++;
        memset(&r->slots[index], 0, sizeof(wasmext_slot));
        r->slots[index].generation = 1;
        /* the table is rehashed over the slots in use only, so a slot that is not used yet needs no entry */
    }
    slot = &r->slots[index];
    slot->key = key;
    slot->object = object;
    slot->ops = ops;
    slot->sequence = ++r->sequence;
    slot->used = 1;
    mask = r->table_capacity - 1;
    for (j = wasmext_registry_hash_(key) & mask; r->table[j] != WASMEXT_TABLE_EMPTY && r->table[j] != WASMEXT_TABLE_DELETED; j = (j + 1) & mask) {}
    if (r->table[j] == WASMEXT_TABLE_DELETED) r->deleted--;
    r->table[j] = index + 1;
    if (ops != NULL && ops->retain != NULL) ops->retain(object);
    *out = wasmext_registry_handle_(r, index);
    return WASMEXT_REGISTRY_OK;
}

static inline int wasmext_registry_find(const wasmext_registry *r, const void *key, wasmext_owner *out) {
    int64_t index = wasmext_registry_lookup_(r, key);
    if (index < 0) return WASMEXT_REGISTRY_UNKNOWN;
    *out = wasmext_registry_handle_(r, (uint32_t)index);
    return WASMEXT_REGISTRY_OK;
}

/* the slot of a handle, or the reason it has none */
static inline int wasmext_registry_slot_(const wasmext_registry *r, wasmext_owner owner, uint32_t *index) {
    uint32_t i = (uint32_t)((owner >> 24) & 0xFFFFFFu), generation = (uint32_t)(owner & 0xFFFFFFu);
    if (owner == 0) return WASMEXT_REGISTRY_STALE; /* none */
    if ((uint32_t)(owner >> 48) != (r->serial & 0xFFFFu)) return WASMEXT_REGISTRY_WRONG_STORE;
    if (i >= r->count || !r->slots[i].used || r->slots[i].generation != generation) return WASMEXT_REGISTRY_STALE;
    *index = i;
    return WASMEXT_REGISTRY_OK;
}

static inline int wasmext_registry_object(const wasmext_registry *r, wasmext_owner owner, void **object) {
    uint32_t i;
    int rc = wasmext_registry_slot_(r, owner, &i);
    if (rc != WASMEXT_REGISTRY_OK) return rc;
    *object = r->slots[i].object;
    return WASMEXT_REGISTRY_OK;
}

/* Takes a member out. Its slot is used again later with another generation. The ops of the member are NOT run: the caller does what the close would (this is for a member that
   never had resources, or for the close itself). */
static inline int wasmext_registry_remove(wasmext_registry *r, wasmext_owner owner) {
    uint32_t i, j, mask;
    int rc = wasmext_registry_slot_(r, owner, &i);
    if (rc != WASMEXT_REGISTRY_OK) return rc;
    mask = r->table_capacity - 1;
    for (j = wasmext_registry_hash_(r->slots[i].key) & mask; r->table[j] != i + 1; j = (j + 1) & mask) {}
    r->table[j] = WASMEXT_TABLE_DELETED;
    r->deleted++;
    r->slots[i].used = 0;
    r->slots[i].generation = (r->slots[i].generation + 1) & 0xFFFFFFu;
    if (r->slots[i].generation == 0) r->slots[i].generation = 1;
    r->slots[i].next_free = r->free_head;
    r->free_head = i + 1;
    return WASMEXT_REGISTRY_OK;
}

/* walks the members in the order of the registration */
static inline int wasmext_registry_each_cmp_(const void *a, const void *b) {
    uint64_t x = (*(const wasmext_slot *const *)a)->sequence, y = (*(const wasmext_slot *const *)b)->sequence;
    return x < y ? -1 : x > y;
}
/* the slots in use, newest first, in a new array (the caller frees it); NULL with *n = 0 when there are none or no memory */
static inline wasmext_slot **wasmext_registry_newest_first(const wasmext_registry *r, uint32_t *n) {
    wasmext_slot **list = NULL;
    uint32_t i, used = 0;
    *n = 0;
    for (i = 0; i < r->count; i++) used += r->slots[i].used;
    if (used == 0) return NULL;
    list = (wasmext_slot **)malloc(used * sizeof(wasmext_slot *));
    if (list == NULL) return NULL;
    for (i = 0, used = 0; i < r->count; i++)
        if (r->slots[i].used) list[used++] = &r->slots[i];
    qsort(list, used, sizeof(wasmext_slot *), wasmext_registry_each_cmp_);
    for (i = 0; i < used / 2; i++) {
        wasmext_slot *t = list[i];
        list[i] = list[used - 1 - i];
        list[used - 1 - i] = t;
    }
    *n = used;
    return list;
}

#endif
