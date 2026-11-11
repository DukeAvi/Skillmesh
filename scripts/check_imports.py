"""Print first-party imports and fail on cycles (including function-local imports)."""

import ast
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def import_graph():
    files = [
        ROOT / "demo",
        *ROOT.glob("scripts/*.py"),
        *ROOT.glob("web/*.py"),
        *ROOT.glob("tests/*.py"),
        *ROOT.glob("web/*.js"),
    ]
    names = {
        (
            p.relative_to(ROOT).as_posix()
            if p.suffix == ".js"
            else p.relative_to(ROOT).with_suffix("").as_posix().replace("/", ".")
        ): p
        for p in files
    }
    graph = {name: set() for name in names}
    for name, path in names.items():
        if path.suffix == ".js":
            for target in re.findall(
                r"\b(?:import|export)\s+[^;]*?\bfrom\s+[\"\'](.+?)[\"\']",
                path.read_text(),
            ):
                resolved = (path.parent / target).resolve().relative_to(ROOT)
                graph[name].add(resolved.as_posix())
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            targets = []
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    base = ".".join(
                        name.split(".")[: -node.level] + ([base] if base else [])
                    )
                targets = [base, *(f"{base}.{alias.name}" for alias in node.names)]
            for target in targets:
                # Direct script launches resolve sibling imports from scripts/.
                if target not in names and f"scripts.{target}" in names:
                    target = f"scripts.{target}"
                if target in names:
                    graph[name].add(target)
    return graph


def check(graph):
    done, active = set(), []

    def visit(name):
        if name in active:
            raise ValueError("Import cycle: " + " -> ".join(active + [name]))
        if name in done:
            return
        active.append(name)
        for target in sorted(graph[name]):
            visit(target)
        active.pop()
        done.add(name)

    for name in sorted(graph):
        visit(name)


if __name__ == "__main__":
    graph = import_graph()
    for source, targets in sorted(graph.items()):
        print(f"{source}: {', '.join(sorted(targets)) or '(no first-party imports)'}")
    check(graph)
    print(f"Acyclic: {len(graph)} modules, {sum(map(len, graph.values()))} edges")
