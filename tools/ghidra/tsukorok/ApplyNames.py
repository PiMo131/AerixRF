# args: symbols.csv outgzf
import ghidra.program.model.listing
from ghidra.program.model.symbol import SourceType
from ghidra.app.util.exporter import GzfExporter
import java.io, csv
args = getScriptArgs()
fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory().getDefaultAddressSpace()
listing = currentProgram.getListing()
n = 0
for row in csv.DictReader(open(args[0]), quoting=csv.QUOTE_NONE):
    addr = af.getAddress(row['addr'])
    f = fm.getFunctionAt(addr)
    if f is None:
        f = createFunction(addr, row['name'])
    if f is None:
        print("no function at", row['addr']); continue
    f.setName(row['name'], SourceType.USER_DEFINED)
    if row['comment']:
        listing.setComment(addr, ghidra.program.model.listing.CodeUnit.PLATE_COMMENT, row["comment"])
    n += 1
print("named", n)

