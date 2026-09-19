from ghidra.program.disassemble import Disassembler
listing = currentProgram.getListing()
mem = currentProgram.getMemory()
fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory().getDefaultAddressSpace()
dis = Disassembler.getDisassembler(currentProgram, monitor, None)
created = 0
for lo, hi in [(0x42003000, 0x4201b000), (0x40374000, 0x40377fe0), (0x40377fe0, 0x40388364)]:
    a = lo
    while a < hi:
        addr = af.getAddress(a)
        if fm.getFunctionContaining(addr) is None:
            b0 = mem.getByte(addr) & 0xff
            b1 = mem.getByte(addr.add(1)) & 0xff
            if b0 == 0x36 and (b1 & 0x0f) == 0x01:
                if listing.getInstructionAt(addr) is None:
                    cu = listing.getCodeUnitContaining(addr)
                    if cu is not None and listing.getInstructionAt(addr) is None and cu.getAddress() != addr:
                        listing.clearCodeUnits(cu.getAddress(), cu.getAddress(), False)
                    dis.disassemble(addr, None)
                f = createFunction(addr, None)
                if f is not None: created += 1
        a += 4
print("created functions pass2:", created)
analyzeChanges(currentProgram)
