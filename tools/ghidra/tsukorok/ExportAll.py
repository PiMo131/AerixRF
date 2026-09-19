# Ghidra post-script: export function list, string xrefs, and decompiled C of the app region
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor
import java.io
fm = currentProgram.getFunctionManager()
listing = currentProgram.getListing()
rm = currentProgram.getReferenceManager()
out = java.io.PrintWriter(java.io.FileWriter("OUT/funcs.txt"))
for f in fm.getFunctions(True):
    out.println("%s %s %s" % (f.getEntryPoint(), f.getBody().getMaxAddress(), f.getName()))
out.close()
# string xrefs: for each defined string in DROM, list referencing functions
out = java.io.PrintWriter(java.io.FileWriter("OUT/string_xrefs.txt"))
for data in listing.getDefinedData(True):
    if data.getDataType().getName().lower().startswith('string') or data.getDataType().getName()=='TerminatedCString':
        s = data.getValue()
        refs = rm.getReferencesTo(data.getAddress())
        fr = set()
        for r in refs:
            f = fm.getFunctionContaining(r.getFromAddress())
            fr.add("%s@%s" % (f.getName() if f else "?", r.getFromAddress()))
        if fr:
            out.println("%s | %r | %s" % (data.getAddress(), s, " ".join(sorted(fr))))
out.close()
di = DecompInterface()
di.openProgram(currentProgram)
mon = ConsoleTaskMonitor()
out = java.io.PrintWriter(java.io.FileWriter("OUT/decomp_all.c"))
n=0
for f in fm.getFunctions(True):
    a = f.getEntryPoint().getOffset()
    if not (0x42000020 <= a < 0x420d1000 or 0x40374000 <= a < 0x40389000):
        continue
    try:
        res = di.decompileFunction(f, 60, mon)
        if res.decompileCompleted():
            out.println("//==== %s @ %s - %s" % (f.getName(), f.getEntryPoint(), f.getBody().getMaxAddress()))
            out.println(res.getDecompiledFunction().getC())
        else:
            out.println("//==== %s @ %s FAILED %s" % (f.getName(), f.getEntryPoint(), res.getErrorMessage()))
    except Exception as e:
        out.println("//==== %s @ %s EXC %s" % (f.getName(), f.getEntryPoint(), e))
    n+=1
    if n%200==0: out.flush()
out.close()
print("decompiled", n)
