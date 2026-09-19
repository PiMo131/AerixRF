# Ghidra pre-script (Jython): rebuild memory map from ESP32-S3 image header
from ghidra.program.model.mem import MemoryConflictException
import struct
mem = currentProgram.getMemory()
fb = mem.getAllFileBytes().get(0)
# remove existing blocks
for b in list(mem.getBlocks()):
    mem.removeBlock(b, monitor)
raw = bytearray(fb.getSize())
for i in range(fb.getSize()):
    raw[i] = fb.getOriginalByte(i) & 0xff
nseg = raw[1]
off = 24
names = ['DROM','DRAM','IRAM0','IROM','IRAM1','RTC']
af = currentProgram.getAddressFactory().getDefaultAddressSpace()
for i in range(nseg):
    va, ln = struct.unpack('<II', bytes(raw[off:off+8]))
    blk = mem.createInitializedBlock(names[i], af.getAddress(va), fb, off+8, ln, False)
    blk.setRead(True); blk.setWrite(names[i] in ('DRAM','RTC')); blk.setExecute(names[i] in ('IRAM0','IROM','IRAM1'))
    print("block %s at %08x len %x" % (names[i], va, ln))
    off += 8 + ln
# uninitialized RAM blocks for the rest of DRAM/BSS so refs resolve
try:
    mem.createUninitializedBlock('DRAM_BSS', af.getAddress(0x3fc98370+0x5a8c), 0x3fcf0000-(0x3fc98370+0x5a8c), False)
except Exception as e:
    print(e)
currentProgram.getSymbolTable().createLabel(af.getAddress(0x40379c1c), "entry", ghidra.program.model.symbol.SourceType.USER_DEFINED)
ghidra.program.disassemble.Disassembler.getDisassembler(currentProgram, monitor, None).disassemble(af.getAddress(0x40379c1c), None)
