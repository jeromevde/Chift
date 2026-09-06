"""Keep only the chosen operations and the schemas they transitively reference."""
import sys

import yaml


def refs(node, out):
    """Collect $ref target names in document order (deterministic)."""
    if isinstance(node, dict):
        target = node.get("$ref")
        if isinstance(target, str):
            name = target.rsplit("/", 1)[-1]
            if name not in out:
                out.append(name)
        for value in node.values():
            refs(value, out)
    elif isinstance(node, list):
        for value in node:
            refs(value, out)
    return out


def prune(spec, keep):
    paths = {p: spec["paths"][p] for p in keep}
    schemas, out = spec["components"]["schemas"], {}
    queue = refs(paths, [])
    while queue:
        name = queue.pop(0)
        if name in out or name not in schemas:
            continue
        out[name] = schemas[name]
        queue.extend(refs(schemas[name], []))
    return {**{k: spec[k] for k in ("openapi", "info", "servers") if k in spec},
            "paths": paths,
            "components": {"schemas": out,
                           "securitySchemes": spec["components"].get("securitySchemes", {})}}


if __name__ == "__main__":
    spec = yaml.safe_load(open(sys.argv[1]))
    pruned = prune(spec, sys.argv[3:])
    yaml.safe_dump(pruned, open(sys.argv[2], "w"), sort_keys=False)
    print(f"{len(pruned['paths'])} paths, {len(pruned['components']['schemas'])} schemas")
