import streamlit as st
import anthropic
import json
import os
import base64
from datetime import datetime
from dotenv import load_dotenv
import sanitiser
import lineage

load_dotenv()

client = anthropic.Anthropic()

LIBRARY_FILE = "measure_library.json"
BIM_PATH = os.getenv("BIM_PATH", "")

# ── Favicon ───────────────────────────────────────────────────────────────────

_favicon_path = os.path.join(os.path.dirname(__file__), "favicon.svg")
with open(_favicon_path, "rb") as _f:
    _favicon_b64 = base64.b64encode(_f.read()).decode()
FAVICON_DATA_URL = f"data:image/svg+xml;base64,{_favicon_b64}"

# ── Page Config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Power BI DAX Agent",
    page_icon="favicon.svg",
    layout="wide"
)

# ── Session State Init ────────────────────────────────────────────────────────

if "generated_dax" not in st.session_state:
    st.session_state.generated_dax = None
if "agent_log" not in st.session_state:
    st.session_state.agent_log = []
if "generation_success" not in st.session_state:
    st.session_state.generation_success = False
if "current_request" not in st.session_state:
    st.session_state.current_request = None
if "attempts_taken" not in st.session_state:
    st.session_state.attempts_taken = 0
if "duplicate_result" not in st.session_state:
    st.session_state.duplicate_result = None
if "duplicate_measure" not in st.session_state:
    st.session_state.duplicate_measure = None
if "sanitise_report" not in st.session_state:
    st.session_state.sanitise_report = None
if "sanitised_content" not in st.session_state:
    st.session_state.sanitised_content = None
if "sanitise_pending_approval" not in st.session_state:
    st.session_state.sanitise_pending_approval = False
if "lineage_graph" not in st.session_state:
    st.session_state.lineage_graph = None

# ── Model Inspector ───────────────────────────────────────────────────────────

def _parse_model(model):
    """Shared logic: extract schema and format context string from parsed model JSON."""
    schema = {"tables": [], "relationships": []}
    tables = model.get("model", {}).get("tables", [])

    for table in tables:
        table_name = table.get("name")
        if table.get("isHidden") or table_name.startswith("DateTableTemplate"):
            continue

        columns = []
        for col in table.get("columns", []):
            if col.get("type") == "calculated":
                continue
            columns.append({"name": col.get("name"), "dataType": col.get("dataType", "unknown")})

        measures = []
        for measure in table.get("measures", []):
            expr = measure.get("expression", "")
            if isinstance(expr, list):
                expr = " ".join(expr)
            measures.append({"name": measure.get("name"), "expression": expr.strip()})

        schema["tables"].append({
            "name": table_name,
            "columns": columns,
            "measures": measures
        })

    relationships = model.get("model", {}).get("relationships", [])
    for rel in relationships:
        schema["relationships"].append({
            "from": f"{rel.get('fromTable')}[{rel.get('fromColumn')}]",
            "to": f"{rel.get('toTable')}[{rel.get('toColumn')}]"
        })

    lines = ["=== POWER BI DATA MODEL ===", ""]
    for table in schema["tables"]:
        lines.append(f"TABLE: {table['name']}")
        if table["columns"]:
            lines.append("  Columns:")
            for col in table["columns"]:
                lines.append(f"    - {col['name']} ({col['dataType']})")
        if table["measures"]:
            lines.append("  Existing Measures:")
            for m in table["measures"]:
                lines.append(f"    - {m['name']}: {m['expression']}")
        lines.append("")

    if schema["relationships"]:
        lines.append("RELATIONSHIPS:")
        for rel in schema["relationships"]:
            lines.append(f"  - {rel['from']} -> {rel['to']}")

    lines.append("")
    lines.append("=== END OF MODEL ===")
    return "\n".join(lines), schema


@st.cache_resource
def load_model_context_from_string(content_hash, content):
    """Load and format the Power BI model from sanitised content string.
    content_hash is only used as a stable cache key."""
    model = json.loads(content)
    return _parse_model(model)


