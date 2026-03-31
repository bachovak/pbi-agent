# PBI Agent — Development To-Do List

> Generated from analysis of the `data-goblin/power-bi-agentic-development` repository.
> Full analysis with patterns, code, and system prompt text: `docs/ANALYSIS-validation-patterns.md`

## Priority Key

| Symbol | Meaning |
|--------|---------|
| 🔴 HIGH | High effort / High improvement |
| 🟡 MED  | Medium effort or improvement |
| 🟢 LOW  | Low effort / Low improvement |

Tasks are sorted: **lowest effort + highest improvement first**.

---

## Tier 1 — Low Effort, High Improvement (do these first)

### ✅ T1-A · Add "reference constraint" rules to System B's system prompt *(done)*
- **Effort:** 🟢 LOW — edit a string constant in `dax_agent.py`
- **Improvement:** 🔴 HIGH — directly prevents System B from hallucinating object names
- **What to do:**
  - In `dax_agent.py`, add the Model Object Constraint block to the system prompt
  - Rules: only reference objects in the registry; fully qualify all column refs as `'Table'[Column]`; never aggregate columns where `summarizeBy=none`; do not use SELECTEDMEASURE() if model has no calculation groups
  - See `docs/ANALYSIS-validation-patterns.md` → "System B — Updated System Prompt Additions" for the exact text to paste in
- **Files:** `dax_agent.py`
- **Depends on:** T1-B (registry must exist to inject)

---

### ✅ T1-B · Wire System A's model registry into System B at runtime *(done)*
- **Effort:** 🟢 LOW — pass the registry dict into the system prompt at call time
- **Improvement:** 🔴 HIGH — makes the constraint in T1-A live and model-specific
- **What to do:**
  - At DAX generation time, serialise the model registry (from T2-A) to JSON and inject it into the System B system prompt using string formatting
  - See `docs/ANALYSIS-validation-patterns.md` → System B prompt block, `{model_registry_json}` placeholder
- **Files:** `dax_agent.py`, `app.py`
- **Depends on:** T2-A

---

### ✅ T1-C · Add "DON'T MAKE ASSUMPTIONS" + fully-qualified reference rules *(done)*
- **Effort:** 🟢 LOW — additional lines in the System B system prompt
- **Improvement:** 🟡 MED — reduces a class of subtle generation errors before validation is even needed
- **What to do:**
  - Add explicit rule: "If you are uncertain whether an object exists in the model, do not reference it — state the gap instead"
  - Add rule: all column refs must be `'Table'[Column]` never `[Column]` alone
  - Sourced from `pbir-format` SKILL.md ("DON'T MAKE ASSUMPTIONS") and `connect-pbid` SKILL.md ("Unqualified columns cause ambiguity errors")
- **Files:** `dax_agent.py`
- **Depends on:** nothing

---

### ✅ T1-D · Add column role metadata to the model registry output *(done)*
- **Effort:** 🟢 LOW — `model_inspector.py` already reads the BIM; add three fields per column
- **Improvement:** 🟡 MED — enables the semantic aggregation check in T2-B
- **What to do:**
  - For each column, emit: `dataType`, `summarizeBy`, `isKey` (bool)
  - `summarizeBy=none` flags keys, attributes, dates — columns that must never be directly aggregated
  - See `docs/ANALYSIS-validation-patterns.md` → System A registry format, `"columns"` array
- **Files:** `model_inspector.py`
- **Depends on:** nothing

---

### ✅ T1-E · Add compatibility level + calculation group presence to the registry *(done)*
- **Effort:** 🟢 LOW — read two fields already present in `Model.bim`
- **Improvement:** 🟡 MED — catches SELECTEDMEASURE() in non-calc-group models; gates DAX UDF usage
- **What to do:**
  - Emit `compatibility_level` (integer) and `has_calculation_groups` (bool) in the registry
  - In System B prompt: "If `has_calculation_groups=false`, do not use SELECTEDMEASURE(). If `compatibility_level < 1702`, do not use DAX UDFs."
  - Sourced from `bpa-rules` SKILL.md compatibility level gating
