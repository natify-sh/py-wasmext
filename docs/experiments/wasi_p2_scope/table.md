| Package | Interface | Functions | Resources (drops) | Required | Seen in programs | Implemented here | Stubbed |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| cli | environment | 3 | 0 | 3 | 2 | 2 | 0 |
| cli | exit | 2 | 0 | 2 | 2 | 2 | 0 |
| cli | run | 0 | 0 | 0 | 0 | 0 | 0 |
| cli | stderr | 1 | 0 | 1 | 1 | 1 | 0 |
| cli | stdin | 1 | 0 | 1 | 1 | 1 | 0 |
| cli | stdout | 1 | 0 | 1 | 1 | 1 | 0 |
| cli | terminal-input | 0 | 1 | 1 | 1 | 0 | 0 |
| cli | terminal-output | 0 | 1 | 1 | 1 | 0 | 0 |
| cli | terminal-stderr | 1 | 0 | 1 | 1 | 1 | 0 |
| cli | terminal-stdin | 1 | 0 | 1 | 1 | 1 | 0 |
| cli | terminal-stdout | 1 | 0 | 1 | 1 | 1 | 0 |
| clocks | monotonic-clock | 4 | 0 | 4 | 4 | 4 | 0 |
| clocks | wall-clock | 2 | 0 | 2 | 2 | 2 | 0 |
| filesystem | preopens | 1 | 0 | 1 | 1 | 1 | 0 |
| filesystem | types | 29 | 2 | 31 | 28 | 23 | 5 |
| http | incoming-handler | 0 | 0 | 0 | 0 | 0 | 0 |
| http | outgoing-handler | 1 | 0 | 1 | 0 | 0 | 0 |
| http | types | 51 | 11 | 62 | 0 | 0 | 0 |
| io | error | 1 | 1 | 2 | 1 | 0 | 0 |
| io | poll | 3 | 1 | 4 | 3 | 3 | 0 |
| io | streams | 15 | 2 | 17 | 8 | 8 | 0 |
| random | insecure | 2 | 0 | 2 | 0 | 0 | 0 |
| random | insecure-seed | 1 | 0 | 1 | 0 | 0 | 0 |
| random | random | 2 | 0 | 2 | 1 | 1 | 0 |
| sockets | instance-network | 1 | 0 | 1 | 1 | 1 | 0 |
| sockets | ip-name-lookup | 3 | 1 | 4 | 4 | 4 | 0 |
| sockets | network | 0 | 1 | 1 | 0 | 0 | 0 |
| sockets | tcp | 28 | 1 | 29 | 28 | 11 | 0 |
| sockets | tcp-create-socket | 1 | 0 | 1 | 1 | 1 | 0 |
| sockets | udp | 18 | 3 | 21 | 20 | 0 | 0 |
| sockets | udp-create-socket | 1 | 0 | 1 | 1 | 0 | 0 |

| Package | Interfaces | Functions | Drops | Required | Seen | Implemented | Stubbed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| cli | 11 | 11 | 2 | 13 | 12 | 10 | 0 |
| clocks | 2 | 6 | 0 | 6 | 6 | 6 | 0 |
| filesystem | 2 | 30 | 2 | 32 | 29 | 24 | 5 |
| http | 3 | 52 | 11 | 63 | 0 | 0 | 0 |
| io | 3 | 19 | 4 | 23 | 12 | 11 | 0 |
| random | 3 | 5 | 0 | 5 | 1 | 1 | 0 |
| sockets | 7 | 52 | 6 | 58 | 55 | 17 | 0 |
| **all** | 31 | 175 | 25 | 200 | 115 | 69 | 5 |

Required and not implemented (functions only; drops are generic):
- wasi:cli/environment: 1: initial-cwd
- wasi:filesystem/types: 8: [method]descriptor.advise, [method]descriptor.get-type, [method]descriptor.is-same-object, [method]descriptor.set-times, [method]descriptor.set-times-at, [method]descriptor.sync, [method]descriptor.sync-data, filesystem-error-code
- wasi:io/error: 1: [method]error.to-debug-string
- wasi:io/poll: 1: [method]pollable.ready
- wasi:io/streams: 9: [method]input-stream.blocking-read, [method]input-stream.blocking-skip, [method]input-stream.skip, [method]output-stream.blocking-splice, [method]output-stream.blocking-write-and-flush, [method]output-stream.blocking-write-zeroes-and-flush, [method]output-stream.flush, [method]output-stream.splice, [method]output-stream.write-zeroes
- wasi:random/insecure: 2: get-insecure-random-bytes, get-insecure-random-u64
- wasi:random/insecure-seed: 1: insecure-seed
- wasi:random/random: 1: get-random-u64
- wasi:sockets/tcp: 18
- wasi:sockets/udp: 18
- wasi:sockets/udp-create-socket: 1: create-udp-socket

Worlds (interfaces imported):
- wasi:io/imports: 3 interfaces, 23 required imports
- wasi:clocks/imports: 3 interfaces, 10 required imports
- wasi:filesystem/imports: 6 interfaces, 57 required imports
- wasi:sockets/imports: 11 interfaces, 85 required imports
- wasi:random/imports: 3 interfaces, 5 required imports
- wasi:cli/imports: 27 interfaces, 137 required imports
- wasi:cli/command: 27 interfaces, 137 required imports
- wasi:http/imports: 11 interfaces, 97 required imports
- wasi:http/proxy: 11 interfaces, 97 required imports

Programs seen:
- git.component.wasm: 53 imports in 18 interfaces
- git_p2_net.component.wasm: 108 imports in 24 interfaces
- hello.component.wasm: 21 imports in 13 interfaces
- cpy_p2s.wasm: 115 imports in 24 interfaces

CLI world: 137 imports; asked for by the programs: 115; never asked for: 22
asked for and not implemented (drops left out): 40
  of them in wasi:sockets: 35
