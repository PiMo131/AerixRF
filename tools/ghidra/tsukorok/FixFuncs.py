# Post-analysis: find undisassembled Xtensa 'entry a1,N' prologues in the app region, create functions, re-analyze
from ghidra.program.model.symbol import SourceType
from ghidra.program.disassemble import Disassembler
listing = currentProgram.getListing()
mem = currentProgram.getMemory()
af = currentProgram.getAddressFactory().getDefaultAddressSpace()
dis = Disassembler.getDisassembler(currentProgram, monitor, None)
created = 0
for lo, hi in [(0x42000020, 0x420d08e8), (0x40374000, 0x40377fe0), (0x40377fe0, 0x40388364)]:
    a = lo
    while a < hi:
        addr = af.getAddress(a)
        if listing.getCodeUnitContaining(addr) is None or listing.getInstructionContaining(addr) is None and listing.getDefinedDataContaining(addr) is None:
            b0 = mem.getByte(addr) & 0xff
            b1 = mem.getByte(addr.add(1)) & 0xff
            if b0 == 0x36 and (b1 & 0x0f) == 0x01 and (a % 4) == 0:
                dis.disassemble(addr, None)
                if listing.getFunctionContaining(addr) is None:
                    f = createFunction(addr, None)
                    if f is not None: created += 1
        a += 4 if (a % 4 == 0) else (4 - a % 4)
print("created functions:", created)
analyzeChanges(currentProgram)
