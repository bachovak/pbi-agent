import json
import os

def load_model(bim_path):
    """Read a model.bim file and return the parsed JSON."""
    with open(bim_path, "r", encoding="utf-8") as f:
        return json.load(f)

def extract_schema(model):
    """Extract tables, columns, and measures from the model."""
    schema = {
        "tables": [],
        "relationships": []
    }

    tables = model.get("model", {}).get("tables", [])
    
    for table in tables:
        table_name = table.get("name")
        
        # Skip hidden system tables
        if table.get("isHidden") or table_name.startswith("DateTableTemplate"):
            continue

        # Get regular columns (not calculated)
        columns = []
        for col in table.get("columns", []):
            if col.get("type") == "calculated":
                continue
            columns.append({
                "name": col.get("name"),
                "dataType": col.get("dataType", "unknown")
            })

        # Get existing measures
        measures = []
        for measure in table.get("measures", []):
            measures.append({
                "name": measure.get("name"),
                "expression": measure.get("expression", "").strip()
            })

        schema["tables"].append({
            "name": table_name,
            "columns": columns,
            "measures": measures
        })

    # Get relationships
    relationships = model.get("model", {}).get("relationships", [])
    for rel in relationships:
        schema["relationships"].append({
            "from": f"{rel.get('fromTable')}[{rel.get('fromColumn')}]",
            "to": f"{rel.get('toTable')}[{rel.get('toColumn')}]",
            "cardinality": rel.get("crossFilteringBehavior", "singleDirection")
        })

    return schema

def format_schema_for_prompt(schema):
    """Format the schema as a clean context block for Claude."""
    lines = []
    lines.append("=== POWER BI DATA MODEL ===")
    lines.append("")

    for table in schema["tables"]:
        lines.append(f"TABLE: {table['name']}")
        
        if table["columns"]:
            lines.append("  Columns:")
            for col in table["columns"]:
                lines.append(f"    - {col['name']} ({col['dataType']})")
        
        if table["measures"]:
            lines.append("  Existing Measures:")
            for measure in table["measures"]:
                lines.append(f"    - {measure['name']}: {measure['expression']}")
        
        lines.append("")

    if schema["relationships"]:
        lines.append("RELATIONSHIPS:")
        for rel in schema["relationships"]:
            lines.append(f"  - {rel['from']} -> {rel['to']}")
    else:
        lines.append("RELATIONSHIPS: None defined yet")

    lines.append("")
    lines.append("=== END OF MODEL ===")

    return "\n".join(lines)

def inspect_model(bim_path):
    """Main function: load and format a model.bim file."""
    if not os.path.exists(bim_path):
        raise FileNotFoundError(f"Cannot find model file at: {bim_path}")
    
    print(f"Reading model from: {bim_path}")
    model = load_model(bim_path)
    schema = extract_schema(model)
    formatted = format_schema_for_prompt(schema)
    
    print(f"Found {len(schema['tables'])} tables")
    print(f"Found {len(schema['relationships'])} relationships")
    print("")
    print(formatted)
    
    return formatted

# --- Test it ---
if __name__ == "__main__":
    # Update this path to where your model.bim file is
    bim_path = input("Enter the full path to your model.bim file: ")
    inspect_model(bim_path)
