// Original HATS harness around unmodified upstream Spike. No ISA implementation.
#include "processor.h"
#include "simif.h"
#include <array>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <map>
#include <stdexcept>
#include <string>

class ApeEnvironment final : public simif_t {
 public:
  cfg_t cfg;
  std::map<size_t, processor_t*> harts;
  std::array<uint8_t, 4096> code{};
  std::array<uint8_t, 65536> data{};
  bool writable, bus_error;

  ApeEnvironment(bool w, bool e) : writable(w), bus_error(e) {
    cfg.isa = "RV64I";
    cfg.priv = "M";
    cfg.pmpregions = 0;
    cfg.hartids = {0};
    const uint64_t words[] = {7, 13, UINT64_MAX, 128, 255, 1024, 0, 42};
    for (size_t i = 0; i < 8; ++i)
      for (size_t j = 0; j < 8; ++j) data[8*i+j] = words[i] >> (8*j);
  }
  char* addr_to_mem(reg_t) override { return nullptr; }
  const cfg_t& get_cfg() const override { return cfg; }
  const std::map<size_t, processor_t*>& get_harts() const override { return harts; }
  const char* get_symbol(uint64_t) override { return nullptr; }
  void proc_reset(unsigned) override {}
  bool mmio_fetch(reg_t addr, size_t len, uint8_t* bytes) override {
    if (addr >= code.size() || len > code.size() - addr) return false;
    for (size_t i = 0; i < len; ++i) bytes[i] = code[addr+i];
    return true;
  }
  bool access(reg_t addr, size_t len, bool store, uint8_t* bytes) {
    // APE platform policy only. Alignment and instruction semantics belong to Spike.
    if (addr < 0x10000 || addr >= 0x20000 || len > 0x20000 - addr ||
        (store && !writable)) return false;
    if (len != 1 && len != 2 && len != 4 && len != 8)
      throw std::runtime_error("unsupported platform transaction width");
    uint64_t value = 0;
    if (store) {
      for (size_t i = 0; i < len; ++i) value |= uint64_t(bytes[i]) << (8*i);
      if (!bus_error) for (size_t i = 0; i < len; ++i) data[addr-0x10000+i] = bytes[i];
    } else if (!bus_error) {
      for (size_t i = 0; i < len; ++i) {
        bytes[i] = data[addr-0x10000+i];
        value |= uint64_t(bytes[i]) << (8*i);
      }
    }
    std::cout << "{\"kind\":\"memory\",\"address\":\"" << addr
              << "\",\"bytes\":" << len << ",\"write\":" << (store ? "true" : "false")
              << ",\"data\":\"" << value << "\",\"error\":" << (bus_error ? "true" : "false") << "}\n";
    return !bus_error;
  }
  bool mmio_load(reg_t addr, size_t len, uint8_t* bytes) override { return access(addr, len, false, bytes); }
  bool mmio_store(reg_t addr, size_t len, const uint8_t* bytes) override {
    // access does not modify bytes on a store.
    return access(addr, len, true, const_cast<uint8_t*>(bytes));
  }
};

int main(int argc, char** argv) {
  try {
    if (argc != 6 && argc != 8)
      throw std::runtime_error("usage: adapter image.hex entry writable bus_error raw-log [data.bin argument]");
    for (int i : {3, 4})
      if (std::string(argv[i]) != "0" && std::string(argv[i]) != "1") throw std::runtime_error("bad boolean");
    size_t consumed = 0;
    uint64_t entry = std::stoull(argv[2], &consumed, 10);
    if (consumed != std::string(argv[2]).size()) throw std::runtime_error("bad entry");
    ApeEnvironment env(std::string(argv[3]) == "1", std::string(argv[4]) == "1");
    uint64_t argument = 0;
    if (argc == 8) {
      std::ifstream data(argv[6], std::ios::binary);
      if (!data.read(reinterpret_cast<char*>(env.data.data()), env.data.size()) || data.peek() != EOF)
        throw std::runtime_error("data image must contain exactly 65536 bytes");
      argument = std::stoull(argv[7], &consumed, 10);
      if (consumed != std::string(argv[7]).size()) throw std::runtime_error("bad argument");
    }
    std::ifstream input(argv[1]);
    if (!input) throw std::runtime_error("missing code image");
    std::string line;
    size_t offset = 0;
    while (std::getline(input, line)) {
      if (line.size() != 8 || offset + 4 > env.code.size() ||
          line.find_first_not_of("0123456789abcdefABCDEF") != std::string::npos)
        throw std::runtime_error("invalid code image");
      uint32_t word = std::stoul(line, nullptr, 16);
      for (size_t i = 0; i < 4; ++i) env.code[offset++] = word >> (8*i);
    }
    if (!offset) throw std::runtime_error("empty code image");
    FILE* log = std::fopen(argv[5], "w");
    if (!log) throw std::runtime_error("cannot open raw Spike log");
    // Spike is responsible for decode, execution, register writes, PC and traps.
    processor_t cpu("RV64I", "M", &env.cfg, &env, 0, false, log, std::cerr);
    env.harts[0] = &cpu;
    cpu.enable_log_commits();
    auto* s = cpu.get_state();
    s->pc = entry;
    for (size_t i = 0; i < 32; ++i) s->XPR.write(i, 0);
    s->XPR.write(10, argument);
    s->mtvec->write(0x30000);
    for (size_t count = 0; count < 200000; ++count) {
      const uint64_t pc = s->pc;
      const uint64_t before = s->minstret->read();
      uint32_t insn = 0;
      if (pc <= env.code.size()-4)
        for (size_t j = 0; j < 4; ++j) insn |= uint32_t(env.code[pc+j]) << (8*j);
      cpu.step(1);
      if (s->minstret->read() == before) {
        if (s->pc != 0x30000) throw std::runtime_error("no retirement without expected trap entry");
        std::cout << "{\"kind\":\"trap\",\"pc\":\"" << s->mepc->read()
                  << "\",\"cause\":" << s->mcause->read() << ",\"value\":\"" << s->XPR[10] << "\"}\n";
        std::fflush(log);
        return 0;
      }
      if (s->minstret->read() != before + 1) throw std::runtime_error("step retired multiple instructions");
      unsigned rd = 0;
      for (const auto& pair : s->log_reg_write) {
        if ((pair.first & 15) == 0 && (pair.first >> 4) != 0) {
          if (rd) throw std::runtime_error("multiple integer destinations");
          rd = pair.first >> 4;
        }
      }
      std::cout << "{\"kind\":\"retire\",\"pc\":\"" << pc << "\",\"instruction\":" << insn
                << ",\"writes\":" << (rd ? "true" : "false") << ",\"rd\":" << rd
                << ",\"value\":\"" << (rd ? s->XPR[rd] : 0) << "\",\"next\":\"" << s->pc << "\"}\n";
    }
    throw std::runtime_error("reference instruction limit exceeded");
  } catch (const std::exception& e) {
    std::cerr << "Spike adapter failed: " << e.what() << "\n";
    return 1;
  }
}
