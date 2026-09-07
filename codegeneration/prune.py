"""
Simplify the OpenAPI specification by keeping only the chosen operations
Keep chosen operations and every component they transitively reference.
"""

HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}


def refs(node, out):
    """Collect internal component references in document order."""
    if isinstance(node, dict):
        target = node.get("$ref")
        if (
            isinstance(target, str)
            and target.startswith("#/components/")
            and target not in out
        ):
            out.append(target)
        for value in node.values():
            refs(value, out)
    elif isinstance(node, list):
        for value in node:
            refs(value, out)
    return out


def prune(spec: dict, endpoints: dict[str, tuple[str, ...]]) -> dict:
    """Keep configured operations and the complete closure of their component refs."""
    paths = {
        path: {
            key: value
            for key, value in spec["paths"][path].items()
            if key not in HTTP_METHODS or key in methods
        }
        for path, methods in endpoints.items()
    }
    source, components = spec["components"], {}
    queue = refs(paths, [])
    while queue:
        ref = queue.pop(0)
        parts = ref.split("/")
        section, encoded_name = parts[2:4]
        name = encoded_name.replace("~1", "/").replace("~0", "~")
        output = components.setdefault(section, {})
        if name in output:
            continue
        try:
            output[name] = source[section][name]
        except KeyError as exc:
            raise ValueError(f"unresolved OpenAPI reference: {ref}") from exc
        queue.extend(refs(output[name], []))

    components.setdefault("schemas", {})
    components["securitySchemes"] = source.get("securitySchemes", {})
    return {
        **{key: spec[key] for key in ("openapi", "info", "servers") if key in spec},
        "paths": paths,
        "components": components,
    }
