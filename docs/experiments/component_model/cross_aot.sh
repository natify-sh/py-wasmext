for t in x86_64-unknown-linux-gnu aarch64-unknown-linux-gnu aarch64-apple-darwin aarch64-pc-windows-msvc \
         riscv64gc-unknown-linux-gnu s390x-unknown-linux-gnu i686-unknown-linux-gnu \
         armv7-unknown-linux-gnueabihf pulley32 pulley64; do
  aot composed.wasm x_$t.cwasm $t
done
