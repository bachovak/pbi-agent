"""
model_inspector.py — Reads a model.bim file and extracts schema information.

Provides two output formats:
  - extract_schema() / format_schema_for_prompt(): human-readable text for
    Claude system prompts (backward-compatible with existing callers).
  - build_model_registry() / format_registry_for_prompt(): structured dict
    used by System B (generation constraint) and System C (reference validation).

Architecture note: patterns for model-aware generation constraints and
reference validation were informed by analysis of the data-goblin/
power-bi-agentic-development repository (GPL v3). The implementation here
is original code.
"""

import json
import os


# ── Internal helpers ──────────────────────────────────────────────────────────

def _is_hidden_table(table):
    name = table.get("name", "")
    return (
        table.get("isHidden", False)
        or name.startswith("DateTableTemplate")
        or name.startswith("LocalDateTable")
    )


def _normalise_expression(expr):
    """Coerce expression to a single stripped string (BIM stores it as str or list)."""
    if isinstance(expr, list):
        return " ".join(expr).strip()
    return (expr or "").strip()


def _get_compat_level(model):
    return model.get("model", {}).get("compatibilityLevel", 0)


def _has_calc_groups(model):
    for table in model.get("model", {}).get("tables", []):
        if "calculationGroup" in table:
            return True
    return False


# ── File I/O ──────────────────────────────────────────────────────────────────

