package hats

import java.nio.file.{Files, Path, Paths}

/** Remove only the disposable C++ compiler cache after a completed simulator
  * run. Spinal-generated Verilog, traces, and validation records are retained.
  */
object ApeSimArtifactCleanup {
  def discardVerilatorBuildTree(workspaceRoot: Path, topName: String): Unit = {
    require(topName.matches("[A-Za-z][A-Za-z0-9_]*"))
    val buildRoot = Paths.get("build").toAbsolutePath.normalize()
    val target = workspaceRoot.toAbsolutePath.normalize().resolve(topName).resolve("verilator")
    if (target.startsWith(buildRoot) && Files.isDirectory(target)) {
      def deleteTree(path: Path): Unit = {
        if (Files.isDirectory(path)) {
          val entries = Files.newDirectoryStream(path)
          try {
            val iterator = entries.iterator()
            while (iterator.hasNext) deleteTree(iterator.next())
          } finally entries.close()
        }
        Files.deleteIfExists(path)
      }
      deleteTree(target)
    }
  }
}
