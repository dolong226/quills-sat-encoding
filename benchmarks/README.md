# .qasm Structure

The benchmarks follow the OPENQASM 2.0 standard.

## Components

### Header:
- `OPENQASM 2.0;`: Defines the syntax version.
- `include "qelib1.inc";`: Includes the standard quantum library

### Register Declaration:
- `qreg q[n]`: Defines a quantum register named `q` with `n` logic qubits.

### Gate list:
- Unary gates
- Birany gates: `cx q[control], q[target];` (CNOT)

### Logical Dependencies:
The order of iinstructions defines the Dependency Graph.

### Transpile Circuit
python .\transpile_investigation\transpile_for_quills.py .\benchmarks\collection guadalupe -o .\benchmarks\transpiled --batch