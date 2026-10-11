package hats

import spinal.core._

object GenerateApePpeSharedMemory extends App {
  SpinalConfig(targetDirectory = args.headOption.getOrElse("build/s04/shared-system"))
    .generateVerilog(new ApePpeSharedMemoryTile())
}
