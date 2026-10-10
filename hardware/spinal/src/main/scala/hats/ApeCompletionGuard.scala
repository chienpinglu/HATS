package hats

import spinal.core._
import spinal.lib._

/** Shared completion/lease policy, independent of instruction semantics.
  * The ROB supplies the current owner's state. Every execution stage must be
  * represented in pending; wrap safety does not assume a bounded stall time.
  */
class ApeCompletionGuard(c: ApeConfig) extends Component {
  val io = new Bundle {
    val candidate = in(ApeExecutionIdentity(c))
    val ownerGeneration = in UInt(c.generationBits bits)
    val ownerDestination = in UInt(c.physicalTagBits bits)
    val ownerLive, ownerIssued, ownerComplete = in Bool()
    val qualified = out Bool()
    val allocationSlot = in UInt(c.tagBits bits)
    val allocationGeneration = in UInt(c.generationBits bits)
    val pending = in Vec(Flow(ApeExecutionIdentity(c)), c.issueWidth * c.executionStages)
    val allocationSafe = out Bool()
  }
  io.qualified := io.ownerLive && io.ownerIssued && !io.ownerComplete &&
    io.candidate.generation === io.ownerGeneration && io.candidate.destination === io.ownerDestination
  io.allocationSafe := !io.pending.map(p => p.valid && p.slot === io.allocationSlot &&
    p.generation === io.allocationGeneration).reduce(_ || _)
}