- **Files:** `model_inspector.py`, `dax_agent.py`
- **Depends on:** nothing

---

### ✅ T1-F · Add measure name collision detection to System C *(done)*
- **Effort:** 🟢 LOW — extend `sanitiser.py` with a name-collision check
- **Improvement:** 🟡 MED — prevents silent overwrites of existing measures with different semantics
- **What to do:**
  - Before accepting a generated measure, check if its name already exists in `measure_library.json`
  - If a collision is found, surface it as a warning (not a hard block): "Measure '[Name]' already exists. Confirm this is a replacement."
  - Sourced from `connect-pbid` SKILL.md "check for duplicate measure names across tables"
- **Files:** `sanitiser.py`
- **Depends on:** nothing

---

## Tier 2 — Medium Effort, High Improvement

### ✅ T2-A · Upgrade System A (model_inspector.py) to emit a structured model_registry JSON *(done)*
- **Effort:** 🟡 MED — refactor `model_inspector.py` output format
- **Improvement:** 🔴 HIGH — prerequisite for all Tier 1 runtime-injection tasks; makes the entire validation chain possible
- **What to do:**
  - Add a `build_model_registry()` function that returns a typed dict matching the schema in `docs/ANALYSIS-validation-patterns.md`
  - Output must include: `tables[]`, `columns{}` (per-table, with role metadata), `measures[]` (with table attribution), `relationships[]`, `compatibility_level`, `has_calculation_groups`
  - Expose this as a property on the existing model inspector class so `dax_agent.py` can call it without re-parsing
  - See `docs/ANALYSIS-validation-patterns.md` → "System A — Upgraded Output Contract" for the exact JSON schema
- **Files:** `model_inspector.py`
- **Depends on:** T1-D, T1-E

---

### ✅ T2-B · Add SemanticReferenceValidator to System C (sanitiser.py) *(done)*
- **Effort:** 🟡 MED — implement the reference resolver class (~120 lines of Python)
- **Improvement:** 🔴 HIGH — closes the core gap: catches references to tables/columns/measures that don't exist, even when DAX syntax is valid
- **What to do:**
  - Add `SemanticReferenceValidator` class to `sanitiser.py` (full implementation in `docs/ANALYSIS-validation-patterns.md`)
  - Run it as the final step of System C's validation pipeline, after existing structural checks
  - Returns `{"passed": bool, "errors": [...], "warnings": [...]}` — block on errors, surface warnings
  - Checks: `'Table'[Column]` existence, `[Measure]` existence, aggregation of `summarizeBy=none` columns, SELECTEDMEASURE without calc groups
- **Files:** `sanitiser.py`
- **Depends on:** T2-A

---

### ✅ T2-C · Add a B → D → B correction retry loop for reference errors *(done)*
- **Effort:** 🟡 MED — add retry logic and a correction prompt to the generation pipeline
- **Improvement:** 🟡 MED — auto-heals reference typos without user intervention; reduces round-trips
- **What to do:**
  - After System D (or the validator in T2-B) returns errors, feed them back to System B with a targeted correction prompt (not a full regeneration)
  - Prompt: "Your expression has these specific reference errors. Correct only these — do not change anything else: [error list]"
  - Cap at 2 correction iterations before surfacing to user
  - Sourced from `standardize-naming-conventions` SKILL.md audit-before-apply and correction patterns
- **Files:** `dax_agent.py`
- **Depends on:** T2-B

---

## Tier 2 (continued) — Discovered during testing

### T2-D · Detect and surface "polite refusal" responses from System B
- **Effort:** 🟢 LOW — add a detection step before structural validation
- **Improvement:** 🟡 MED — stops pointless retries and shows Claude's explanation to the user as actionable feedback
- **What to do:**
  - Before `validate_structural`, check if the response contains no `=` sign AND is longer than ~50 chars (heuristic for "explanation text, not DAX")
  - If detected, skip retries and surface the response directly as a "Model gap" message: "The requested columns/measures don't exist in this model. Claude's suggestion: ..."
  - This handles the case where the registry constraint works correctly (Claude refuses to hallucinate) but the pipeline treats the refusal as a failed DAX attempt and retries pointlessly
