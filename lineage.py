import json
import os
import re
from datetime import datetime

LINEAGE_FILE = "lineage.json"

# ── Graph Structure ───────────────────────────────────────────────────────────

def create_empty_graph():
    """Create an empty lineage graph."""
    return {
        "nodes": {},
        "edges": [],
        "last_updated": datetime.now().isoformat()
    }

def add_node(graph, node_id, node_type, name, metadata=None):
    """Add a node to the graph."""
    graph["nodes"][node_id] = {
        "id": node_id,
        "type": node_type,
        "name": name,
        "metadata": metadata or {}
    }

def add_edge(graph, from_id, to_id, relationship):
    """Add a directed edge between two nodes."""
    edge = {
        "from": from_id,
        "to": to_id,
        "relationship": relationship
    }
    # Avoid duplicates
    if edge not in graph["edges"]:
        graph["edges"].append(edge)

def save_graph(graph):
    """Save the lineage graph to a JSON file."""
    graph["last_updated"] = datetime.now().isoformat()
    with open(LINEAGE_FILE, "w") as f:
        json.dump(graph, f, indent=2)
    print(f"Lineage graph saved: {len(graph['nodes'])} nodes, {len(graph['edges'])} edges.")

def load_graph():
    """Load the lineage graph from file, or create empty if not found."""
    if os.path.exists(LINEAGE_FILE):
        with open(LINEAGE_FILE, "r") as f:
            return json.load(f)
    return create_empty_graph()

# ── Graph Population ──────────────────────────────────────────────────────────

def extract_column_references(dax_expression):
    """Find all Table[Column] references in a DAX expression."""
    pattern = r"(\w+)\[([^\]]+)\]"
    return re.findall(pattern, dax_expression)

def build_graph_from_model(bim_path):
    """Build a lineage graph from a model.bim file."""
    print(f"Building lineage graph from: {bim_path}")

    with open(bim_path, "r", encoding="utf-8") as f:
        model = json.load(f)

    graph = create_empty_graph()
    tables = model.get("model", {}).get("tables", [])

    # Pass 1: Add all table and column nodes
    for table in tables:
        table_name = table.get("name")
        if table.get("isHidden") or table_name.startswith("DateTableTemplate"):
            continue

        # Add table node
        table_id = f"table::{table_name}"
        add_node(graph, table_id, "table", table_name)

        # Add column nodes
        for col in table.get("columns", []):
            if col.get("type") == "calculated":
                continue
            col_name = col.get("name")
            col_id = f"column::{table_name}::{col_name}"
            add_node(graph, col_id, "column", col_name, {
                "table": table_name,
                "dataType": col.get("dataType", "unknown")
            })
            # Column belongs to table
            add_edge(graph, col_id, table_id, "belongs_to")

    # Pass 2: Add measure nodes and their dependencies
    for table in tables:
        table_name = table.get("name")
        if table.get("isHidden") or table_name.startswith("DateTableTemplate"):
            continue

        for measure in table.get("measures", []):
            measure_name = measure.get("name")
            expr = measure.get("expression", "")
            if isinstance(expr, list):
                expr = " ".join(expr)
            expr = expr.strip()

            measure_id = f"measure::{table_name}::{measure_name}"
            add_node(graph, measure_id, "measure", measure_name, {
                "table": table_name,
                "expression": expr
            })

            # Find column references in the DAX
            refs = extract_column_references(expr)
            for ref_table, ref_col in refs:
                # Check if it references a column
                col_id = f"column::{ref_table}::{ref_col}"
                if col_id in graph["nodes"]:
                    add_edge(graph, measure_id, col_id, "references_column")

                # Check if it references another measure
                measure_ref_id = f"measure::{ref_table}::{ref_col}"
                if measure_ref_id in graph["nodes"]:
                    add_edge(graph, measure_id, measure_ref_id, "references_measure")

    # Pass 3: Add relationship edges between tables
    relationships = model.get("model", {}).get("relationships", [])
    for rel in relationships:
        from_table = rel.get("fromTable")
        to_table = rel.get("toTable")
        from_col = rel.get("fromColumn")
        to_col = rel.get("toColumn")

        from_col_id = f"column::{from_table}::{from_col}"
        to_col_id = f"column::{to_table}::{to_col}"

        if from_col_id in graph["nodes"] and to_col_id in graph["nodes"]:
            add_edge(graph, from_col_id, to_col_id, "relates_to")

    return graph

# ── Impact Analysis ───────────────────────────────────────────────────────────

def get_dependents(graph, node_id):
    """Find everything that depends on a given node."""
    dependents = []
    for edge in graph["edges"]:
        if edge["to"] == node_id:
            dependent_node = graph["nodes"].get(edge["from"])
            if dependent_node:
                dependents.append({
                    "id": edge["from"],
                    "type": dependent_node["type"],
                    "name": dependent_node["name"],
                    "relationship": edge["relationship"]
                })
    return dependents

def impact_analysis(graph, node_id, depth=0, visited=None):
    """Recursively find all objects affected by a change to a node."""
    if visited is None:
        visited = set()

    if node_id in visited:
        return []
    visited.add(node_id)

    results = []
    dependents = get_dependents(graph, node_id)

    for dep in dependents:
        results.append({
            "depth": depth,
            "type": dep["type"],
            "name": dep["name"],
            "id": dep["id"],
            "relationship": dep["relationship"]
        })
        # Recurse to find what depends on this dependent
        results.extend(impact_analysis(graph, dep["id"], depth + 1, visited))

    return results

def print_impact_report(graph, node_id):
    """Print a human readable impact report for a node."""
    node = graph["nodes"].get(node_id)
    if not node:
        print(f"Node not found: {node_id}")
        return

    print(f"\n{'='*50}")
    print(f"IMPACT ANALYSIS: {node['type'].upper()} — {node['name']}")
    print(f"{'='*50}")

    impacts = impact_analysis(graph, node_id)

    if not impacts:
        print("No dependents found — nothing else references this object.")
    else:
        print(f"{len(impacts)} object(s) would be affected:\n")
        for item in impacts:
            indent = "  " * item["depth"]
            print(f"{indent}→ [{item['type']}] {item['name']}")

    print(f"{'='*50}\n")

# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    bim_path = os.getenv("BIM_PATH", "Model.bim")

    # Build and save the graph
    graph = build_graph_from_model(bim_path)
    save_graph(graph)

    # Print summary
    node_types = {}
    for node in graph["nodes"].values():
        node_types[node["type"]] = node_types.get(node["type"], 0) + 1

    print("\nGraph summary:")
    for node_type, count in node_types.items():
        print(f"  {node_type}: {count}")

    print(f"\nEdges: {len(graph['edges'])}")

    # Demo: impact analysis on RoomRevenue column
    print("\nDemo — what depends on Fact_DailyFlash[RoomRevenue]?")
    print_impact_report(graph, "column::Fact_DailyFlash::RoomRevenue")
