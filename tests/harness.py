"""Differential harness: run a binary on the golden simulator and on the Verilator RTL model,
then compare commit traces, console output, final RAM image and halt status."""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from asm import Assembler, preprocess, write_hex128  # noqa: E402
from isa import RAM_BYTES  # noqa: E402
from sim import Machine  # noqa: E402

VTB = os.path.join(ROOT, "build", "vtb", "Vtb")


def assemble_src(src):
    return Assembler().assemble(src)[0]


def assemble_path(path):
    return Assembler().assemble(preprocess(path))[0]


class Result:
    def __init__(self, name):
        self.name, self.ok, self.msg = name, False, ""
        self.cycles = self.retired = 0
        self.console = b""

    @property
    def cpi(self):
        return self.cycles / self.retired if self.retired else 0.0


def run_diff(name, binary, workdir, max_steps=3_000_000, expect=None):
    """expect: optional callable(machine) -> error string or None (golden sanity checks)."""
    os.makedirs(workdir, exist_ok=True)
    res = Result(name)
    base = os.path.join(workdir, name)
    hexf = base + ".hex"
    write_hex128(binary, hexf)
    m = Machine(binary).run(max_steps)
    if m.halted[0] == "timeout":
        res.msg = "golden model timed out"
        return res
    if expect:
        err = expect(m)
        if err:
            res.msg = "golden expectation failed: " + err
            return res
    files = {k: f"{base}.rtl.{k}" for k in ("trace", "console", "mem", "stat")}
    cmd = [VTB, f"+prog={hexf}", f"+max={max_steps * 200 + 10000}"] + [f"+{k}={v}" for k, v in files.items()]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        res.msg = f"RTL run failed rc={p.returncode}: {p.stderr.strip()[-300:]}"
        return res
    stat = dict(l.split() for l in open(files["stat"]) if l.strip())
    res.cycles, res.retired = int(stat["cycles"]), int(stat["retired"])
    gtrace = m.trace
    rtrace = open(files["trace"]).read().splitlines()
    for i, (g, r) in enumerate(zip(gtrace, rtrace)):
        if g != r:
            res.msg = f"trace mismatch at commit {i}:\n   golden: {g}\n   rtl:    {r}"
            return res
    if len(gtrace) != len(rtrace):
        res.msg = f"trace length differs: golden {len(gtrace)} vs rtl {len(rtrace)}"
        return res
    rcon = open(files["console"], "rb").read()
    if rcon != bytes(m.console):
        res.msg = f"console differs:\n   golden: {bytes(m.console)[:120]!r}\n   rtl:    {rcon[:120]!r}"
        return res
    words = open(files["mem"]).read().split()
    rmem = b"".join(int(w, 16).to_bytes(16, "little") for w in words)
    if rmem != bytes(m.ram):
        diff = next(i for i in range(RAM_BYTES) if rmem[i] != m.ram[i])
        res.msg = f"RAM differs first at 0x{diff:x}"
        return res
    if m.retired != res.retired:
        res.msg = f"retired count differs golden {m.retired} rtl {res.retired}"
        return res
    if m.halted[0] == "exit" and int(stat["exit"]) != m.exit_code:
        res.msg = f"exit code differs golden {m.exit_code} rtl {stat['exit']}"
        return res
    res.console = bytes(m.console)
    res.ok = True
    for f in list(files.values()) + [hexf]:
        os.remove(f)
    return res