- **Files:** `dax_agent.py`, `app.py`
- **Depends on:** nothing (standalone check)

---

## Tier 3 — Medium/High Effort, Medium Improvement

### T3-A · Add relationship-awareness to the registry and System B prompts
- **Effort:** 🟡 MED — parse relationships from BIM and include in registry
- **Improvement:** 🟡 MED — System B can avoid generating CALCULATE filters across inactive or missing relationships
- **What to do:**
  - Emit `relationships[]` with `from`, `to`, `active` fields in the registry
  - Add to System B prompt: "Do not filter across relationships that are marked `active=false` without wrapping in USERELATIONSHIP()"
  - Sourced from `connect-pbid` SKILL.md relationship validation checks
- **Files:** `model_inspector.py`, `dax_agent.py`
- **Depends on:** T2-A

---

### T3-B · Create System D as a standalone validation agent (separate Claude call)
- **Effort:** 🔴 HIGH — new agent, new API call, integration with the pipeline
- **Improvement:** 🔴 HIGH — separates generation and validation into different cognitive contexts; catches a different class of errors than the code-based validator in T2-B
- **What to do:**
  - Create a new `reference_resolver_agent.py` that makes a separate Claude API call using only the System D system prompt (see `docs/ANALYSIS-validation-patterns.md`)
  - Input: generated DAX + model registry. Output: structured validation JSON
  - Use this in addition to (not instead of) the code-based T2-B validator — they catch different things
  - Sourced from the `deneb-reviewer` / `python-reviewer` / `svg-reviewer` agent pattern found in three separate skills
- **Files:** `reference_resolver_agent.py` (new), `dax_agent.py`
- **Depends on:** T2-A, T2-B

---

### T3-C · Add DependsOn / measure dependency tracking to the registry
- **Effort:** 🔴 HIGH — requires parsing DAX expressions to extract `[MeasureRef]` chains
- **Improvement:** 🟡 MED — enables impact analysis: "if I change [Base Measure], which other measures break?"
- **What to do:**
  - For each measure in the model, parse its expression to extract referenced measures and columns
  - Build a dependency graph (already partially done in `lineage.py` — review and extend)
  - Add `"depends_on": ["[Total Revenue]", "Date[Date]"]` per measure in the registry
  - Surface in System C: warn if a generated measure references a measure whose own expression has errors
  - Sourced from `bpa-rules` SKILL.md `DependsOn.Any()` and `ReferencedBy.Count` patterns
- **Files:** `lineage.py`, `model_inspector.py`, `sanitiser.py`
- **Depends on:** T2-A

---

## Quick Reference: Sort Order Rationale

| Task | Effort | Improvement | Priority |
|------|--------|-------------|----------|
| T1-C · "DON'T MAKE ASSUMPTIONS" prompt rules | LOW | MED | 1 |
| T1-D · Column role metadata (summarizeBy, isKey) | LOW | MED | 2 |
| T1-E · Compat level + calc groups in registry | LOW | MED | 3 |
| T1-F · Measure name collision detection | LOW | MED | 4 |
| T2-A · Upgrade model_inspector → model_registry | MED | HIGH | 5 ← unblocks T1-A/B |
| T1-A · Reference constraint in System B prompt | LOW | HIGH | 6 ← needs T2-A |
| T1-B · Wire registry into System B at runtime | LOW | HIGH | 7 ← needs T2-A |
| T2-B · SemanticReferenceValidator in sanitiser.py | MED | HIGH | 8 |
| T2-C · B→D→B correction retry loop | MED | MED | 9 |
| T3-A · Relationship awareness in prompts | MED | MED | 10 |
| T3-B · System D standalone validator agent | HIGH | HIGH | 11 |
| T3-C · DependsOn / dependency graph | HIGH | MED | 12 |

---

*Full implementation details, code, and system prompt text: `docs/ANALYSIS-validation-patterns.md`*
