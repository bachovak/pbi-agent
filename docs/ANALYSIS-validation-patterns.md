# Validation & Sanitisation Patterns — Analysis

> Source: Full read of all 14 SKILL.md files in `data-goblin/power-bi-agentic-development`
> Date: 2026-03-31
> Purpose: Improve System A/B/C validation logic in this agent; identify System D gap

---

## Context

This agent has three systems:
- **System A** — model discovery (reads semantic model metadata from `Model.bim`)
- **System B** — DAX generation (produces measure expressions)
- **System C** — amendment protection (prevents breaking existing measures)

**The gap being closed:** System B can generate DAX that passes System C's structural checks but is semantically wrong — referencing tables, columns, or measures that don't exist in the model. Structural correctness (syntax) does not guarantee semantic correctness (valid object references).

---

## Part 1: All Validation Patterns Found Across 14 SKILL.md Files

### Group A — "Read the model first, generate second" gates

**A1 — Discovery before modification** (`standardize-naming-conventions`, Phase 1)
> *"Scan all table TMDL files to build a complete picture of current naming patterns. Focus on: Table names, Measure names, Column names, Display folder structure."*

Solves: acting on stale or assumed model state. The agent reads the actual model before proposing any change.

**A2 — Business context gate** (`standardize-naming-conventions`, Phase 2)
> *"CRITICAL: Do not rename anything without understanding the business terminology."*

Solves: generating correct-looking output that breaks business semantics.

**A3 — Double-diamond requirements gate** (`bpa-rules`, Primary Workflow)
> *"CRITICAL: Do NOT generate BPA rules immediately... Do not generate rules until the user confirms the priorities."*

Solves: premature generation that wastes effort or generates rules misaligned to the actual model.

**A4 — Model investigation before generation** (`bpa-rules`, Phase 2)
> Investigate: table count, measure count, column count, storage mode, metadata completeness, DAX patterns in use, naming conventions currently in use, existing BPA annotations.

Solves: generating rules that reference wrong scope, wrong object types, or non-existent patterns.

**A5 — Check semantic model before binding fields** (`pbir-format`, Modifying a report, step 3)
> *"Check the connected semantic model... Understanding the model helps you to know what fields are available for visuals."*

Solves: PBIR visuals that reference fields that don't exist.

**A6 — Check page dimensions before positioning** (`pbi-report-design`)
> *"Always query the actual page dimensions before adding or repositioning visuals. Do not assume a page is 1280x720."*

Solves the "don't assume environment state" principle — same logic applies to model state.

---

### Group B — Existence checks at the point of use

**B1 — `Contains()` before access in C# scripts** (`c-sharp-scripting`, Debugging section)
```csharp
if(Model.Tables.Contains("Sales")) {
    var table = Model.Tables["Sales"];
} else {
    Error("Table 'Sales' not found");
}
// Or: Model.Tables.FirstOrDefault(t => t.Name == "Sales")
```
Solves: NullReferenceException when scripting against models where the object may not exist. Equivalent to: never blindly reference a table/column/measure.

**B2 — Existence check in LINQ** (`c-sharp-scripting`, LINQ examples)
```csharp
if(Model.Tables.Any(t => t.Name == "Sales")) { ... }
var dateTable = Model.Tables.FirstOrDefault(t => t.DataCategory == "Time");
```
Solves: same problem, expressed in query form. This is the pattern a validation layer uses to check generated DAX references against a model inventory.