def load_model(bim_path):
    """Read a model.bim file and return the parsed JSON."""
    with open(bim_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Schema extraction — text prompt format (System A v1, backward-compatible) ─

def extract_schema(model):
    """
    Extract tables, columns, measures, and relationships from the model.
    Returns a dict suitable for format_schema_for_prompt().

    Now includes summarizeBy and isKey per column so callers have richer
    data without needing to call build_model_registry() separately.
    """
    schema = {"tables": [], "relationships": []}

    for table in model.get("model", {}).get("tables", []):
        if _is_hidden_table(table):
            continue

        columns = []
        for col in table.get("columns", []):
            if col.get("type") == "calculated":
                continue
            columns.append({
                "name":        col.get("name"),
                "dataType":    col.get("dataType", "unknown"),
                "summarizeBy": col.get("summarizeBy", "default"),
                "isKey":       bool(col.get("isKey", False)),
                "isHidden":    bool(col.get("isHidden", False)),
            })

        measures = []
        for m in table.get("measures", []):
            measures.append({
                "name":       m.get("name"),
                "expression": _normalise_expression(m.get("expression", "")),
            })

        schema["tables"].append({
            "name":     table.get("name"),
            "columns":  columns,
            "measures": measures,
        })

    for rel in model.get("model", {}).get("relationships", []):
        schema["relationships"].append({
            "from":   f"{rel.get('fromTable')}[{rel.get('fromColumn')}]",
            "to":     f"{rel.get('toTable')}[{rel.get('toColumn')}]",
            "active": rel.get("isActive", True),
        })

    return schema


def format_schema_for_prompt(schema):
    """Format the schema as a readable context block for Claude."""
    lines = ["=== POWER BI DATA MODEL ===", ""]

    for table in schema["tables"]:
        lines.append(f"TABLE: {table['name']}")
        if table["columns"]:
            lines.append("  Columns:")
            for col in table["columns"]:
                tags = []
                if col.get("isKey"):
                    tags.append("key")
                if col.get("summarizeBy") == "none":
                    tags.append("no-aggregate")
                tag_str = f"  [{', '.join(tags)}]" if tags else ""
                lines.append(f"    - '{table['name']}'[{col['name']}] ({col['dataType']}){tag_str}")
        if table["measures"]:
            lines.append("  Existing Measures:")
            for m in table["measures"]:
                lines.append(f"    - [{m['name']}]: {m['expression']}")
        lines.append("")

    if schema["relationships"]:
        lines.append("RELATIONSHIPS:")
        for rel in schema["relationships"]:
            inactive = " [INACTIVE — requires USERELATIONSHIP()]" if not rel.get("active", True) else ""
            lines.append(f"  - {rel['from']} -> {rel['to']}{inactive}")
    else:
        lines.append("RELATIONSHIPS: None defined yet")

    lines += ["", "=== END OF MODEL ==="]
    return "\n".join(lines)


# ── Model registry — structured dict format (System A v2) ────────────────────

def build_model_registry(model):
    """
    Build a structured registry of all model objects for programmatic use.

    Used by:
      - System B: injected into the system prompt as a hard generation constraint
        so Claude only references objects that actually exist.
      - System C (SemanticReferenceValidator): used as a lookup to validate every
        'Table'[Column] and [Measure] reference extracted from generated DAX.

    Returns a dict with the following keys:
      compatibility_level   int    — model.bim compatibilityLevel
      has_calculation_groups bool  — True if any table has a calculationGroup
      tables                list   — table names (strings)
      columns               dict   — {table_name: [{ref, dataType, summarizeBy,
                                       isKey, isHidden}, ...]}
      measures              list   — [{ref, name, table, expression_preview}, ...]
      all_measure_names     list   — measure names (strings, no brackets)
      relationships         list   — [{from, to, active}, ...]
    """
    registry = {
        "compatibility_level":   _get_compat_level(model),
        "has_calculation_groups": _has_calc_groups(model),
        "tables":               [],
        "columns":              {},
        "measures":             [],
        "all_measure_names":    [],
        "relationships":        [],
    }

    for table in model.get("model", {}).get("tables", []):
        if _is_hidden_table(table):
            continue

        table_name = table.get("name")
        registry["tables"].append(table_name)

        col_entries = []
        for col in table.get("columns", []):
            if col.get("type") == "calculated":
                continue
            col_entries.append({
                "ref":         f"{table_name}[{col.get('name')}]",
                "dataType":    col.get("dataType", "unknown"),
                "summarizeBy": col.get("summarizeBy", "default"),
                "isKey":       bool(col.get("isKey", False)),
                "isHidden":    bool(col.get("isHidden", False)),
            })
        registry["columns"][table_name] = col_entries

        for m in table.get("measures", []):
            m_name = m.get("name")
            registry["measures"].append({
                "ref":                f"[{m_name}]",
                "name":               m_name,
                "table":              table_name,
                "expression_preview": _normalise_expression(m.get("expression", ""))[:80],
            })
            registry["all_measure_names"].append(m_name)

    for rel in model.get("model", {}).get("relationships", []):
        registry["relationships"].append({
            "from":   f"{rel.get('fromTable')}[{rel.get('fromColumn')}]",
            "to":     f"{rel.get('toTable')}[{rel.get('toColumn')}]",
            "active": rel.get("isActive", True),
        })

    return registry


def format_registry_for_prompt(registry):
    """
    Format the model registry as a structured block to embed in System B's
    system prompt as a hard generation constraint.
    """
    lines = [
        "=== MODEL OBJECT REGISTRY ===",
        "",
        f"Compatibility level    : {registry['compatibility_level']}",
        f"Calculation groups     : {'YES — SELECTEDMEASURE() is available' if registry['has_calculation_groups'] else 'NO — do NOT use SELECTEDMEASURE()'}",
        "",
        "VALID TABLES AND COLUMNS:",
        "  (Format to use in DAX: 'TableName'[ColumnName])",
        "  Tags: [key] = primary/foreign key — never aggregate directly",
        "        [no-aggregate] = summarizeBy=none — never wrap in SUM/AVG/MIN/MAX/COUNT",
    ]

    for table_name in registry["tables"]:
        lines.append(f"\n  TABLE: {table_name}")
        for col in registry["columns"].get(table_name, []):
            col_name = col["ref"].split("[", 1)[1].rstrip("]")
            tags = []
            if col["isKey"]:
                tags.append("key")
            if col["summarizeBy"] == "none":
                tags.append("no-aggregate")
            tag_str = f"  [{', '.join(tags)}]" if tags else ""
            lines.append(f"    '{table_name}'[{col_name}]{tag_str}")

    lines += [
        "",
        "VALID MEASURES:",
        "  (Format to use in DAX: [MeasureName]  — never quote with table name)",
    ]
    if registry["measures"]:
        for m in registry["measures"]:
            lines.append(f"    {m['ref']}  (table: {m['table']})")
    else:
        lines.append("    (none defined yet)")

    if registry["relationships"]:
        lines += ["", "RELATIONSHIPS:"]
        for rel in registry["relationships"]:
            inactive = " [INACTIVE — use USERELATIONSHIP() to activate]" if not rel["active"] else ""
            lines.append(f"    {rel['from']} -> {rel['to']}{inactive}")

    lines += ["", "=== END OF REGISTRY ==="]
    return "\n".join(lines)


# ── CLI ───────────────────────────────────────────────────────────────────────

def inspect_model(bim_path):
    """Load a model.bim and print the formatted schema."""
    if not os.path.exists(bim_path):
        raise FileNotFoundError(f"Cannot find model file at: {bim_path}")

    print(f"Reading model from: {bim_path}")
    model = load_model(bim_path)
    schema = extract_schema(model)
    formatted = format_schema_for_prompt(schema)

    print(f"Found {len(schema['tables'])} tables")
    print(f"Found {len(schema['relationships'])} relationships")
    print(f"Compatibility level   : {_get_compat_level(model)}")
    print(f"Calculation groups    : {_has_calc_groups(model)}")
    print("")
    print(formatted)
    return formatted


if __name__ == "__main__":
    bim_path = input("Enter the full path to your model.bim file: ")
    inspect_model(bim_path)
