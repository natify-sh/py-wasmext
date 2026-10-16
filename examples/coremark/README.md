# wasmext-example-coremark

[CoreMark](https://github.com/eembc/coremark) as a WebAssembly module (`src/coremark/_core.wasm`, from
[wasm2mpy](https://github.com/vshymanskyy/wasm2mpy), MIT) turned into a native CPython extension by
[wasmext](../..): a package with no WebAssembly engine at run time.

```sh
pip install .            # wasmext (and with it wabt-package) is a build requirement; a C compiler is needed
python -c "import coremark; print(coremark.run())"
```

`setup.py` is the whole integration:

```python
from setuptools import setup
from wasmext import wasmize

setup(ext_modules=wasmize("src/coremark/*.wasm"))
```

`cibuildwheel` builds wheels of it as it does for any extension.
