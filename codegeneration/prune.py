"""Keep only the chosen operations and the schemas they transitively reference."""

HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}


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


def prune(spec: dict, endpoints: dict[str, tuple[str, ...]]) -> dict:
    """Keep configured path/method pairs plus path metadata and referenced schemas."""
    paths = {
        path: {
            key: value
            for key, value in spec["paths"][path].items()
            if key not in HTTP_METHODS or key in methods
        }
        for path, methods in endpoints.items()
    }
    schemas, out = spec["components"]["schemas"], {}
    queue = refs(paths, [])
    while queue:
        name = queue.pop(0)
        if name in out or name not in schemas:
            continue
        out[name] = schemas[name]
        queue.extend(refs(schemas[name], []))
    return {
        **{key: spec[key] for key in ("openapi", "info", "servers") if key in spec},
        "paths": paths,
        "components": {
            "schemas": out,
            "securitySchemes": spec["components"].get("securitySchemes", {}),
        },
    }
