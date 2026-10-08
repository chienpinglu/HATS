/* Original measurement interposition: retain upstream atomic values and orders. */
#include <stddef.h>
#include <stdint.h>
uint32_t hats_atomic_add_fetch(volatile uint32_t *, uint32_t, int);
uint32_t hats_atomic_sub_fetch(volatile uint32_t *, uint32_t, int);
size_t hats_atomic_load_n(const volatile size_t *, int);
