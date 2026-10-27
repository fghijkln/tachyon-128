# TACHYON-128 top-level flow.  Requires: python3, verilator (+C++ compiler), yowasp-yosys.
PY ?= python3
N  ?= 1000

.PHONY: all build test tools mulcheck unit programs random mutants synth clean
all: build test synth

build:
	tb/build.sh

test: tools mulcheck unit programs random

tools:
	$(PY) tests/test_tools.py

mulcheck:
	bash tests/test_mul32x4.sh

unit: build
	$(PY) tests/run_tests.py unit

programs: build
	$(PY) tests/run_tests.py programs

random: build
	$(PY) tests/run_tests.py random $(N) 1

mutants:
	$(PY) tests/mutants.py

synth:
	yowasp-yosys -q -l build/synth.log synth/synth.ys
	@cat build/synth_stat.txt

clean:
	rm -rf build programs/*.bin
