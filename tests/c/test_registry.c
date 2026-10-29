/* The registry of owners of a store, in plain C with members that are only counters (no module, no Python). Exit 0 and "ok" when all pass. */
#define WASMEXT_DEFINE_THREAD_STATE
#include <stdio.h>
#include "wasmext_store.h"

#ifdef _WIN32
#include <process.h>
typedef HANDLE thread_t;
#define THREAD_RESULT unsigned __stdcall
static void thread_start(thread_t *t, unsigned (__stdcall *f)(void *), void *arg) { *t = (HANDLE)_beginthreadex(NULL, 0, f, arg, 0, NULL); }
static void thread_join(thread_t t) { WaitForSingleObject(t, INFINITE); CloseHandle(t); }
#else
typedef pthread_t thread_t;
#define THREAD_RESULT void *
static void thread_start(thread_t *t, THREAD_RESULT (*f)(void *), void *arg) { pthread_create(t, NULL, f, arg); }
static void thread_join(thread_t t) { pthread_join(t, NULL); }
#endif

static int failures;
#define CHECK(COND) do { if (!(COND)) { fprintf(stderr, "%s:%d: check failed: %s\n", __FILE__, __LINE__, #COND); failures++; } } while (0)

/* members that record what the store does to them */
typedef struct { int id; int retained, released, unlinked, closed; } member_t;
static int order[64], order_n;
static void m_retain(void *o) { ((member_t *)o)->retained++; }
static void m_release(void *o) { ((member_t *)o)->released++; order[order_n++] = 3000 + ((member_t *)o)->id; }
static void m_unlink(void *o) { ((member_t *)o)->unlinked++; order[order_n++] = 1000 + ((member_t *)o)->id; }
static void m_close(void *o) { ((member_t *)o)->closed++; order[order_n++] = 2000 + ((member_t *)o)->id; }
static const wasmext_owner_ops ops = {m_retain, m_release, m_unlink, m_close};

static void test_basics(void) {
    wasmext_store *s = wasmext_store_new();
    member_t a = {1, 0, 0, 0, 0}, b = {2, 0, 0, 0, 0}, c = {3, 0, 0, 0, 0};
    int ka, kb, kc;
    wasmext_owner oa, ob, found;
    void *object;
    CHECK(wasmext_store_register(s, &ka, &a, &ops, &oa) == WASMEXT_STORE_OK && oa != 0);
    CHECK(wasmext_store_register(s, &kb, &b, &ops, &ob) == WASMEXT_STORE_OK && ob != oa);
    CHECK(a.retained == 1 && b.retained == 1);
    CHECK(wasmext_store_register(s, &ka, &b, &ops, &found) == WASMEXT_STORE_DUPLICATE && b.retained == 1); /* a key is a member once */
    CHECK(wasmext_store_find(s, &ka, &found) == WASMEXT_STORE_OK && found == oa);
    CHECK(wasmext_store_find(s, &kc, &found) == WASMEXT_STORE_UNKNOWN);
    CHECK(wasmext_store_member(s, oa, &object) == WASMEXT_STORE_OK && object == &a);
    CHECK(wasmext_store_member(s, 0, &object) == WASMEXT_STORE_STALE);
    /* a member taken out: its handle is stale, and its slot used again gets another generation */
    CHECK(wasmext_store_unregister(s, oa) == WASMEXT_STORE_OK);
    CHECK(wasmext_store_member(s, oa, &object) == WASMEXT_STORE_STALE);
    CHECK(wasmext_store_find(s, &ka, &found) == WASMEXT_STORE_UNKNOWN);
    CHECK(wasmext_store_unregister(s, oa) == WASMEXT_STORE_STALE);
    {
        wasmext_owner oc;
        CHECK(wasmext_store_register(s, &kc, &c, &ops, &oc) == WASMEXT_STORE_OK);
        CHECK(oc != oa && ((oc >> 24) & 0xFFFFFF) == ((oa >> 24) & 0xFFFFFF)); /* the same slot, another handle */
        CHECK(wasmext_store_member(s, oa, &object) == WASMEXT_STORE_STALE);    /* the old handle does not open the new member */
        CHECK(wasmext_store_member(s, oc, &object) == WASMEXT_STORE_OK && object == &c);
    }
    wasmext_store_free(s);
}

