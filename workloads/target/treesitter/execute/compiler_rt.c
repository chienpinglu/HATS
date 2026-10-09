/* Original RV64I integer compiler helpers. No imported runtime implementation.
 * Unsigned operations avoid signed-overflow UB. Division by zero follows the
 * integer ISA convention; this does not make C division by zero defined. */
#include <stdint.h>

uint64_t __muldi3(uint64_t a, uint64_t b) {
  uint64_t r = 0;
  while (b) { if (b & 1) r += a; a <<= 1; b >>= 1; }
  return r;
}
static uint64_t divide(uint64_t n, uint64_t d, uint64_t *remainder) {
  uint64_t q = 0, r = 0;
  if (!d) { *remainder = n; return UINT64_MAX; }
  for (unsigned i = 64; i; i--) {
    uint64_t carry = r >> 63;
    r = (r << 1) | ((n >> (i - 1)) & 1);
    if (carry || r >= d) { r -= d; q |= UINT64_C(1) << (i - 1); }
  }
  *remainder = r;
  return q;
}
uint64_t __udivdi3(uint64_t a, uint64_t b) { uint64_t r; return divide(a, b, &r); }
uint64_t __umoddi3(uint64_t a, uint64_t b) { uint64_t r; (void)divide(a, b, &r); return r; }
int64_t __moddi3(int64_t a, int64_t b) {
  uint64_t x = (uint64_t)a, y = (uint64_t)b, r;
  if (a < 0) x = 0 - x;
  if (b < 0) y = 0 - y;
  (void)divide(x, y, &r);
  return (int64_t)(a < 0 ? 0 - r : r);
}
/* LP64 little-endian register pair, explicitly carried as two 64-bit limbs. */
typedef union { __uint128_t value; struct { uint64_t lo, hi; } limb; } U128;
__uint128_t __multi3(__uint128_t left, __uint128_t right) {
  U128 a = {.value = left}, b = {.value = right}, r = {.limb = {0, 0}};
  while (b.limb.lo || b.limb.hi) {
    if (b.limb.lo & 1) {
      uint64_t previous = r.limb.lo;
      r.limb.lo += a.limb.lo;
      r.limb.hi += a.limb.hi + (r.limb.lo < previous);
    }
    a.limb.hi = (a.limb.hi << 1) | (a.limb.lo >> 63); a.limb.lo <<= 1;
    b.limb.lo = (b.limb.lo >> 1) | (b.limb.hi << 63); b.limb.hi >>= 1;
  }
  return r.value;
}