@st.cache_resource
def load_model_context_from_path(bim_path):
    """Load and format the Power BI model from a given path."""
    with open(bim_path, "r", encoding="utf-8") as f:
        model = json.load(f)
    return _parse_model(model)
# ── Measure Library ───────────────────────────────────────────────────────────

def load_library():
    if os.path.exists(LIBRARY_FILE):
        with open(LIBRARY_FILE, "r") as f:
            return json.load(f)
    return []

def save_to_library(user_request, dax, attempts_taken):
    library = load_library()
    entry = {
        "id": len(library) + 1,
        "request": user_request,
        "dax": dax,
        "attempts_taken": attempts_taken,
        "created_at": datetime.now().isoformat()
    }
    library.append(entry)
    with open(LIBRARY_FILE, "w") as f:
        json.dump(library, f, indent=2)
    return entry["id"]

# ── Agent Functions ───────────────────────────────────────────────────────────

def check_for_duplicate(user_request, library):
    if not library:
        return None, None
    existing = [f"ID {m['id']}: {m['request']} => {m['dax']}" for m in library]
    existing_text = "\n".join(existing)
    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=512,
        system="""You are a Power BI measure library manager checking for duplicate measures.
Two measure requests are duplicates if they are asking for the same business calculation,
even if they use different wording.
Be aggressive about catching duplicates — if in doubt, flag it.

Respond in this exact format and nothing else:
DUPLICATE: <id number> — <one sentence explaining why it matches>
or
NEW: <one sentence explaining why no existing measure matches>""",
        messages=[{"role": "user", "content": f"New request: {user_request}\n\nExisting measures:\n{existing_text}"}]
    )
    result = message.content[0].text
    if result.startswith("DUPLICATE"):
        try:
            duplicate_id = int(result.split(":")[1].strip().split("—")[0].strip())
            existing_measure = next((m for m in library if m["id"] == duplicate_id), None)
            return result, existing_measure
        except (ValueError, IndexError):
            return result, None
    return result, None

def generate_dax(user_request, model_context, previous_attempt=None, feedback=None):
    if previous_attempt and feedback:
        content = f"""Request: {user_request}

Your previous attempt was:
{previous_attempt}

That attempt failed validation with this feedback:
{feedback}

Please fix the issue and try again.
Remember to only use tables and columns that exist in the data model below."""
    else:
        content = f"Request: {user_request}"

    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        system=f"""You are an expert Power BI DAX developer.
You must ONLY use tables and columns that exist in the data model.
Do NOT invent table or column names.
Respond with ONLY the DAX measure code — no explanations, no markdown, no backticks.

Important rules:
- For "by category" or "by dimension" requests, write a simple aggregation measure only
- NEVER use ALLEXCEPT for breakdown measures — the visual handles the breakdown
- "Number of X by Y" means just count X — Power BI visuals handle the Y breakdown
- Reuse existing measures from the model where possible

Example output format:
Total Revenue = SUM(Fact_DailyFlash[TotalRevenue])

Here is the data model you must use:

{model_context}""",
        messages=[{"role": "user", "content": content}]
    )
    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        raw = "\n".join(lines).strip()
    return raw

def validate_structural(dax):
    issues = []
    if "=" not in dax:
        issues.append("Missing measure name — no equals sign found")
    if len(dax.strip()) < 10:
        issues.append("Output is too short — may not be valid DAX")
    table_functions = ["COUNTROWS", "SUMMARIZE", "FILTER", "ALL", "ALLEXCEPT", "VALUES", "DISTINCT"]
    uses_table_function = any(fn in dax.upper() for fn in table_functions)
    if not uses_table_function and ("[" not in dax or "]" not in dax):
        issues.append("No column references found — may be incomplete")
    return issues

