"""Execute upstream startup with one independently maintained in-memory adapter."""
from __future__ import annotations
import ast
import sys
from pathlib import Path
from reference_guard.backend_adapter import install


def main():
    server = Path(sys.argv[1]).resolve()
    sys.argv = [str(server), *sys.argv[2:]]
    sys.path.insert(0, str(server.parent))
    tree = ast.parse(server.read_text(encoding='utf-8'), filename=str(server))
    # Install after upstream definitions, immediately before its own startup block.
    startup = next(i for i, node in enumerate(tree.body) if isinstance(node, ast.If)
                   and ast.unparse(node.test) == "__name__ == '__main__'")
    hook = ast.parse('_reference_guard_install(globals())').body[0]
    tree.body.insert(startup, hook)
    ast.fix_missing_locations(tree)
    namespace = {'__name__': '__main__', '__file__': str(server),
                 '_reference_guard_install': install}
    exec(compile(tree, str(server), 'exec'), namespace)


if __name__ == '__main__':
    main()
