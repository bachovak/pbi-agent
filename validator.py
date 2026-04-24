"""
validator.py — DAX output validation module
Validates generated DAX expressions before they are accepted into the pipeline.

Responsibilities:
  - DAX type-name pre-check (T1-G): catch incorrect Power BI type names before
    semantic validation runs and feed them into the retry loop
  - SemanticReferenceValidator (T2-B): validate all object references against
    the model registry produced by model_inspector.build_model_registry()

Intentionally separate from sanitiser.py, which handles only PII redaction of
model.bim content before it is shared with the AI.
"""

import re


# ── Type-name pre-check (T1-G) ────────────────────────────────────────────────

# Correct Power BI DAX type names: Int64, Decimal, Double, String, DateTime,
# Boolean, Numeric, Variant. Maps common wrong names Claude emits (from general
# training on SQL/Python) to the correct Power BI equivalent.
# Only checked inside AS/RETURNS clauses where type names legitimately appear.
_WRONG_TYPE_MAP = {
    "integer":  "Int64",
    "float":    "Double",
    "text":     "String",
    "date":     "DateTime",
    "bool":     "Boolean",
    "number":   "Numeric",
    "any":      "Variant",
}

_TYPE_CONTEXT_RE = re.compile(r"\b(AS|RETURNS)\s+(\w+)", re.IGNORECASE)


def check_dax_type_names(dax_expression: str) -> list:
    """
    Scan a DAX expression for incorrect Power BI type names in UDF AS/RETURNS
    clauses. Returns structured error strings suitable for the retry loop.
    Each unique wrong type is reported once.
    """
    errors = []
    seen: set = set()
    for match in _TYPE_CONTEXT_RE.finditer(dax_expression):
        type_name = match.group(2)
        correct = _WRONG_TYPE_MAP.get(type_name.lower())
        if correct and type_name.lower() not in seen:
            errors.append(
                f"WRONG TYPE NAME: '{type_name}' is not a valid Power BI DAX type. "
                f"Use '{correct}' instead (found in '{match.group(0)}')."
            )
            seen.add(type_name.lower())
    return errors


# ── Semantic Reference Validator (T2-B) ───────────────────────────────────────
# Validates that every object reference in a generated DAX expression exists in
# the model registry produced by model_inspector.build_model_registry().
#
# Implements the cross-reference and semantic validation patterns identified in
# the analysis of data-goblin/power-bi-agentic-development (GPL v3) —
# patterns C2 (valid syntax ≠ valid semantics), D1–D3 (orphan detection),
# F2 (summarizeBy semantic rules), F3 (compat level gating).
# Implementation here is original code.