def validate_semantic(user_request, dax, model_context):
    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=512,
        system=f"""You are a Power BI DAX code reviewer.
Check if the DAX correctly answers the request using only valid columns from the model.

Important rules:
- In Power BI, "by category" or "by dimension" breakdowns are handled in visuals, not in measures
- A measure for "sales by channel" should just calculate total sales
- Only fail if the core calculation logic is wrong or uses non-existent columns

Respond in this exact format and nothing else:
PASS: <one sentence explaining why it is correct>
or
FAIL: <one sentence explaining what is wrong>

Data model for reference:
{model_context}""",
        messages=[{"role": "user", "content": f"Request: {user_request}\n\nDAX: {dax}"}]
    )
    return message.content[0].text

def run_agent(user_request, model_context, schema):
    max_attempts = 3
    attempt = 1
    previous_dax = None
    previous_feedback = None
    log = []

    while attempt <= max_attempts:
        log.append(f"Attempt {attempt} of {max_attempts}...")
        dax = generate_dax(user_request, model_context, previous_dax, previous_feedback)

        structural_issues = validate_structural(dax)
        if structural_issues:
            feedback = " | ".join(structural_issues)
            log.append(f"Structural issues: {feedback}")
            previous_dax = dax
            previous_feedback = feedback
            attempt += 1
            continue

        log.append("Structural validation passed.")
        semantic_result = validate_semantic(user_request, dax, model_context)
        log.append(f"Semantic: {semantic_result}")

        if semantic_result.startswith("PASS"):
            return dax, attempt, log, True
        else:
            previous_dax = dax
            previous_feedback = semantic_result
            attempt += 1

    return dax, attempt, log, False

# ── UI ────────────────────────────────────────────────────────────────────────

st.markdown(
    "<div style='text-align: center;'>Interested in what I do? Visit my website: "
    "<a href='https://kristinabachova.com' target='_blank'>kristinabachova.com</a></div>",
    unsafe_allow_html=True
)
st.markdown(
    f"<h1 style='display:flex; align-items:center; gap:12px;'>"
    f"<img src='{FAVICON_DATA_URL}' style='height:42px;'>Power BI DAX Agent</h1>",
    unsafe_allow_html=True
)
st.caption("Generate, validate and manage DAX measures for your Power BI model.")

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Model Settings")

    folder_path_input = st.text_input(
        "Path to model folder:",
        value=os.path.dirname(BIM_PATH) if BIM_PATH else "",
        help="Paste the folder that contains your Model.bim file — the filename will be added automatically"
    )
    model_path_input = os.path.join(folder_path_input, "Model.bim") if folder_path_input else ""
    if model_path_input:
        st.caption(f"Full path: `{model_path_input}`")

    st.caption("Sanitisation settings")
    san_sql = st.toggle("Mask SQL connection strings", value=True)
    san_paths = st.toggle("Mask file & network paths", value=True)
    san_urls = st.toggle("Mask URLs", value=True)
    san_emails = st.toggle("Mask email addresses", value=True)
    san_guids = st.toggle("Mask GUIDs", value=False)
    san_rls = st.toggle("Remove RLS role definitions", value=False)
    san_comments = st.toggle("Remove developer comments", value=True)

    load_model_btn = st.button("Load Model", type="primary")
    st.caption(
        "No data leaves your computer at this step. Clicking Load Model runs the "
        "sanitiser locally on your laptop and creates a temporary in-memory copy "
        "of the file with sensitive items redacted. You will then review the results "
        "and choose to approve or cancel before anything is loaded into the agent."
    )

    if load_model_btn:
        if not os.path.exists(model_path_input):
            st.error(f"File not found: {model_path_input}")
        else:
            with st.spinner("Scanning for sensitive data..."):
                try:
                    san_content, san_report = sanitiser.sanitise_model(
                        model_path_input,
                        mask_sql_connections=san_sql,
                        mask_file_paths=san_paths,
                        mask_urls=san_urls,
                        mask_emails=san_emails,
                        mask_guids=san_guids,
                        remove_rls=san_rls,
                        remove_comments=san_comments,
                    )
                    st.session_state.sanitised_content = san_content
                    st.session_state.sanitise_report = san_report
                    st.session_state.sanitise_pending_approval = True
                    # Clear any previously loaded model
                    st.cache_resource.clear()
                    st.session_state.pop("model_path", None)
                    st.session_state.pop("model_context", None)
                    st.session_state.pop("schema", None)
                    st.rerun()
                except Exception as e:
                    st.error(f"Sanitisation failed: {e}")

    if "model_path" not in st.session_state and BIM_PATH:
        st.session_state.model_path = BIM_PATH

