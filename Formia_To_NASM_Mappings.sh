| FORMIA Word | NASM x64 Instruction     | Hex     | Binary       |
| ----------- | ------------------------ | ------- | ------------ |
| `and`       | `AND r/m64, r64`         | `0x1D2` | `111010010`  |
| `or`        | `OR r/m64, r64`          | `0x1D3` | `111010011`  |
| `xor`       | `XOR r/m64, r64`         | `0x1D4` | `111010100`  |
| `not`       | `NOT r/m64`              | `0x1D5` | `111010101`  |
| `if`        | `CMP + conditional jump` | `0x205` | `1000000101` |
| `throw`     | `JMP throw_handler`      | `0x1E1` | `111100001`  |
| `nullptr`   | `XOR reg, reg`           | `0x1E0` | `111100000`  |
| `new`       | `CALL malloc`            | `0x201` | `1000000001` |
| `delete`    | `CALL free`              | `0x202` | `1000000010` |
| `for`       | `LOOP label`             | `0x20B` | `1000001011` |
