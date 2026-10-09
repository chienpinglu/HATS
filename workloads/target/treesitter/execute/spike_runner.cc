// Original checked platform harness. All RV64 instruction semantics are Spike's.
#include "processor.h"
#include "simif.h"
#include "platform.h"
#include "../bulk/digest.h"
#include <memory>
#include <cstring>
#include <fstream>
#include <iostream>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>

static uint64_t number(const std::string &s) {
  if (s.empty() || s.find_first_not_of("0123456789") != std::string::npos) throw std::runtime_error("invalid unsigned integer");
  size_t used; auto n = std::stoull(s, &used); if (used != s.size()) throw std::runtime_error("invalid integer"); return n;
}
static std::vector<uint8_t> load(const char *path, size_t maximum) {
  std::ifstream f(path, std::ios::binary | std::ios::ate);
  if (!f || f.tellg() < 0 || (uint64_t)f.tellg() > maximum) throw std::runtime_error("invalid input file");
  std::vector<uint8_t> result((size_t)f.tellg()); f.seekg(0);
  if (!f.read((char *)result.data(), result.size())) throw std::runtime_error("input read failure");
  return result;
}
class Environment final : public simif_t {
 public:
  cfg_t cfg; std::map<size_t, processor_t*> harts;
  std::vector<uint8_t> code, data;
  uint64_t code_bytes, writable_start, bss_end, loads = 0, stores = 0;
  std::ofstream trace;
  std::unique_ptr<EventDigest> digest;
  Environment() { cfg.isa = "RV64I"; cfg.priv = "M"; cfg.pmpregions = 0; cfg.hartids = {0}; }
  char *addr_to_mem(reg_t) override { return nullptr; }
  const cfg_t &get_cfg() const override { return cfg; }
  const std::map<size_t, processor_t*> &get_harts() const override { return harts; }
  const char *get_symbol(uint64_t) override { return nullptr; }
  void proc_reset(unsigned) override {}
  static bool span(uint64_t a, size_t n, uint64_t lo, uint64_t hi) { return a >= lo && a < hi && n <= hi-a; }
  bool mmio_fetch(reg_t a, size_t n, uint8_t *p) override {
    if (!span(a, n, 0, code_bytes)) return false;
    memcpy(p, code.data()+a, n); return true;
  }
  bool access(reg_t a, size_t n, uint8_t *p, bool store) {
    if (n != 1 && n != 2 && n != 4 && n != 8) throw std::runtime_error("unsupported transaction width");
    bool common = span(a,n,HATS_OUTPUT,HATS_OUTPUT+HATS_OUTPUT_BYTES) ||
                  span(a,n,HATS_HEAP,HATS_HEAP+HATS_HEAP_BYTES) || span(a,n,HATS_STACK_BASE,HATS_STACK_TOP);
    bool permitted = common || span(a,n,store ? writable_start : HATS_DATA_BASE,bss_end) ||
                     (!store && (span(a,n,HATS_ARGUMENT,HATS_ARGUMENT+64) ||
                      span(a,n,HATS_OLD,HATS_OLD+HATS_INPUT_MAX) || span(a,n,HATS_NEW,HATS_NEW+HATS_INPUT_MAX)));
    if (!permitted) return false;
    if (store) { memcpy(data.data()+a-HATS_DATA_BASE,p,n); stores++; }
    else { memcpy(p,data.data()+a-HATS_DATA_BASE,n); loads++; }
    if (trace.is_open()) {
      uint64_t value = 0; for (size_t i=0;i<n;i++) value |= uint64_t(p[i])<<(8*i);
      trace << "{\"kind\":\"memory\",\"address\":\"" << a << "\",\"bytes\":" << n
            << ",\"write\":" << (store ? "true" : "false") << ",\"data\":\"" << value << "\",\"error\":false}\n";
    }
    if (digest) {
      uint64_t value=0; for(size_t i=0;i<n;i++) value |= uint64_t(p[i])<<(8*i);
      digest->access(a,n,store,value);
    }
    return true;
  }
  bool mmio_load(reg_t a, size_t n, uint8_t *p) override { return access(a,n,p,false); }
  bool mmio_store(reg_t a, size_t n, const uint8_t *p) override { return access(a,n,const_cast<uint8_t*>(p),true); }
};
int main(int argc, char **argv) {
  try {
    if (argc < 10 || argc > 12) throw std::runtime_error("code data properties args old new result report max_steps [trace|-] [digest]");
    Environment env;
    env.code=load(argv[1],0x40000); env.data=load(argv[2],HATS_DATA_END-HATS_DATA_BASE);
    if (env.code.size()!=0x40000 || env.data.size()!=HATS_DATA_END-HATS_DATA_BASE) throw std::runtime_error("wrong image size");
    std::ifstream prop(argv[3]); std::map<std::string,uint64_t> p; std::string line;
    while (std::getline(prop,line)) { auto pos=line.find('='); if(pos==std::string::npos) throw std::runtime_error("bad property");
      if(!p.emplace(line.substr(0,pos),number(line.substr(pos+1))).second) throw std::runtime_error("duplicate property"); }
    if (p.size()!=4) throw std::runtime_error("incomplete properties");
    env.code_bytes=p.at("code_bytes"); env.writable_start=p.at("writable_start"); env.bss_end=p.at("bss_end");
    if(!env.code_bytes || env.code_bytes>env.code.size() || env.writable_start<HATS_DATA_BASE ||
        env.bss_end<env.writable_start || env.bss_end>HATS_ARGUMENT || p.at("exit_pc")>=env.code_bytes) throw std::runtime_error("bad memory map");
    auto args=load(argv[4],64), old=load(argv[5],HATS_INPUT_MAX), updated=load(argv[6],HATS_INPUT_MAX);
    if(args.size()!=64) throw std::runtime_error("wrong argument size");
    memcpy(env.data.data()+HATS_ARGUMENT-HATS_DATA_BASE,args.data(),args.size());
    memcpy(env.data.data()+HATS_OLD-HATS_DATA_BASE,old.data(),old.size());
    memcpy(env.data.data()+HATS_NEW-HATS_DATA_BASE,updated.data(),updated.size());
    memset(env.data.data()+HATS_OUTPUT-HATS_DATA_BASE,0xcc,HATS_OUTPUT_BYTES);
    if(argc>=11 && std::string(argv[10])!="-") { env.trace.open(argv[10]); if(!env.trace) throw std::runtime_error("trace open failed"); }
    if(argc==12) env.digest=std::make_unique<EventDigest>();
    FILE *raw_log = std::fopen("/dev/null", "w");
    if(!raw_log) throw std::runtime_error("cannot open diagnostic sink");
    processor_t cpu("RV64I","M",&env.cfg,&env,0,false,raw_log,std::cerr); env.harts[0]=&cpu;
    if(env.trace.is_open()) cpu.enable_log_commits();
    auto *s=cpu.get_state(); s->pc=0;
    for(size_t i=0;i<32;i++) s->XPR.write(i,0);
    s->XPR.write(10,HATS_ARGUMENT); s->mtvec->write(0x80000);
    uint64_t retired=0, minimum_sp=HATS_STACK_TOP, limit=number(argv[9]);
    if(!limit || limit>UINT64_C(2000000000)) throw std::runtime_error("invalid step limit");
    for(uint64_t count=0;count<limit;count++) {
      uint64_t pc=s->pc, before=s->minstret->read(); uint32_t instruction=0;
      if(pc+4<=env.code_bytes) memcpy(&instruction,env.code.data()+pc,4);
      cpu.step(1);
      if(s->minstret->read()==before) {
        if(s->pc!=0x80000 || s->mcause->read()!=3 || s->mepc->read()!=p.at("exit_pc"))
          throw std::runtime_error("unexpected trap cause="+std::to_string(s->mcause->read())+" pc="+std::to_string(s->mepc->read())+" value="+std::to_string(s->mtval->read()));
        if(env.trace.is_open()) env.trace << "{\"kind\":\"trap\",\"pc\":\"" << pc << "\",\"cause\":3,\"value\":\"" << s->XPR[10] << "\"}\n";
        if(env.digest) { env.digest->trap(pc,3,s->XPR[10]); env.digest->save(argv[11]); }
        std::ofstream result(argv[7],std::ios::binary); result.write((char*)env.data.data()+HATS_OUTPUT-HATS_DATA_BASE,HATS_OUTPUT_BYTES);
        std::ofstream report(argv[8]); report << "{\"status\":\"executed\",\"result\":" << s->XPR[10]
          << ",\"retired\":" << retired << ",\"loads\":" << env.loads << ",\"stores\":" << env.stores
          << ",\"observed_stack_pointer_bytes\":" << HATS_STACK_TOP-minimum_sp << ",\"exit_pc\":" << pc << "}\n";
        if(!result || !report) throw std::runtime_error("output write failed");
        return 0;
      }
      if(s->minstret->read()!=before+1) throw std::runtime_error("unexpected retirement count");
      retired++;
      if(env.digest) {
        std::array<uint64_t,32> registers{}; for(size_t i=0;i<32;i++) registers[i]=s->XPR[i];
        env.digest->retire(pc,instruction,s->pc,registers);
      }
      if(s->XPR[2]) {
        uint64_t sp=s->XPR[2]; if(sp<HATS_STACK_BASE || sp>HATS_STACK_TOP || sp%16) throw std::runtime_error("stack bound/alignment violation");
        minimum_sp=std::min(minimum_sp,sp);
      }
      if(env.trace.is_open()) {
        unsigned rd=0; for(const auto &entry:s->log_reg_write) if((entry.first&15)==0 && (entry.first>>4)) {
          if(rd) throw std::runtime_error("multiple destinations"); rd=entry.first>>4;
        }
        env.trace << "{\"kind\":\"retire\",\"pc\":\""<<pc<<"\",\"instruction\":"<<instruction
          <<",\"writes\":"<<(rd?"true":"false")<<",\"rd\":"<<rd<<",\"value\":\""<<(rd?s->XPR[rd]:0)<<"\",\"next\":\""<<s->pc<<"\"}\n";
      }
    }
    throw std::runtime_error("instruction budget exhausted");
  } catch(const std::exception &error) { std::cerr<<error.what()<<"\n"; return 1; }
}
