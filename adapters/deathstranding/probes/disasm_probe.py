"""Disassembles Death Stranding's exe on disk around an address (relative to the image, as the
game's error.txt and watch_probe print them), and finds byte patterns. No game needed.

    uv run --with capstone --with pefile python -m adapters.deathstranding.probes.disasm_probe 0x1C6A9A7
    ... disasm_probe --find "48 8B ?? ?? 89"           # every place a pattern matches (RVA)
"""
import argparse
import os
import re

GAME_EXE = os.path.join(r"C:\Program Files (x86)\Steam\steamapps\common\DEATH STRANDING DIRECTORS CUT", "ds.exe")


class Image:
    def __init__(self, path=GAME_EXE):
        import pefile
        self.pe = pefile.PE(path, fast_load=True)
        self.data = open(path, "rb").read()
        self.base = self.pe.OPTIONAL_HEADER.ImageBase

    def bytes_at(self, rva, n):
        off = self.pe.get_offset_from_rva(rva)
        return self.data[off: off + n]

    def text(self):
        s = [s for s in self.pe.sections if s.Name.startswith(b".text")][0]
        return s.VirtualAddress, self.data[s.PointerToRawData: s.PointerToRawData + s.SizeOfRawData]

    def calls_to(self, target, limit=50):
        """Every direct call (E8 rel32) to an RVA."""
        va, text = self.text()
        out = []
        i = text.find(b"\xe8")
        while i != -1 and len(out) < limit:
            if i + 5 <= len(text):
                rel = int.from_bytes(text[i + 1:i + 5], "little", signed=True)
                if va + i + 5 + rel == target:
                    out.append(va + i)
            i = text.find(b"\xe8", i + 1)
        return out

    def find(self, pattern, limit=20):
        rx = re.compile(b"".join(b"." if t in ("?", "??") else re.escape(bytes([int(t, 16)])) for t in pattern.split()), re.S)
        va, text = self.text()
        return [va + m.start() for m in rx.finditer(text)][:limit]


def disasm(img, rva, before=64, after=96, mark=None):
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    md.detail = False
    mark = rva if mark is None else mark
    for back in range(before, 0, -1):     # find a start that decodes cleanly onto the marked address
        code = img.bytes_at(rva - back, back + after)
        ins = list(md.disasm(code, rva - back))
        starts = {i.address for i in ins}
        ends = {i.address + i.size for i in ins}
        if mark in starts or mark in ends:
            return ["%s %08x  %-24s %s %s" % ("=>" if i.address + i.size == mark else "  ", i.address,
                                              i.bytes.hex(" "), i.mnemonic, i.op_str) for i in ins]
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rva", nargs="?")
    ap.add_argument("--before", type=int, default=64)
    ap.add_argument("--after", type=int, default=96)
    ap.add_argument("--find", default=None)
    ap.add_argument("--calls", default=None, help="every direct call to this RVA")
    a = ap.parse_args()
    img = Image()
    if a.calls:
        for r in img.calls_to(int(a.calls, 0)):
            print(hex(r))
        return
    if a.find:
        for r in img.find(a.find):
            print(hex(r))
        return
    print("\n".join(disasm(img, int(a.rva, 0), a.before, a.after)))


if __name__ == "__main__":
    main()