/* a handle of one store does not open a member of another, nor of a store made later at the same address */
static void test_other_stores(void) {
    wasmext_store *s1 = wasmext_store_new(), *s2 = wasmext_store_new(), *s3;
    member_t a = {1, 0, 0, 0, 0}, b = {2, 0, 0, 0, 0};
    int k;
    wasmext_owner o1, o2;
    void *object;
    CHECK(wasmext_store_register(s1, &k, &a, &ops, &o1) == WASMEXT_STORE_OK);
    CHECK(wasmext_store_register(s2, &k, &a, &ops, &o2) == WASMEXT_STORE_OK);
    CHECK(wasmext_store_member(s2, o1, &object) == WASMEXT_STORE_WRONG); /* the same slot and generation, another store */
    CHECK(wasmext_store_member(s1, o2, &object) == WASMEXT_STORE_WRONG);
    wasmext_store_free(s1);
    s3 = wasmext_store_new(); /* usually at the address of s1 */
    {
        wasmext_owner o3;
        CHECK(wasmext_store_register(s3, &k, &b, &ops, &o3) == WASMEXT_STORE_OK);
        CHECK(o3 != o1 && wasmext_store_member(s3, o1, &object) == WASMEXT_STORE_WRONG);
    }
    wasmext_store_free(s2);
    wasmext_store_free(s3);
}

/* many keys, with removals: the table is rehashed and no search loops */
static void test_many(void) {
    enum { N = 6000 };
    wasmext_store *s = wasmext_store_new();
    static char keys[N];
    static wasmext_owner owners[N];
    member_t m = {0, 0, 0, 0, 0};
    for (int i = 0; i < N; i++) CHECK(wasmext_store_register(s, &keys[i], &m, NULL, &owners[i]) == WASMEXT_STORE_OK);
    for (int i = 0; i < N; i += 2) CHECK(wasmext_store_unregister(s, owners[i]) == WASMEXT_STORE_OK);
    for (int round = 0; round < 5; round++) { /* remove and add again many times: the removed marks must not fill the table */
        for (int i = 0; i < N; i += 2) CHECK(wasmext_store_register(s, &keys[i], &m, NULL, &owners[i]) == WASMEXT_STORE_OK);
        for (int i = 0; i < N; i += 2) CHECK(wasmext_store_unregister(s, owners[i]) == WASMEXT_STORE_OK);
    }
    for (int i = 0; i < N; i++) {
        wasmext_owner found;
        int rc = wasmext_store_find(s, &keys[i], &found);
        CHECK(i % 2 ? (rc == WASMEXT_STORE_OK && found == owners[i]) : rc == WASMEXT_STORE_UNKNOWN);
    }
    wasmext_store_free(s);
}

/* a long churn of one member at a time with different keys: the table is full of removed marks unless it is rehashed, and a search would never find an empty place to stop at */
static void test_churn(void) {
    enum { N = 20000 };
    wasmext_store *s = wasmext_store_new();
    static char keys[N];
    member_t m = {0, 0, 0, 0, 0};
    wasmext_owner o, found;
    for (int i = 0; i < N; i++) {
        CHECK(wasmext_store_register(s, &keys[i], &m, NULL, &o) == WASMEXT_STORE_OK);
        CHECK(wasmext_store_unregister(s, o) == WASMEXT_STORE_OK);
    }
    CHECK(wasmext_store_find(s, &keys[0], &found) == WASMEXT_STORE_UNKNOWN); /* must come back */
    wasmext_store_free(s);
}