st.divider()

# ── Sanitisation Review Screen ────────────────────────────────────────────────
if st.session_state.sanitise_pending_approval and st.session_state.sanitise_report:
    report = st.session_state.sanitise_report
    total = report["total_replacements"]

    st.subheader("Model Sanitisation Review")

    if total == 0:
        st.success("No sensitive items found. The model appears clean.")
    else:
        st.warning(f"{total} sensitive item(s) were found and masked before loading.")

    # Settings used
    s = report["settings"]
    setting_labels = {
        "mask_sql_connections": "SQL connections",
        "mask_file_paths": "file/network paths",
        "mask_urls": "URLs",
        "mask_emails": "emails",
        "mask_guids": "GUIDs",
        "remove_rls": "RLS roles",
        "remove_comments": "comments",
    }
    on = [label for key, label in setting_labels.items() if s.get(key)]
    off = [label for key, label in setting_labels.items() if not s.get(key)]
    st.caption(f"Scanning for: {', '.join(on) or 'nothing'}  |  Skipped: {', '.join(off) or 'none'}")

    # Category breakdown
    if report["categories"]:
        st.markdown("**Replacements by category**")
        cat_rows = [{"Category": k, "Count": v} for k, v in sorted(report["categories"].items())]
        st.table(cat_rows)

    # Items found — expanded by default so the user can see exactly what was redacted
    if report["items_found"]:
        with st.expander(f"{len(report['items_found'])} item(s) found — click to collapse", expanded=True):
            for item in report["items_found"]:
                st.markdown(
                    f"- **{item['category']}** &nbsp;|&nbsp; "
                    f"`{item['original'][:80]}` &nbsp;→&nbsp; `{item['replacement']}`"
                )
    elif total == 0:
        st.info("Nothing was redacted — the model contains no sensitive items matching the selected categories.")

    col_approve, col_cancel = st.columns(2)
    with col_approve:
        if st.button("Approve and Load Model", type="primary"):
            try:
                content = st.session_state.sanitised_content
                content_hash = str(hash(content))
                model_context, schema = load_model_context_from_string(content_hash, content)
                st.session_state.model_context = model_context
                st.session_state.schema = schema
                st.session_state.lineage_graph = lineage.build_graph_from_model_dict(
                    json.loads(content)
                )
                st.session_state.sanitise_pending_approval = False
                st.rerun()
            except Exception as e:
                st.error(f"Failed to parse sanitised model: {e}")
    with col_cancel:
        if st.button("Cancel"):
            st.session_state.sanitise_pending_approval = False
            st.session_state.sanitised_content = None
            st.session_state.sanitise_report = None
            st.rerun()

    st.stop()

# ── Model Loading ─────────────────────────────────────────────────────────────
# Use approved sanitised content if available, otherwise load from path
if "model_context" in st.session_state and st.session_state.model_context:
    try:
        model_context = st.session_state.model_context
        schema = st.session_state.schema
        table_count = len(schema["tables"])
        rel_count = len(schema["relationships"])
        st.success(f"Model loaded — {table_count} tables, {rel_count} relationships.")
    except Exception as e:
        st.error(f"Could not load model: {e}")
        st.stop()
elif st.session_state.get("model_path") and os.path.exists(st.session_state.model_path):
    try:
        model_context, schema = load_model_context_from_path(st.session_state.model_path)
        table_count = len(schema["tables"])
        rel_count = len(schema["relationships"])
        st.success(f"Model loaded — {table_count} tables, {rel_count} relationships.")
    except Exception as e:
        st.error(f"Could not load model: {e}")
        st.stop()
