"""Turn Pydantic models into the strict JSON schemas the Claude API expects for tools and outputs.

Strict mode needs every object to list all properties as required and set additionalProperties false.
Validation constraints (ranges, lengths) are stripped from the schema and enforced by Pydantic instead.
"""

from copy import deepcopy
from typing import Any

from pydantic import BaseModel

_DROP_KEYS = {
    "title", "default", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
    "minLength", "maxLength", "pattern", "minItems", "maxItems", "examples",
}


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    raw = model.model_json_schema()
    defs = raw.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                name = node["$ref"].split("/")[-1]
                return resolve(deepcopy(defs[name]))
            out = {k: resolve(v) for k, v in node.items() if k not in _DROP_KEYS}
            if out.get("format") not in (None, "date", "date-time"):
                out.pop("format")
            if out.get("type") == "object" and "properties" in out:
                out["required"] = list(out["properties"])
                out["additionalProperties"] = False
            return out
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(raw)
