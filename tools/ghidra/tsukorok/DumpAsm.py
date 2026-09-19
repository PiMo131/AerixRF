# args: outfile addr1 addr2 ...  -> dump disassembly listing of the functions containing each address
import java.io
args = getScriptArgs()
out = java.io.PrintWriter(java.io.FileWriter(args[0]))
fm = currentProgram.getFunctionManager()
listing = currentProgram.getListing()
af = currentProgram.getAddressFactory().getDefaultAddressSpace()
for a in args[1:]:
    addr = af.getAddress(a)
    f = fm.getFunctionContaining(addr)
    if f is None:
        out.println("// no function at %s" % a); continue
    out.println("//==== %s %s-%s" % (f.getName(), f.getEntryPoint(), f.getBody().getMaxAddress()))
    it = listing.getInstructions(f.getBody(), True)
    for ins in it:
        refs = []
        for r in ins.getReferencesFrom():
            t = r.getToAddress()
            d = listing.getDataAt(t)
            if d is not None and d.isDefined():
                v = d.getValue()
                refs.append("%s=%s" % (t, v))
        out.println("%s  %-40s %s" % (ins.getAddress(), ins.toString(), " ".join(refs)))
out.close()
