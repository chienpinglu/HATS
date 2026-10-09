// Original canonical architectural-state stream encoder. OpenSSL supplies SHA-256.
// This is evidence compression, not ISA emulation or a substitute output oracle.
#ifndef HATS_EVENT_DIGEST_H
#define HATS_EVENT_DIGEST_H
#include <openssl/evp.h>
#include <array>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <stdexcept>
class EventDigest {
  EVP_MD_CTX *context = EVP_MD_CTX_new();
 public:
  uint64_t events = 0, retirements = 0, memory = 0;
  EventDigest() { if (!context || EVP_DigestInit_ex(context, EVP_sha256(), nullptr) != 1) throw std::runtime_error("SHA256 init"); }
  ~EventDigest() { EVP_MD_CTX_free(context); }
  void words(const uint64_t *values, size_t count) {
    std::array<uint8_t, 288> raw{};
    if(count*8 > raw.size()) throw std::runtime_error("digest record too large");
    for(size_t i=0;i<count;i++) for(size_t j=0;j<8;j++) raw[i*8+j]=uint8_t(values[i]>>(8*j));
    if(EVP_DigestUpdate(context,raw.data(),count*8)!=1) throw std::runtime_error("SHA256 update");
    events++;
  }
  void retire(uint64_t pc, uint64_t instruction, uint64_t next, const std::array<uint64_t,32> &registers) {
    std::array<uint64_t,36> record{}; record[0]=1; record[1]=pc; record[2]=instruction; record[3]=next;
    for(size_t i=0;i<32;i++) record[4+i]=registers[i]; words(record.data(),record.size()); retirements++;
  }
  void access(uint64_t address,uint64_t size,bool write,uint64_t data,bool error=false) {
    uint64_t record[]={2,address,size,uint64_t(write),data,uint64_t(error)}; words(record,6); memory++;
  }
  void trap(uint64_t pc,uint64_t cause,uint64_t value) { uint64_t record[]={3,pc,cause,value}; words(record,4); }
  void save(const char *path) {
    std::array<uint8_t,32> hash{}; unsigned bytes=0;
    if(EVP_DigestFinal_ex(context,hash.data(),&bytes)!=1 || bytes!=32) throw std::runtime_error("SHA256 final");
    std::ostringstream hex; for(auto byte:hash) hex<<std::hex<<std::setfill('0')<<std::setw(2)<<unsigned(byte);
    std::ofstream out(path);
    out<<"{\"schema\":1,\"encoding\":\"hats-architectural-state-le64-v1\",\"events\":"<<events
       <<",\"retirements\":"<<retirements<<",\"memory_events\":"<<memory<<",\"sha256\":\""<<hex.str()<<"\"}\n";
    if(!out) throw std::runtime_error("digest output failed");
  }
};
#endif
