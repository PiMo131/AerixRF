import java.io
args = getScriptArgs()
df = currentProgram.getDomainFile()
df.packFile(java.io.File(args[0]), monitor)
print("packed")
