import greeter

c = greeter.instance()
c.call("demo:text/api@0.1.0", "greet", "Murphy")  # 'hello, Murphy #735'
c.call("demo:text/api@0.1.0", "greet", "wasm")  # 'hello, wasm #20'
