#ifndef HATS_S03_SERVICE_SCHEDULE_H
#define HATS_S03_SERVICE_SCHEDULE_H

#include <cstdint>
#include <limits>
#include <stdexcept>

namespace hats::s03 {

struct Delays {
  uint32_t acceptance, response;
  bool operator==(const Delays &) const = default;
};

// Deterministic per-transaction service, never a cycle-indexed RNG. These are
// abstract cycle delays; the profile does not claim an HBM/LPDDR/DRAM latency.
inline Delays transactionDelays(uint64_t ordinal, uint32_t responseBase, uint64_t seed) {
  if (responseBase == 0 || responseBase > std::numeric_limits<uint32_t>::max() - 7)
    throw std::invalid_argument("response base must leave room for 0..7 jitter and be positive");
  uint64_t x = (ordinal ^ seed) + UINT64_C(0x9e3779b97f4a7c15);
  x = (x ^ (x >> 30)) * UINT64_C(0xbf58476d1ce4e5b9);
  x = (x ^ (x >> 27)) * UINT64_C(0x94d049bb133111eb);
  x ^= x >> 31;
  return {uint32_t(x & 3), responseBase + uint32_t((x >> 16) & 7)};
}

// One request/response outstanding, matching APE's present memory contract.
// Request backpressure is relative to first presentation, response delay to
// acceptance. Different processor arrival cycles receive the identical service
// sequence when ordinal, seed and responseBase are held fixed.
class TransactionService {
  uint32_t base_;
  uint64_t seed_, ordinal_ = 0, first_ = 0, due_ = 0;
  bool presented_ = false, pending_ = false;
  Delays current_{};

 public:
  TransactionService(uint32_t responseBase, uint64_t seed) : base_(responseBase), seed_(seed) {
    (void)transactionDelays(0, base_, seed_);
  }
  uint64_t ordinal() const { return ordinal_; }
  bool idle() const { return !presented_ && !pending_; }
  Delays delays() const { return current_; }
  bool requestReady(uint64_t cycle, bool valid) {
    if (pending_) return false;
    if (!valid) {
      if (presented_) throw std::logic_error("request withdrawn before acceptance");
      return false;
    }
    if (!presented_) {
      presented_ = true; first_ = cycle;
      current_ = transactionDelays(ordinal_, base_, seed_);
    }
    if (cycle < first_) throw std::logic_error("non-monotonic request clock");
    return cycle - first_ >= current_.acceptance;
  }
  void accepted(uint64_t cycle) {
    if (pending_ || !presented_ || cycle < first_ || cycle - first_ < current_.acceptance)
      throw std::logic_error("request accepted before service readiness");
    if (cycle > std::numeric_limits<uint64_t>::max() - current_.response)
      throw std::overflow_error("response clock overflow");
    due_ = cycle + current_.response;
    presented_ = false; pending_ = true;
  }
  bool responseReady(uint64_t cycle) const { return pending_ && cycle >= due_; }
  void responseConsumed(uint64_t cycle) {
    if (!responseReady(cycle)) throw std::logic_error("response consumed before due or without request");
    if (ordinal_ == std::numeric_limits<uint64_t>::max()) throw std::overflow_error("transaction ordinal overflow");
    pending_ = false; ++ordinal_;
  }
};

}  // namespace hats::s03
#endif