class SemanticReferenceValidator:
    """
    Validates that all object references in a DAX expression exist in the model
    registry produced by System A (build_model_registry()).

    Catches:
      - Incorrect Power BI type names in UDF definitions (T1-G pre-check)
      - References to tables that don't exist in the model
      - References to columns that don't exist in those tables
      - References to measures that don't exist in the model
      - Direct aggregation of summarizeBy=none columns (semantic warning)
      - SELECTEDMEASURE() when model has no calculation groups
      - DAX UDFs when model compatibility level < 1702
    """

    def __init__(self, model_registry: dict):
        self.registry = model_registry
        self._build_lookup_sets()

    def _build_lookup_sets(self):
        """Build O(1) lookup sets from the registry."""
        self.valid_columns: set = set()
        for table, cols in self.registry.get("columns", {}).items():
            for col in cols:
                ref = col["ref"]  # e.g. "Sales[Amount]"
                self.valid_columns.add(ref.lower())

        self.valid_tables: set = {
            t.lower() for t in self.registry.get("tables", [])
        }

        self.valid_measures: set = {
            m["ref"].strip("[]").lower()
            for m in self.registry.get("measures", [])
        }

        self.non_additive_columns: set = set()
        for table, cols in self.registry.get("columns", {}).items():
            for col in cols:
                if col.get("summarizeBy") == "none" or col.get("isKey"):
                    self.non_additive_columns.add(col["ref"].lower())

    def validate(self, dax_expression: str) -> dict:
        """
        Validate all object references in a DAX expression.

        Returns:
            {
              "passed":   bool,
              "errors":   [str],   # blocking — object doesn't exist in model
              "warnings": [str]    # non-blocking — semantic concern
            }
        """
        # Type-name pre-check — runs before any registry lookup so that
        # wrong type names are caught and corrected first
        type_errors = check_dax_type_names(dax_expression)
        if type_errors:
            return {"passed": False, "errors": type_errors, "warnings": []}

        errors = []
        warnings = []

        # Strip DAX line and block comments before pattern matching to avoid
        # false positives from Claude echoing registry tags (e.g. [no-aggregate])
        # inside comments. All patterns run against the comment-free copy.
        dax_clean = re.sub(r"//[^\n]*", "", dax_expression)
        dax_clean = re.sub(r"/\*.*?\*/", "", dax_clean, flags=re.DOTALL)

        # UDF detection — if this is a UDF definition, skip all object reference
        # checks (steps 1–3). UDF parameter names are not model objects and must
        # not be validated against the registry. Fall through to compat checks only.
        is_udf = bool(re.search(r"\bFUNCTION\b", dax_clean, re.IGNORECASE)) and "=>" in dax_clean
        if is_udf:
            compat = self.registry.get("compatibility_level", 0)
            if compat > 0 and compat < 1702:
                warnings.append(
                    f"COMPATIBILITY: Model is at level {compat}. DAX UDFs "
                    f"require compatibility level 1702+."
                )
            return {"passed": len(errors) == 0, "errors": errors, "warnings": warnings}

        # Track which non-additive refs have already generated a warning to
        # avoid duplicate entries when the same column appears multiple times.
        warned_agg_refs: set = set()

        # 1. Validate 'Table'[Column] references (correct fully-qualified form)
        quoted_col_pattern = re.compile(r"'([^']+)'\[([^\]]+)\]")
        for match in quoted_col_pattern.finditer(dax_clean):
            table_name = match.group(1)
            col_name = match.group(2)
            full_ref = f"{table_name}[{col_name}]".lower()

            if table_name.lower() not in self.valid_tables:
                errors.append(
                    f"UNKNOWN TABLE: '{table_name}' is not in the model "
                    f"(from '{match.group(0)}')"
                )
            elif full_ref not in self.valid_columns:
                errors.append(
                    f"UNKNOWN COLUMN: [{col_name}] does not exist in "
                    f"table '{table_name}' (from '{match.group(0)}')"
                )

            # Check for direct aggregation of non-additive / key columns.
            if full_ref in self.non_additive_columns and full_ref not in warned_agg_refs:
                agg_pattern = re.compile(
                    r"\b(SUM|AVERAGE|AVG|MIN|MAX|COUNT|COUNTA|DISTINCTCOUNT)\s*\(\s*"
                    + re.escape(match.group(0)),
                    re.IGNORECASE
                )
                if agg_pattern.search(dax_clean):
                    warnings.append(
                        f"SEMANTIC WARNING: '{match.group(0)}' is a key/attribute "
                        f"column (summarizeBy=none) but is being directly aggregated. "
                        f"This is almost certainly incorrect."
                    )
                    warned_agg_refs.add(full_ref)

        # 2. Also catch unquoted Table[Column] references — format violation
        #    that may still contain wrong names.
        unquoted_col_pattern = re.compile(r"(?<!')\b([A-Za-z][A-Za-z0-9 _$]*)\[([^\]]+)\]")
        for match in unquoted_col_pattern.finditer(dax_clean):
            table_name = match.group(1).strip()
            col_name = match.group(2).strip()
            if table_name.lower() in self.valid_tables:
                full_ref = f"{table_name}[{col_name}]".lower()
                if full_ref not in self.valid_columns:
                    errors.append(
                        f"UNKNOWN COLUMN: [{col_name}] does not exist in "
                        f"table '{table_name}' (from '{match.group(0)}'). "
                        f"Also: use quoted form 'TableName'[ColumnName]."
                    )
                else:
                    warnings.append(
                        f"FORMAT: Use single-quoted table name: "
                        f"'{table_name}'[{col_name}] not {table_name}[{col_name}]"
                    )

        # 3. Validate [Measure] references (unqualified bracket notation).
        #    Skip anything whose '[' is immediately preceded by a single quote —
        #    those are column refs already handled above.
        measure_pattern = re.compile(r"\[([^\]]+)\]")
        for match in measure_pattern.finditer(dax_clean):
            start = match.start()
            if start > 0 and dax_clean[start - 1] == "'":
                continue  # column ref, already validated above
            measure_name = match.group(1)
            if measure_name.lower() not in self.valid_measures:
                errors.append(
                    f"UNKNOWN MEASURE: [{measure_name}] is not in the model. "
                    f"Check for typos or confirm it is defined elsewhere."
                )

        # 4. Compatibility level gating
        compat = self.registry.get("compatibility_level", 0)
        if compat > 0 and compat < 1702:
            udf_pattern = re.compile(r"\b\w+\.\w+\s*\(", re.IGNORECASE)
            if udf_pattern.search(dax_clean):
                warnings.append(
                    f"COMPATIBILITY: Model is at level {compat}. DAX UDFs "
                    f"(e.g. MyLib.Function()) require compatibility level 1702+."
                )

        if not self.registry.get("has_calculation_groups", False):
            if re.search(r"\bSELECTEDMEASURE\s*\(", dax_clean, re.IGNORECASE):
                errors.append(
                    "SEMANTIC ERROR: SELECTEDMEASURE() referenced but model has no "
                    "calculation groups (has_calculation_groups=False in registry)."
                )

        return {
            "passed": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }


def validate_generated_dax(
    dax_expression: str,
    model_registry: dict,
    existing_measure_names=None,
) -> dict:
    """
    Top-level validation combining semantic reference resolution with amendment
    protection. Suitable for calling directly from the generation pipeline.

    existing_measure_names: list of measure names already in the library,
    used to warn about silent overwrites (non-blocking).
    """
    validator = SemanticReferenceValidator(model_registry)
    result = validator.validate(dax_expression)

    if existing_measure_names:
        import re as _re
        for existing in existing_measure_names:
            name_pattern = _re.compile(
                r"^\s*" + _re.escape(existing) + r"\s*=",
                _re.IGNORECASE | _re.MULTILINE,
            )
            if name_pattern.search(dax_expression):
                result["warnings"].append(
                    f"AMENDMENT RISK: Expression redefines existing measure "
                    f"'{existing}'. Confirm this replacement is intentional."
                )

    return result
