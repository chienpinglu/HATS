// Native component test only. It does not execute APE or measure HATS performance.
#include "service_schedule.h"
#include <cassert>
#include <iostream>
#include <vector>

using hats::s03::Delays;
using hats::s03::TransactionService;

template <typename F> void rejects(F f) {
  bool rejected = false;
  try { f(); } catch (const std::exception &) { rejected = true; }
  assert(rejected);
}

std::vector<Delays> run(unsigned arrivalPattern, unsigned responseBase) {
  TransactionService service(responseBase, 0x48415453);
  std::vector<Delays> observed;
  uint64_t cycle = 0;
  for (unsigned i = 0; i < 10000; ++i) {
    assert(service.idle() && service.ordinal() == i);
    cycle += 1 + ((i * arrivalPattern + 13) % (arrivalPattern + 1));
    assert(!service.requestReady(cycle, false));
    const auto first = cycle;
    while (!service.requestReady(cycle, true)) ++cycle;
    const auto accept = cycle;
    auto plan = service.delays();
    assert(accept - first == plan.acceptance && plan.acceptance <= 3);
    service.accepted(cycle);
    assert(!service.responseReady(cycle));
    rejects([&] { service.accepted(cycle); });
    rejects([&] { service.responseConsumed(cycle); });
    while (!service.responseReady(cycle)) {
      assert(!service.requestReady(cycle, true)); // cannot accept overlapping work
      ++cycle;
    }
    assert(cycle - accept == plan.response && plan.response >= responseBase && plan.response < responseBase + 8);
    const auto due = cycle;
    // Also hold the response for an arrival-dependent interval. It must neither
    // change this request's service nor advance the transaction ordinal early.
    cycle += (i + arrivalPattern) % 5;
    assert(service.responseReady(cycle) && service.ordinal() == i);
    observed.push_back({uint32_t(accept - first), uint32_t(due - accept)});
    service.responseConsumed(cycle);
    assert(!service.responseReady(cycle));
    rejects([&] { service.responseConsumed(cycle); });
  }
  return observed;
}

int main() {
  for (unsigned base : {2U, 8U, 32U}) {
    auto baseline = run(0, base);
    for (unsigned arrivals : {3U, 17U, 101U}) assert(run(arrivals, base) == baseline);
  }
  rejects([] { TransactionService s(0, 0); });
  rejects([] { TransactionService s(UINT32_MAX, 0); });
  TransactionService s(2, 0);
  (void)s.requestReady(10, true);
  rejects([&] { s.requestReady(11, false); });
  rejects([&] { s.requestReady(9, true); });
  std::cout << "Service schedule PASS: 120000 native transactions; identical realized delays across arrival patterns; not RTL performance\n";
}
