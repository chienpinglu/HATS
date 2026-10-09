package hats
import spinal.core._

/** Same large-image core as ApeToolSim, exported for streaming full-matrix DV. */
object ApeToolGenerate extends App {
  require(args.length == 3, "output-directory rob-entries prediction")
  require(Set("off", "bimodal").contains(args(2)))
  SpinalConfig(targetDirectory = args(0)).generateVerilog(new ApeCore(ApeConfig(
    robEntries = args(1).toInt, programWords = 65536, prediction = args(2) == "bimodal")))
}