**B3 — Field binding validity rule** (`pbi-report-design`, Core rules #7)
> *"All data visuals should have field bindings, and all field bindings should be for fields that actually exist in the model; there is no reason for visuals to exist that have no fields bound."*

Solves: visuals silently returning blanks because a field reference is wrong. This is the report-layer analogue of the System B gap.

**B4 — Field name matching in Deneb** (`deneb-visuals`, Best Practices #8)
> *"Test field names — verify `nativeQueryRef` matches spec field references."*

Solves: Deneb spec that looks syntactically valid but references a field by the wrong display name.

---

### Group C — "Validate after writing, before committing" hooks

**C1 — Validate-often rule** (`pbir-format`, General critical guidance)
> *"Validate often: Any time a JSON file changes, validate it IMMEDIATELY after the modification to avoid 'breaking' changes with `jq empty <file.json>`."*

Solves: a broken file silently corrupting downstream state before discovery.

**C2 — Valid syntax ≠ valid semantics** (`pbir-format`, General critical guidance)
> *"Valid JSON does not guarantee rendering. A visual might not render if the bound field is invalid (missing, wrong table, or misspelled) in the visual.json."*

**This is the exact System B/C gap, stated explicitly: structural correctness is necessary but not sufficient.**

**C3 — TOM validation before SaveChanges** (`connect-pbid`, Validation section)
```powershell
$results = [Microsoft.AnalysisServices.Tabular.TomValidation]::Validate($model)
```
Manual fallback checks:
```powershell
# Check measures have valid expressions
foreach ($m in ...) {
    if ([string]::IsNullOrWhiteSpace($m.Expression)) {
        Write-Output "WARNING: Measure [$($m.Name)] has no expression"
    }
}
# Check relationships reference valid columns
foreach ($rel in $model.Relationships) {
    $sr = [Microsoft.AnalysisServices.Tabular.SingleColumnRelationship]$rel
    if ($sr.FromColumn -eq $null -or $sr.ToColumn -eq $null) {
        Write-Output "WARNING: Relationship [$($sr.Name)] has null column references"
    }
}
# Check for duplicate measure names across tables
$names = @{}
foreach ($m in ($model.Tables | ForEach-Object { $_.Measures })) {
    if ($names.ContainsKey($m.Name)) {
        Write-Output "WARNING: Duplicate measure name [$($m.Name)]"
    }
    $names[$m.Name] = $m.Table.Name
}
```
Solves: changes that are internally inconsistent or reference null objects.

**C4 — BPA expression validation** (`bpa-rules`, Critical section)
> *"Always validate rule expressions before suggesting them. Test expressions against the target scope. Ensure FixExpression does not cause data loss or break the model."*

Solves: auto-fix expressions that pass syntax checks but corrupt the model.

**C5 — Dispatch reviewer agent pre-delivery** (`deneb-visuals` step 3b, `python-visuals` step 2b, `svg-visuals` step 1b)
> *"Before presenting the spec to the user, dispatch the `deneb-reviewer` agent to validate syntax and provide design feedback."*

**Architectural pattern: generation and validation are separated into different agents.** This is why System D is recommended.

---

### Group D — Orphan detection and cross-reference checking

**D1 — Orphan reference detection in TMDL** (`standardize-naming-conventions`, Phase 5)
```bash
rg -n "old_name_pattern" <path>/definition/
```
> *"No orphaned references to old names remain in any file."*

Solves: renamed objects leaving broken references in DAX expressions across files.

**D2 — Cross-file reference updates are critical** (`standardize-naming-conventions`, Phase 4)
> *"Cross-file reference updates are critical. When renaming a measure or column, search the entire `definition/` directory for all references."*

**D3 — Rename cascade verification** (`pbip`, Verification section)
```bash
grep -r "Old Name" "Project.Report/" "Project.SemanticModel/" --include="*.json" --include="*.tmdl"
grep -rP "\bOld Name\b" ...
grep -r "'Old Name'" --include="*.tmdl" --include="*.dax"
```
Common missed locations: SparklineData metadata, Conditional formatting expressions, Filter config, Sort definitions, DAX queries in Report folder, Culture file linguisticMetadata.

**D4 — Unused object detection in BPA** (`bpa-rules`, Expression Syntax)
```csharp
// Orphan check:
IsHidden and ReferencedBy.Count = 0 and not UsedInRelationships.Any()
```
Solves: objects that are defined but never actually consumed.

**D5 — DependsOn/ReferencedBy tracking** (`bpa-rules`, Common Properties)
> `DependsOn.Any()`, `ReferencedBy.Count = 0` — properties available on Measure/Column objects.

Solves: identifying exactly which objects a measure depends on — the inverse of "does this reference exist."

---

### Group E — "Do not assume" and explicit no-assumption rules

**E1 — TMDL has no validation** (`tmdl`, Critical box)
> *"Direct TMDL editing does not validate DAX syntax, check referential integrity, or verify that property values are valid. Errors will only surface when the model is next loaded in Power BI Desktop."*

Names the gap this agent's System B/C has: generating content without a validation harness.

**E2 — DON'T MAKE ASSUMPTIONS** (`pbir-format`, General critical guidance)
> *"DON'T MAKE ASSUMPTIONS: Check the Microsoft documentation and other reputable resources for context if needed, or ask the user."*

**E3 — TOM is preferred because it validates atomically** (`connect-pbid`, When to Use)
> *"TOM validates changes against the engine and applies them atomically."*

Tool-mediated changes are preferred over text-based changes precisely because the tool enforces semantic validity.

**E4 — Fully qualify all column references** (`connect-pbid`, DAX Rules)
> *"Always fully qualify column references with single-quoted table names: `'Sales'[Amount]`, not `[Amount]`. Unqualified columns cause ambiguity errors."*

---

### Group F — Scope awareness and type-correctness checks

**F1 — Correct scope names in BPA** (`bpa-rules`, Correct Scope Names)
> `Role` → `ModelRole`, `Expression` → `NamedExpression`, etc.

Solves: BPA rules that silently apply to the wrong object type.

**F2 — summarizeBy semantic rules** (`tmdl`, Common Data Quality Patterns)
> Keys, attributes, dates, boolean flags → `summarizeBy: none`. Additive numeric facts → `sum`. Non-additive → `none`.

This is a domain-semantic validation rule: not just "is this valid syntax" but "does this value make sense given the column's role."

**F3 — CompatibilityLevel gating in BPA** (`bpa-rules`, Compatibility Levels)
> Rules only apply if `model.Database.CompatibilityLevel >= rule's level`.

Solves: generating code that references features unavailable in the target model version.

---

## Part 2: Pattern-to-Architecture Mapping

| Pattern | System A | System B | System C | System D |
|---|---|---|---|---|
| A1/A4: Read model → complete inventory | **Upgrade** | | | |
| A5/B3: Model fields gate | | **Add to prompt** | | |
| B1/B2: Existence check before reference | | **Add to prompt** | **Add as check** | |
| C2: Valid syntax ≠ valid semantics | | | **Core gap to fix** | |
| C3: TOM-style validation | | | **Extend checks** | |
| C5: Separate reviewer agent | | | | **New agent** |
| D1/D2/D3: Orphan detection | | | **Add cross-ref scan** | |
| D4/D5: ReferencedBy/DependsOn | | | **Add dep check** | |
| E1: Explicit no-validation warning | Inform B | | | |
| E2: DON'T MAKE ASSUMPTIONS | | **Add to prompt** | | |
| E4: Fully qualify references | | **Add to prompt** | **Validate** | |
| F2: Semantic type rules | Capture in output | **Constrain** | **Check** | |

---

## Part 3: Implementation

### System A — Upgraded Output Contract

Add `build_model_registry()` to `model_inspector.py`. This function must return a dict matching this schema exactly. System B and C consume it at runtime.

```python
def build_model_registry(self) -> dict:
    """
    Returns a structured registry of all model objects for use by System B
    (as a generation constraint) and System C (as a validation lookup).
    """
    return {
        "compatibility_level": self._get_compat_level(),   # e.g. 1702
        "storage_mode": self._get_storage_mode(),          # "Import" | "DirectQuery" | "Direct Lake" | "Mixed"
        "has_calculation_groups": self._has_calc_groups(),  # bool
        "tables": [t["name"] for t in self.tables],
        "columns": {
            table["name"]: [
                {
                    "ref": f"{table['name']}[{col['name']}]",
                    "dataType": col.get("dataType", "unknown"),
                    "summarizeBy": col.get("summarizeBy", "default"),
                    "isKey": col.get("isKey", False)
                }
                for col in table.get("columns", [])
            ]
            for table in self.tables
        },
        "measures": [
            {
                "ref": f"[{m['name']}]",
                "table": m["table"],
                "expression_preview": m["expression"][:80] if m.get("expression") else ""
            }
            for m in self.all_measures
        ],
        "relationships": [
            {
                "from": rel["fromColumn"],   # "Sales[CustomerKey]"
                "to": rel["toColumn"],        # "Customer[CustomerKey]"
                "active": rel.get("isActive", True)
            }
            for rel in self.relationships
        ]
    }
```

**JSON output example (paste this format into System B's prompt at runtime):**
```json
{
  "compatibility_level": 1702,
  "storage_mode": "Import",
  "has_calculation_groups": false,
  "tables": ["Sales", "Date", "Product", "Customer", "_Measures"],
  "columns": {
    "Sales": [
      {"ref": "Sales[Amount]",      "dataType": "decimal",  "summarizeBy": "sum",  "isKey": false},
      {"ref": "Sales[CustomerKey]", "dataType": "int64",    "summarizeBy": "none", "isKey": false},
      {"ref": "Sales[OrderDate]",   "dataType": "dateTime", "summarizeBy": "none", "isKey": false}
    ],
    "Date": [
      {"ref": "Date[Date]",         "dataType": "dateTime", "summarizeBy": "none", "isKey": true},
      {"ref": "Date[Year]",         "dataType": "int64",    "summarizeBy": "none", "isKey": false},
      {"ref": "Date[MonthName]",    "dataType": "string",   "summarizeBy": "none", "isKey": false}
    ]
  },
  "measures": [
    {"ref": "[Total Revenue]",  "table": "_Measures", "expression_preview": "SUM(Sales[Amount])"},
    {"ref": "[Sales YTD]",      "table": "_Measures", "expression_preview": "CALCULATE([Total Revenue], DATESYTD('Date'[Date]))"}
  ],
  "relationships": [
    {"from": "Sales[CustomerKey]", "to": "Customer[CustomerKey]", "active": true},
    {"from": "Sales[OrderDate]",   "to": "Date[Date]",            "active": true}
  ]
}
```

---

### System B — Updated System Prompt Additions

Insert this block **before** any DAX generation instructions in `dax_agent.py`:

```
## Model Object Constraint (MANDATORY)

The Model Object Registry from System A is provided below. You are STRICTLY
CONSTRAINED to reference only tables, columns, and measures that appear in
that registry.

RULES:
1. Never invent, guess, or infer object names. If you need an object that
   is not in the registry, state the gap explicitly — do not generate a
   reference to it.

2. All column references MUST be fully qualified:
      CORRECT: 'Sales'[Amount]
      WRONG:   Sales[Amount]   or   [Amount]

3. Measure references are always unqualified bracket notation:
      CORRECT: [Total Revenue]
      WRONG:   'Sales'[Total Revenue]   or   Sales[Total Revenue]

4. Table names in DAX are always single-quoted:
      CORRECT: 'Sales'    WRONG: Sales

5. Do NOT aggregate (SUM, AVERAGE, MIN, MAX, COUNT) any column where the
   registry shows "summarizeBy": "none" unless there is an explicit,
   documented business reason. Key columns and attribute columns are never
   directly aggregated.

6. If the model compatibility_level is below 1702, do not use DAX UDFs.
   If has_calculation_groups is false, do not reference SELECTEDMEASURE().

7. Before writing any object reference, mentally check:
   "Is this exact string present in the model_registry?"
   If the answer is uncertain, do not write it.

MODEL OBJECT REGISTRY:
{model_registry_json}
```

**Runtime injection (in `dax_agent.py`):**
```python
import json

model_registry = model_inspector.build_model_registry()
system_prompt = SYSTEM_B_BASE_PROMPT.replace(
    "{model_registry_json}",
    json.dumps(model_registry, indent=2)
)
```

---

### System C — SemanticReferenceValidator (add to sanitiser.py)

```python
import re
from typing import Optional

class SemanticReferenceValidator:
    """
    Validates that all object references in a DAX expression exist in the
    model registry produced by System A.

    Implements the orphan-detection and cross-reference checking patterns
    from the power-bi-agentic-development skill files:
    - "Valid syntax does not guarantee rendering" (pbir-format)
    - TOM validation patterns (connect-pbid)
    - Orphan detection (standardize-naming-conventions)
    - summarizeBy semantic rules (tmdl)
    """

    def __init__(self, model_registry: dict):
        self.registry = model_registry
        self._build_lookup_sets()

    def _build_lookup_sets(self):
        """Build O(1) lookup sets from the registry."""
        self.valid_columns: set[str] = set()
        for table, cols in self.registry.get("columns", {}).items():
            for col in cols:
                ref = col["ref"]  # e.g. "Sales[Amount]"
                self.valid_columns.add(ref.lower())

        self.valid_tables: set[str] = {
            t.lower() for t in self.registry.get("tables", [])
        }

        self.valid_measures: set[str] = {
            m["ref"].strip("[]").lower()
            for m in self.registry.get("measures", [])
        }

        self.non_additive_columns: set[str] = set()
        for table, cols in self.registry.get("columns", {}).items():
            for col in cols:
                if col.get("summarizeBy") == "none":
                    self.non_additive_columns.add(col["ref"].lower())

    def validate(self, dax_expression: str) -> dict:
        """
        Returns:
        {
          "passed": bool,
          "errors": [str],    # blocking — object doesn't exist in model
          "warnings": [str]   # non-blocking — semantic concern
        }
        """
        errors = []
        warnings = []

        # 1. Validate 'Table'[Column] references
        col_pattern = re.compile(r"'([^']+)'\[([^\]]+)\]")
        for match in col_pattern.finditer(dax_expression):
            table_name = match.group(1)
            col_name = match.group(2)
            full_ref = f"{table_name}[{col_name}]".lower()

            if table_name.lower() not in self.valid_tables:
                errors.append(
                    f"UNKNOWN TABLE: '{table_name}' is not in the model. "
                    f"(from reference '{match.group(0)}')"
                )
            elif full_ref not in self.valid_columns:
                errors.append(
                    f"UNKNOWN COLUMN: [{col_name}] does not exist in table '{table_name}'. "
                    f"(from reference '{match.group(0)}')"
                )

            # Check aggregation of non-additive columns
            if full_ref in self.non_additive_columns:
                agg_pattern = re.compile(
                    r"\b(SUM|AVERAGE|AVG|MIN|MAX|COUNT|COUNTA|DISTINCTCOUNT)\s*\(\s*"
                    + re.escape(match.group(0)),
                    re.IGNORECASE
                )
                if agg_pattern.search(dax_expression):
                    warnings.append(
                        f"SEMANTIC WARNING: '{match.group(0)}' has summarizeBy=none "
                        f"(key/attribute column) but is being directly aggregated. "
                        f"This is almost certainly incorrect."
                    )

        # 2. Validate [Measure] references (unqualified, not preceded by quote)
        measure_pattern = re.compile(r"(?<!')\[([^\]]+)\]")
        for match in measure_pattern.finditer(dax_expression):
            start = match.start()
            if start > 0 and dax_expression[start - 1] == "'":
                continue  # already caught as column ref above
            measure_name = match.group(1).lower()
            if measure_name not in self.valid_measures:
                errors.append(
                    f"UNKNOWN MEASURE: [{match.group(1)}] is not in the model. "
                    f"Check for typos or ask System A to re-read the model."
                )

        # 3. Compatibility level checks
        compat = self.registry.get("compatibility_level", 0)
        if compat < 1702:
            udf_pattern = re.compile(r"\b\w+\.\w+\s*\(", re.IGNORECASE)
            if udf_pattern.search(dax_expression):
                warnings.append(
                    f"COMPATIBILITY: Model is at level {compat}. DAX UDFs "
                    f"(function.name()) require level 1702+."
                )

        if not self.registry.get("has_calculation_groups", False):
            if re.search(r"\bSELECTEDMEASURE\s*\(", dax_expression, re.IGNORECASE):
                errors.append(
                    "SEMANTIC ERROR: SELECTEDMEASURE() referenced but model has no "
                    "calculation groups (has_calculation_groups=false in registry)."
                )

        return {
            "passed": len(errors) == 0,
            "errors": errors,
            "warnings": warnings
        }


def validate_generated_dax(
    dax_expression: str,
    model_registry: dict,
    existing_measure_names: Optional[list[str]] = None
) -> dict:
    """
    Top-level validation function combining semantic reference resolution
    with amendment protection.

    existing_measure_names: names of measures already saved in the model/library,
    used to detect silent overwrites.
    """
    validator = SemanticReferenceValidator(model_registry)
    result = validator.validate(dax_expression)

    # Amendment protection: name collision detection
    if existing_measure_names:
        for existing in existing_measure_names:
            # Check if the generated expression is trying to define a measure
            # with the same name as one that already exists
            name_pattern = re.compile(
                r"^\s*" + re.escape(existing) + r"\s*=",
                re.IGNORECASE | re.MULTILINE
            )
            if name_pattern.search(dax_expression):
                result["warnings"].append(
                    f"AMENDMENT RISK: Expression references or redefines existing "
                    f"measure '{existing}'. Confirm this replacement is intentional."
                )

    return result
```

**Usage in pipeline:**
```python
# In dax_agent.py, after System B generates DAX:
from sanitiser import validate_generated_dax

validation = validate_generated_dax(
    dax_expression=generated_dax,
    model_registry=model_inspector.build_model_registry(),
    existing_measure_names=[m["name"] for m in measure_library.get_all()]
)

if not validation["passed"]:
    # Feed errors back to System B for correction (not to System C)
    correction_prompt = f"""
Your generated DAX has the following reference errors.
Correct ONLY these specific issues — do not change anything else.

Errors:
{chr(10).join(validation['errors'])}

Original expression:
{generated_dax}

Model Object Registry (ground truth):
{json.dumps(model_registry, indent=2)}
"""
    # Re-run System B with correction_prompt (cap at 2 retries)

if validation["warnings"]:
    # Surface to user but do not block
    pass
```

---

### System D — Reference Resolver Agent Specification

This agent is a separate Claude API call. It handles validation as a dedicated cognitive context, separate from generation. Pattern sourced from `deneb-reviewer` / `python-reviewer` / `svg-reviewer` in three separate skills.

**System prompt for System D:**
```
ROLE: You are a DAX reference validator. You do not generate DAX.
You only validate that a given DAX expression references objects that
exist in the provided model registry.

INPUTS:
- A DAX expression produced by System B
- The model_registry JSON from System A

TASK:
1. Extract every table reference: 'TableName' patterns
2. Extract every column reference: 'Table'[Column] patterns
3. Extract every measure reference: [MeasureName] patterns (not preceded by quote)
4. For each extracted reference, check it against model_registry
5. For each aggregation function (SUM/AVG/MIN/MAX/COUNT), check that the
   column being aggregated has summarizeBy != "none"

OUTPUT FORMAT (always structured JSON, never prose):
{
  "validation_passed": true | false,
  "blocking_errors": [
    "UNKNOWN TABLE: 'Saless' — did you mean 'Sales'?",
    "UNKNOWN COLUMN: 'Date'[MonthNum] — available Date columns: [Date, Year, MonthName, MonthNumber]"
  ],
  "semantic_warnings": [
    "Sales[CustomerKey] has summarizeBy=none but is wrapped in SUM()"
  ],
  "references_checked": {
    "tables": ["Sales", "Date"],
    "columns": ["Sales[Amount]", "Date[Date]"],
    "measures": ["Total Revenue"]
  }
}

CRITICAL RULES:
- If a reference is not in the registry, it is an error. No exceptions.
- Do not attempt to fix the DAX. Only report errors.
- Do not explain DAX semantics. Only validate references.
- If model_registry is missing or empty, return:
  {"validation_passed": false, "blocking_errors": ["Model registry not provided.
   Cannot validate references. Re-run System A."]}
```

---

## Part 4: Complete Pipeline Flow (Updated Architecture)

```
User request
    │
    ▼
System A
  ├── Read Model.bim
  ├── Build model_registry JSON (tables, columns with roles,
  │   measures, relationships, compat_level, has_calc_groups)
  └── Returns: human summary + structured model_registry dict
    │
    ▼
System B  ◄─── model_registry injected into system prompt
  ├── Generate DAX
  ├── Constrained to model_registry objects only
  └── Returns: dax_expression string
    │
    ▼
System D (new — optional but recommended)
  ├── Receives: dax_expression + model_registry
  ├── Validates all object references against registry
  └── Returns: {passed, errors, warnings}
    │                    │
    │ passed=true        │ passed=false
    │                    ▼
    │           Return errors to System B
    │           with targeted correction prompt
    │           (max 2 retries)
    ▼
System C
  ├── Existing structural checks (syntax, format)
  ├── NEW: SemanticReferenceValidator (sanitiser.py)
  │   └── Checks all references against model_registry
  ├── Amendment protection (existing measure collision)
  └── Returns: approved DAX or rejection with reasons
    │
    ▼
Output to user + save to measure_library.json
```

---

## Part 5: The Core Insight

The pattern running through all 14 skill files is a three-phase safety structure:

1. **Read the actual environment before generating** (not assuming)
2. **Generate constrained to only what was read**
3. **Validate the generated output against the environment before committing**

The current agent does step 1 and step 2, but they don't share state (System A's output is not injected as a hard constraint into System B). Step 3 only checks structure, not semantics.

The single highest-impact fix is to wire System A's model registry as a hard constraint into System B's system prompt, and add semantic reference resolution (checking all `'Table'[Column]` and `[Measure]` extractions against System A's object list) inside System C.

---

*To-do list with effort/improvement ratings and priority order: `TODO.md` (project root)*