else:
    st.info("Enter the path to your Power BI model (.bim file) in the sidebar and click **Load Model** to get started.")
    st.stop()

# Add model browser and search to sidebar now that schema is loaded
with st.sidebar:
    st.divider()
    st.header("🔍 Measure Search")
    search_term = st.text_input("Search library:", placeholder="e.g. revenue")
    if search_term:
        library = load_library()
        results = [m for m in library if search_term.lower() in m["request"].lower()
                  or search_term.lower() in m["dax"].lower()]
        if results:
            st.caption(f"{len(results)} match(es) found")
            for m in results:
                with st.expander(f"#{m['id']} — {m['request'][:35]}"):
                    st.code(m["dax"], language="dax")
        else:
            st.caption("No matches found.")

    st.divider()
    st.header("📋 Model Browser")
    for table in schema["tables"]:
        with st.expander(f"{table['name']}"):
            if table["columns"]:
                st.caption("Columns")
                for col in table["columns"]:
                    st.markdown(f"- `{col['name']}` *{col['dataType']}*")
            if table["measures"]:
                st.caption("Existing Measures")
                for m in table["measures"]:
                    st.markdown(f"- `[{m['name']}]`")

    if st.session_state.lineage_graph:
        g = st.session_state.lineage_graph
        node_types = {}
        for node in g["nodes"].values():
            node_types[node["type"]] = node_types.get(node["type"], 0) + 1
        st.divider()
        st.header("🔗 Lineage")
        st.caption(f"{len(g['nodes'])} nodes · {len(g['edges'])} edges")
        for ntype, count in sorted(node_types.items()):
            st.caption(f"  {ntype}: {count}")

st.divider()

tab_generate, tab_impact = st.tabs(["Generate a Measure", "Impact Analysis"])

with tab_generate:
  col1, col2 = st.columns([2, 1])

  with col1:
    st.subheader("Generate a Measure")
    user_request = st.text_area(
        "Describe the measure you need:",
        placeholder="e.g. total room revenue for the current year",
        height=100
    )

    generate_btn = st.button("Generate DAX", type="primary")

    if generate_btn and user_request.strip():
        # Reset state
        st.session_state.generated_dax = None
        st.session_state.generation_success = False
        st.session_state.agent_log = []
        st.session_state.current_request = user_request
        st.session_state.duplicate_result = None
        st.session_state.duplicate_measure = None

        # Duplicate check
        with st.spinner("Checking measure library..."):
            library = load_library()
            dup_result, dup_measure = check_for_duplicate(user_request, library)
            st.session_state.duplicate_result = dup_result
            st.session_state.duplicate_measure = dup_measure

        if dup_result and dup_result.startswith("DUPLICATE") and dup_measure:
            pass  # handled below
        else:
            # Run agent
            with st.spinner("Generating and validating DAX..."):
                dax, attempts, log, success = run_agent(user_request, model_context, schema)
                st.session_state.generated_dax = dax
                st.session_state.agent_log = log
                st.session_state.generation_success = success
                st.session_state.attempts_taken = attempts

    # Show duplicate warning
    if st.session_state.duplicate_result and st.session_state.duplicate_result.startswith("DUPLICATE") and st.session_state.duplicate_measure:
        st.warning(f"Similar measure found: {st.session_state.duplicate_result}")
        st.code(st.session_state.duplicate_measure["dax"], language="dax")
        if st.button("Generate new measure anyway"):
            with st.spinner("Generating and validating DAX..."):
                dax, attempts, log, success = run_agent(
                    st.session_state.current_request, model_context, schema
                )
                st.session_state.generated_dax = dax
                st.session_state.agent_log = log
                st.session_state.generation_success = success
                st.session_state.attempts_taken = attempts
                st.session_state.duplicate_result = None
                st.session_state.duplicate_measure = None

    # Show agent results
    if st.session_state.generated_dax:
        if st.session_state.agent_log:
            with st.expander("Agent log", expanded=False):
                for line in st.session_state.agent_log:
                    st.text(line)

        if st.session_state.generation_success:
            st.success(f"DAX generated and validated in {st.session_state.attempts_taken} attempt(s).")
            st.subheader("Generated DAX")
            st.code(st.session_state.generated_dax, language="dax")

            st.subheader("Approve & Save")
            st.info("Review the DAX above. If correct, click Approve to save to your library.")

            col_approve, col_reject = st.columns(2)
            with col_approve:
                if st.button("✅ Approve & Save", type="primary"):
                    measure_id = save_to_library(
                        st.session_state.current_request,
                        st.session_state.generated_dax,
                        st.session_state.attempts_taken
                    )
                    st.success(f"✅ Saved to library as measure #{measure_id}")
                    st.info("Copy the DAX above into Tabular Editor to deploy to your model.")
                    st.session_state.generated_dax = None
                    st.session_state.generation_success = False
            with col_reject:
                if st.button("❌ Reject"):
                    st.warning("Measure rejected. Try rephrasing your request.")
                    st.session_state.generated_dax = None
                    st.session_state.generation_success = False
        else:
            st.error("Could not generate valid DAX after 3 attempts.")
            st.code(st.session_state.generated_dax, language="dax")
            st.info("Try rephrasing your request with more specific table and column names.")

  with col2:
      st.subheader("Measure Library")
      library = load_library()

      if not library:
          st.info("No measures saved yet.")
      else:
          st.caption(f"{len(library)} measures saved")
          for entry in reversed(library[-10:]):
              with st.expander(f"#{entry['id']} — {entry['request'][:40]}"):
                  st.code(entry["dax"], language="dax")
                  st.caption(f"Saved: {entry['created_at'][:10]}")

