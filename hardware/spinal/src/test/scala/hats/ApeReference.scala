package hats

import scala.collection.mutable

/** Sequential ISA oracle, intentionally independent of RTL decode/scheduling code.
  * This local model is not a substitute for future Spike/Sail/riscv-arch-test coverage.
  */
object ApeReference {
  val mask = (BigInt(1) << 64) - 1
  def u(v: BigInt): BigInt = v & mask
  def sx(v: BigInt, bits: Int): BigInt = {
    val x = v & ((BigInt(1) << bits) - 1)
    if (x.testBit(bits - 1)) x - (BigInt(1) << bits) else x
  }
  case class Retire(pc: BigInt, instruction: Long, rd: Int, writes: Boolean, value: BigInt)
  case class Trap(pc: BigInt, cause: Int) extends RuntimeException

  def initialMemory(): mutable.Map[BigInt, Int] = {
    val mem = mutable.Map[BigInt, Int]()
    Seq[Long](7, 13, -1, 128, 255, 1024, 0, 42).zipWithIndex.foreach { case (v, i) =>
      for (j <- 0 until 8) mem(BigInt(0x10000 + i * 8 + j)) = ((u(BigInt(v)) >> (8 * j)) & 255).toInt
    }
    mem
  }

  class Machine(program: Vector[Long], val memory: mutable.Map[BigInt, Int], entry: BigInt = 0,
                argument: BigInt = 0, base: BigInt = 0x10000, limit: BigInt = 0x20000,
                writable: Boolean = true, busError: Boolean = false) {
    val registers = Array.fill[BigInt](32)(0)
    registers(10) = u(argument)
    var pc = entry
    def step(): Retire = {
      def trap(n: Int): Nothing = throw Trap(pc, n)
      if ((pc & 3) != 0) trap(0)
      if (pc < 0 || pc >= 4096) trap(1)
      val ins = if (pc / 4 < program.size) program((pc / 4).toInt) else 0L
      val opc = (ins & 127).toInt
      val rd = ((ins >>> 7) & 31).toInt
      val f = ((ins >>> 12) & 7).toInt
      val rs1 = ((ins >>> 15) & 31).toInt
      val rs2 = ((ins >>> 20) & 31).toInt
      val hi = ((ins >>> 25) & 127).toInt
      val a = registers(rs1)
      val r = registers(rs2)
      val imm = sx(BigInt(ins >>> 20), 12)
      var result = BigInt(0)
      var write = false
      var next = u(pc + 4)
      opc match {
        case 0x37 => result = sx(BigInt(ins & 0xfffff000L), 32); write = true
        case 0x17 => result = pc + sx(BigInt(ins & 0xfffff000L), 32); write = true
        case 0x13 | 0x1b | 0x33 | 0x3b =>
          val immediate = opc == 0x13 || opc == 0x1b
          val word = opc == 0x1b || opc == 0x3b
          val b = if (immediate) u(imm) else r
          val shamt = (b & (if (word) 31 else 63)).toInt
          if (word && !Set(0, 1, 5).contains(f)) trap(2)
          result = f match {
            case 0 if immediate || hi == 0 => a + b
            case 0 if hi == 32 => a - b
            case 1 =>
              if (immediate) {
                if ((ins >>> 26) != 0 || (word && (hi & 1) != 0)) trap(2)
              } else if (hi != 0) trap(2)
              a << shamt
            case 5 =>
              val top = if (immediate && !word) (ins >>> 26).toInt else hi
              val arithmetic = if (immediate && !word) top == 16 else top == 32
              if (top != 0 && !arithmetic) trap(2)
              if (arithmetic) sx(a, if (word) 32 else 64) >> shamt
              else (if (word) a & 0xffffffffL else a) >> shamt
            case 2 | 3 | 4 | 6 | 7 if immediate || hi == 0 =>
              f match {
                case 2 => if (sx(a, 64) < sx(b, 64)) BigInt(1) else BigInt(0)
                case 3 => if (a < b) BigInt(1) else BigInt(0)
                case 4 => a ^ b
                case 6 => a | b
                case 7 => a & b
              }
            case _ => trap(2)
          }
          if (word) result = sx(result, 32)
          write = true
        case 0x63 =>
          val offset = sx(BigInt(((ins >>> 31) << 12) | (((ins >>> 7) & 1) << 11) |
            (((ins >>> 25) & 63) << 5) | (((ins >>> 8) & 15) << 1)), 13)
          val taken = f match {
            case 0 => a == r
            case 1 => a != r
            case 4 => sx(a, 64) < sx(r, 64)
            case 5 => sx(a, 64) >= sx(r, 64)
            case 6 => a < r
            case 7 => a >= r
            case _ => trap(2)
          }
          if (taken) next = u(pc + offset)
        case 0x6f =>
          val offset = sx(BigInt(((ins >>> 31) << 20) | (((ins >>> 12) & 255) << 12) |
            (((ins >>> 20) & 1) << 11) | (((ins >>> 21) & 1023) << 1)), 21)
          result = pc + 4; write = true; next = u(pc + offset)
        case 0x67 =>
          if (f != 0) trap(2)
          result = pc + 4; write = true; next = u(a + imm) & (mask - 1)
        case 0x03 | 0x23 =>
          val store = opc == 0x23
          if ((store && f > 3) || (!store && f == 7)) trap(2)
          val offset = if (store) sx(BigInt(((ins >>> 25) << 5) | ((ins >>> 7) & 31)), 12) else imm
          val addr = u(a + offset)
          val size = 1 << (f & 3)
          if (addr % size != 0) trap(if (store) 6 else 4)
          if (addr < base || addr + size > limit || (store && !writable) || busError) trap(if (store) 7 else 5)
          if (store) {
            for (i <- 0 until size) memory(addr + i) = ((r >> (8 * i)) & 255).toInt
          } else {
            result = (0 until size).map(i => BigInt(memory.getOrElse(addr + i, 0)) << (8 * i)).foldLeft(BigInt(0))(_ | _)
            if (f < 4) result = sx(result, size * 8)
            write = true
          }
        case 0x0f if f == 0 => // head-ordered memory makes FENCE a no-op in this single-hart model
        case 0x73 if ins == 0x00100073L => trap(3)
        case _ => trap(2)
      }
      if ((next & 3) != 0) trap(0)
      result = u(result)
      if (write && rd != 0) registers(rd) = result
      val event = Retire(pc, ins, rd, write && rd != 0, result)
      pc = next
      event
    }
  }
}