/* the close: unlink of every member newest first, then close of every member newest first, then release; the arena after, in its own order */
static void arena_release(void *o) { order[order_n++] = 4000 + *(int *)o; }
static void test_close_order(void) {
    wasmext_store *s = wasmext_store_new();
    member_t m[3];
    int keys[3], arena_a = 1, arena_b = 2;
    wasmext_owner o;
    order_n = 0;
    for (int i = 0; i < 3; i++) {
        memset(&m[i], 0, sizeof m[i]);
        m[i].id = i + 1;
        CHECK(wasmext_store_register(s, &keys[i], &m[i], &ops, &o) == WASMEXT_STORE_OK);
    }
    CHECK(wasmext_store_own(s, &arena_a, arena_release) == WASMEXT_STORE_OK && wasmext_store_own(s, &arena_b, arena_release) == WASMEXT_STORE_OK);
    CHECK(order_n == 0);
    CHECK(wasmext_store_close(s) == WASMEXT_STORE_OK);
    {
        int want[] = {1003, 1002, 1001, 2003, 2002, 2001, 3003, 3002, 3001, 4002, 4001};
        CHECK(order_n == 11 && memcmp(order, want, sizeof want) == 0);
    }
    for (int i = 0; i < 3; i++) CHECK(m[i].retained == 1 && m[i].released == 1 && m[i].unlinked == 1 && m[i].closed == 1);
    CHECK(wasmext_store_close(s) == WASMEXT_STORE_OK && order_n == 11); /* once */
    CHECK(wasmext_store_register(s, &arena_a, &m[0], &ops, &o) == WASMEXT_STORE_CLOSED); /* refused after the close */
    CHECK(wasmext_store_find(s, &keys[1], &o) == WASMEXT_STORE_OK); /* the members are still found, closed */
    wasmext_store_free(s);
}

static int visited;
static void count_visit(void *object, void *arg) { (void)object; (void)arg; visited++; }
static void test_each_and_adopt(void) {
    wasmext_store *s = wasmext_store_new();
    member_t a = {1, 0, 0, 0, 0}, b = {2, 0, 0, 0, 0};
    int ka, kb, thing = 0;
    wasmext_owner o;
    CHECK(wasmext_store_register(s, &ka, &a, NULL, &o) == WASMEXT_STORE_OK && wasmext_store_register(s, &kb, &b, NULL, &o) == WASMEXT_STORE_OK);
    CHECK(wasmext_store_own(s, &thing, NULL) == WASMEXT_STORE_OK);
    visited = 0;
    wasmext_store_each(s, count_visit, NULL);
    CHECK(visited == 3); /* two members and one object of the arena */
    /* what is adopted is freed when the store is freed, not when it is closed; and it can be taken back */
    {
        static int freed;
        int x = 0, y = 0;
        void (*free_fn)(void *) = NULL;
        (void)free_fn;
        CHECK(wasmext_store_adopt(s, &x, NULL) == WASMEXT_STORE_OK && wasmext_store_adopt(s, &y, NULL) == WASMEXT_STORE_OK);
        CHECK(wasmext_store_unadopt(s, &x) == WASMEXT_STORE_OK && wasmext_store_unadopt(s, &x) == WASMEXT_STORE_UNKNOWN);
        (void)freed;
    }
    wasmext_store_free(s);
}

typedef struct { wasmext_store *s; char *keys; int from, to; int failed; } work_t;
static THREAD_RESULT worker(void *arg) {
    work_t *w = (work_t *)arg;
    member_t m = {0, 0, 0, 0, 0};
    for (int n = 0; n < 200; n++)
        for (int i = w->from; i < w->to; i++) {
            wasmext_owner o, f;
            void *object;
            if (wasmext_store_register(w->s, &w->keys[i], &m, NULL, &o) != WASMEXT_STORE_OK) w->failed = 1;
            if (wasmext_store_find(w->s, &w->keys[i], &f) != WASMEXT_STORE_OK || f != o) w->failed = 1;
            if (wasmext_store_member(w->s, o, &object) != WASMEXT_STORE_OK || object != &m) w->failed = 1;
            if (wasmext_store_unregister(w->s, o) != WASMEXT_STORE_OK) w->failed = 1;
        }
    return 0;
}
static void test_threads(void) {
    enum { N = 4, PER = 8 };
    wasmext_store *s = wasmext_store_new();
    static char keys[N * PER];
    work_t w[N];
    thread_t t[N];
    for (int k = 0; k < N; k++) { w[k].s = s; w[k].keys = keys; w[k].from = k * PER; w[k].to = (k + 1) * PER; w[k].failed = 0; thread_start(&t[k], worker, &w[k]); }
    for (int k = 0; k < N; k++) { thread_join(t[k]); CHECK(!w[k].failed); }
    wasmext_store_free(s);
}

int main(void) {
    test_basics();
    test_other_stores();
    test_many();
    test_churn();
    test_close_order();
    test_each_and_adopt();
    test_threads();
    if (failures) { fprintf(stderr, "%d failed\n", failures); return 1; }
    puts("ok");
    return 0;
}