# ── Impact Analysis Tab ────────────────────────────────────────────────────────
with tab_impact:
    st.subheader("Impact Analysis")
    st.markdown(
        "Impact Analysis shows you which measures, columns, and tables depend on a selected "
        "object in your data model. Use it before renaming or removing a column or table to "
        "understand what would break, or to trace which measures are built on top of a given field."
    )

    if not st.session_state.lineage_graph:
        st.info("Load a model first to use Impact Analysis.")
    else:
        g = st.session_state.lineage_graph

        options = {}  # display label -> node_id
        for node_id, node in sorted(g["nodes"].items(), key=lambda x: (x[1]["type"], x[1]["name"])):
            if node["type"] == "table":
                label = f"[Table]  {node['name']}"
            elif node["type"] == "column":
                table = node.get("metadata", {}).get("table", "")
                label = f"[Column]  {table} → {node['name']}"
            elif node["type"] == "measure":
                table = node.get("metadata", {}).get("table", "")
                label = f"[Measure]  {table} → {node['name']}"
            else:
                continue
            options[label] = node_id

        selected_label = st.selectbox(
            "Select an object:",
            options=["— select —"] + list(options.keys()),
        )

        if selected_label and selected_label != "— select —":
            selected_node_id = options[selected_label]
            impacts = lineage.impact_analysis(g, selected_node_id)

            if not impacts:
                st.success("No dependents found — this object is safe to change.")
            else:
                st.warning(f"{len(impacts)} object(s) would be affected by changes to this item.")
                type_icon = {"measure": "📐", "column": "📋", "table": "🗂️"}
                rel_label = {
                    "references_column": "uses column",
                    "references_measure": "uses measure",
                    "belongs_to": "belongs to",
                    "relates_to": "relates to",
                }
                for item in impacts:
                    indent = "&nbsp;" * (item["depth"] * 6)
                    icon = type_icon.get(item["type"], "•")
                    rel = rel_label.get(item["relationship"], item["relationship"])
                    st.markdown(
                        f"{indent}{icon} **{item['name']}** "
                        f"<span style='color:#78716C'>({item['type']} · {rel})</span>",
                        unsafe_allow_html=True,
                    )