package hats

import spinal.core._

/** Compatibility with the initial HSE bring-up API; implementation lives in APE.
  * Historical configurations use fall-through prediction.
  */
case class HseConfig(robEntries: Int = 8, programWords: Int = 1024) {
  def toApe: ApeConfig = ApeConfig(robEntries, programWords, prediction = false)
}
class HseCore(c: HseConfig = HseConfig()) extends ApeCore(c.toApe)

object GenerateHse extends App {
  for (n <- Seq(4, 8, 16)) {
    SpinalConfig(targetDirectory = s"build/hse/rtl/r$n")
      .generateVerilog(new HseCore(HseConfig(robEntries = n)))
  }
}
