package hats

import spinal.core._

/** Explicit design point for matched-workload and synthesis studies. The code
  * memory capacity differs between small structural probes and real-tool images;
  * callers must record that difference rather than equating their area totals.
  */
object ApeDesignPointGenerate extends App {
  require(args.length == 8, "output-directory rob physical issue-width prediction predictor-entries code-words checkpoints")
  require(Set("off", "bimodal").contains(args(4)))
  val c = ApeConfig(robEntries = args(1).toInt, physicalRegisters = args(2).toInt,
    issueWidth = args(3).toInt, prediction = args(4) == "bimodal", predictorEntries = args(5).toInt,
    programWords = args(6).toInt, branchCheckpoints = args(7).toInt)
  SpinalConfig(targetDirectory = args(0)).generateVerilog(new ApeCore(c))
  println(s"APE design point: $c")
}
