package hats

/** Legacy command delegates to the APE suite with prediction disabled. */
object HseCoreSim {
  def main(args: Array[String]): Unit =
    ApeCoreSim.main(Array(args.headOption.getOrElse("8"), "off"))
}
