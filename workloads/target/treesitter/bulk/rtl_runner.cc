// Original fast transport for Spinal-generated APE RTL. No host ISA/parser logic.
#include "VApeCore.h"
#include "verilated.h"
#include "digest.h"
#include "../execute/platform.h"
#include <algorithm>
#include <cstring>
#include <fstream>
#include <iostream>
#include <map>
#include <optional>
#include <random>
#include <string>
#include <vector>

static void check(bool yes,const char *message) { if(!yes) throw std::runtime_error(message); }
static std::vector<uint8_t> load(const std::string &path,size_t maximum) {
  std::ifstream f(path,std::ios::binary|std::ios::ate);
  check(bool(f)&&f.tellg()>=0&&uint64_t(f.tellg())<=maximum,"bad input file");
  std::vector<uint8_t> data(size_t(f.tellg())); f.seekg(0); f.read(reinterpret_cast<char*>(data.data()),data.size());
  check(bool(f),"read failed"); return data;
}
static bool span(uint64_t a,size_t n,uint64_t lo,uint64_t hi) { return a>=lo && a<hi && n<=hi-a; }
struct Request {
  uint64_t address,data; unsigned size; bool write;
  bool operator==(const Request &) const = default;
};
struct Reply { uint64_t due,data; bool error; };
int main(int argc,char **argv) {
  try {
    check(argc==6,"parser-folder case-folder output-prefix repetitions max-cycles");
    const std::string root=argv[1], input=argv[2], output=argv[3];
    unsigned repetitions=std::stoul(argv[4]); uint64_t maximum=std::stoull(argv[5]);
    check(repetitions>=1&&repetitions<=2&&maximum>0,"bad run limits");
    auto code=load(root+"/code.bin",0x40000), initial=load(root+"/data.bin",HATS_DATA_END-HATS_DATA_BASE);
    check(code.size()==0x40000&&initial.size()==HATS_DATA_END-HATS_DATA_BASE,"wrong image capacity");
    std::ifstream properties(root+"/runtime.properties"); std::map<std::string,uint64_t> p; std::string line;
    while(std::getline(properties,line)) { auto pos=line.find('='); check(pos!=std::string::npos,"bad map"); p.emplace(line.substr(0,pos),std::stoull(line.substr(pos+1))); }
    check(p.size()==4&&p.at("code_bytes")<=code.size()&&p.at("bss_end")<=HATS_ARGUMENT,"bad map capacity");
    VApeCore dut; dut.clk=0; dut.reset=1; dut.io_program_valid=0; dut.io_program_payload_index=0; dut.io_program_payload_instruction=0;
    dut.io_launch_valid=0; dut.io_launch_payload_pc=0; dut.io_launch_payload_argument=HATS_ARGUMENT;
    dut.io_launch_payload_base=HATS_DATA_BASE; dut.io_launch_payload_limit=HATS_DATA_END; dut.io_launch_payload_writable=1;
    dut.io_memory_ready=0; dut.io_response_valid=0; dut.io_response_payload_data=0; dut.io_response_payload_error=0; dut.io_halt_ready=0;
    auto edge=[&](){ dut.clk=1; dut.eval(); dut.clk=0; dut.eval(); };
    for(unsigned i=0;i<4;i++) edge(); dut.reset=0; edge();
    for(size_t i=0;i<code.size()/4;i++) {
      uint32_t word=0; memcpy(&word,code.data()+i*4,4); dut.io_program_valid=1;
      dut.io_program_payload_index=i; dut.io_program_payload_instruction=word; edge();
    }
    dut.io_program_valid=0;
    for(unsigned invocation=0;invocation<repetitions;invocation++) {
      auto memory=initial;
      auto overlay=[&](const std::string &name,uint64_t address,size_t max){ auto bytes=load(input+"/"+name,max); memcpy(memory.data()+address-HATS_DATA_BASE,bytes.data(),bytes.size()); };
      overlay("args.bin",HATS_ARGUMENT,64); overlay("old.bin",HATS_OLD,HATS_INPUT_MAX); overlay("new.bin",HATS_NEW,HATS_INPUT_MAX);
      std::fill(memory.begin()+HATS_OUTPUT-HATS_DATA_BASE,memory.begin()+HATS_OUTPUT-HATS_DATA_BASE+HATS_OUTPUT_BYTES,0xcc);
      std::array<uint64_t,32> registers{}; registers[10]=HATS_ARGUMENT;
      EventDigest digest; std::optional<Reply> pending; std::optional<Request> held;
      std::mt19937 rng(0x48415453+invocation); uint64_t cycles=0,requests=0,stalls=0,minimum_sp=HATS_STACK_TOP; bool halted=false;
      dut.io_launch_valid=1; dut.eval(); check(dut.io_launch_ready,"launch not ready"); edge(); dut.io_launch_valid=0;
      for(;cycles<maximum;cycles++) {
        dut.io_memory_ready=cycles%5>=2 && rng()%4!=0;
        bool reply=pending&&pending->due<=cycles;
        dut.io_response_valid=reply; dut.io_response_payload_data=reply?pending->data:0; dut.io_response_payload_error=reply&&pending->error;
        dut.eval();
        std::optional<Request> request;
        if(dut.io_memory_valid) request=Request{dut.io_memory_payload_address,dut.io_memory_payload_data,dut.io_memory_payload_size,bool(dut.io_memory_payload_write)};
        check(!held || request==held,"held memory request changed"); held=!dut.io_memory_ready?request:std::nullopt;
        if(held) stalls++;
        if(reply&&dut.io_response_ready) pending.reset();
        if(request&&dut.io_memory_ready) {
          check(!pending,"multiple outstanding requests"); auto r=*request; size_t bytes=1u<<r.size;
          check(r.address%bytes==0,"misaligned request");
          bool common=span(r.address,bytes,HATS_OUTPUT,HATS_OUTPUT+HATS_OUTPUT_BYTES)||span(r.address,bytes,HATS_HEAP,HATS_HEAP+HATS_HEAP_BYTES)||span(r.address,bytes,HATS_STACK_BASE,HATS_STACK_TOP);
          bool permitted=common||span(r.address,bytes,r.write?p.at("writable_start"):HATS_DATA_BASE,p.at("bss_end"))||
            (!r.write&&(span(r.address,bytes,HATS_ARGUMENT,HATS_ARGUMENT+64)||span(r.address,bytes,HATS_OLD,HATS_OLD+HATS_INPUT_MAX)||span(r.address,bytes,HATS_NEW,HATS_NEW+HATS_INPUT_MAX)));
          uint64_t value=0;
          if(permitted) {
            uint8_t *ptr=memory.data()+r.address-HATS_DATA_BASE;
            if(r.write) { for(size_t i=0;i<bytes;i++) ptr[i]=uint8_t(r.data>>(i*8)); }
            for(size_t i=0;i<bytes;i++) value |= uint64_t(ptr[i])<<(i*8);
          }
          digest.access(r.address,bytes,r.write,value,!permitted);
          pending=Reply{cycles+2+rng()%8,value,!permitted}; requests++;
        }
        if(dut.io_retired_valid) {
          if(dut.io_retired_payload_writes) {
            check(dut.io_retired_payload_rd!=0,"x0 publication");
            registers[dut.io_retired_payload_rd]=dut.io_retired_payload_value;
            if(dut.io_retired_payload_rd==2) {
              uint64_t sp=registers[2]; check(sp>=HATS_STACK_BASE&&sp<=HATS_STACK_TOP&&sp%16==0,"stack bound/alignment"); minimum_sp=std::min(minimum_sp,sp);
            }
          }
          uint64_t pc=dut.io_retired_payload_pc;
          digest.retire(pc,dut.io_retired_payload_instruction,dut.io_controlRetired_valid?dut.io_controlRetired_payload_actualNext:pc+4,registers);
        }
        if(dut.io_halt_valid) {
          check(!pending&&!held,"halt before drain");
          check(dut.io_halt_payload_cause==3&&dut.io_halt_payload_pc==p.at("exit_pc"),"unexpected hardware trap");
          digest.trap(dut.io_halt_payload_pc,3,dut.io_halt_payload_value); halted=true; break;
        }
        edge();
      }
      check(halted,"hardware cycle budget exhausted");
      std::string prefix=output+"-"+std::to_string(invocation);
      digest.save((prefix+".digest.json").c_str());
      std::ofstream result(prefix+".result.bin",std::ios::binary);
      result.write(reinterpret_cast<char*>(memory.data()+HATS_OUTPUT-HATS_DATA_BASE),HATS_OUTPUT_BYTES);
      std::ofstream stats(prefix+".execution.json");
      stats<<"{\"cycles\":"<<cycles<<",\"retired\":"<<digest.retirements<<",\"requests\":"<<requests
        <<",\"stalls\":"<<stalls<<",\"stack_bytes\":"<<HATS_STACK_TOP-minimum_sp<<",\"result\":"<<dut.io_halt_payload_value<<"}\n";
      check(bool(result)&&bool(stats),"output write failed");
      uint64_t result_value=dut.io_halt_payload_value;
      dut.io_response_valid=0;
      for(unsigned i=0;i<8;i++) { edge(); check(dut.io_halt_valid&&dut.io_halt_payload_value==result_value&&!dut.io_memory_valid,"unstable completion"); }
      dut.io_halt_ready=1; edge(); dut.io_halt_ready=0;
      check(!dut.io_busy&&!dut.io_halt_valid,"relaunch state not idle");
    }
    return 0;
  } catch(const std::exception &error) { std::cerr<<error.what()<<"\n"; return 1; }
}
