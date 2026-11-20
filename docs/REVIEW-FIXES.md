# Independent review fixes — milestone 6

Reference: `m6.md` (review dated 2026-11-20). Every item below got a failing
regression test first (hand-derived expected value), then a root-cause fix.
Full suite: `529 passed`, coverage `97.34%`; `mypy`, `ruff check`, `ruff format --check` clean.

| Item | Regression test (`tests/test_review_fixes.py` unless noted) | Fix summary | Status |
|---|---|---|---|
| C1 — incomplete 9900 / wrong 9990 | `test_writer_9900_includes_9900_9990_9999_and_correct_9990`, `test_fix_totals_cli_writes_complete_block_9`, `test_9900_count_for_9900_is_the_number_of_9900_lines` | `core/writer.py` now counts `9900`, `9990` and `9999` as first-class registers; emits one `9900` line per distinct register (including itself, 9990 and 9999); `9990.QTD_LIN_9` = 9900 lines + 9001 + 9990 + 9999 (Guia Prático 3.2.4, bloco 9). `sped fix-totals` inherits the fix via the shared writer. | Fixed |
| C2 — implied decimals | `test_integer_body_has_no_implied_decimals`, `test_no_false_c190_error_for_integer_and_comma_spellings` | Removed `scaleb(-dec)` from `FieldDef.coerce`; an integer body is its literal value (`10000` → `10000.00`). `analysis/apuracao._format_raw` now writes a comma separator instead of shifting the decimal point. Corrected bug-locking assertions in `test_types.py`, `test_reader.py`, `test_hierarchy.py`, `test_hardening.py`, `test_analysis.py`. | Fixed |
| H1 — x990/9990/9900 counts ignored | `test_wrong_x990_and_9990_counts_are_reported`, `test_missing_9900_line_for_a_present_register_is_reported` | `StructureChecks` validates every `x990.QTD_LIN_n` while streaming, checks `9990.QTD_LIN_9` against the real block-9 line count, verifies each `9900` count and reports missing/duplicate `9900` lines. New rules `SPED-STRUCT-X990-001` and `SPED-9990`; new broken fixtures and `CASES` entries. | Fixed |
| H2 — no CNPJ/CPF check digits | `test_cnpj_cpf_check_digits_hand_table`, `test_invalid_cnpj_in_0000_is_reported`, `test_factory_cnpj_cpf_fixtures_are_officially_valid` | Added official módulo-11 `valid_cnpj`/`valid_cpf` to `validation/tables.py`; `TableChecks` validates fields whose official size is 14/11 and whose name identifies a CNPJ/CPF, using rule `SPED-TAB-CNPJ-001`. Synthetic fixtures use valid documents. | Fixed |
| H3 — CFOP vs IND_OPER | `test_cfop_entrada_with_saida_operation_is_reported` | `TableChecks._check_direction` compares the first CFOP digit (1/2/3 = entrada, 5/6/7 = saída per Guia Prático) with the parent document's `IND_OPER`; new rule `SPED-TAB-CFOP-002`. | Fixed |
| H4 — hierarchy not enforced | `test_c170_without_c100_parent_is_reported` | `HierarchyChecks` walks the level stack in one pass and requires a data (non-structural) ancestor for level-3+ details, plus explicit official parent relations (C170/C190→C100, D190→D100, E110→E100, I155→I150, I150→I010/I050, M210→M200, M610→M600). New rule `SPED-STRUCT-HIER-001` and `orphan_c170` fixture. | Fixed |
| H5 — validation not streaming | `test_validation_memory_is_flat_on_a_100k_line_file` | `ValidationContext` keeps only counters, last-record-per-code and control records; `engine.validate` consumes a single reader iterator and dispatches to per-record accumulators (`checks.py`, `totals.py`). `parent()` is now an O(1) dictionary lookup instead of a backwards scan. Peak for 100k records: well under 32 MB (was ~718 MB). | Fixed |
| M1 — dot separator accepted | `test_dot_decimal_separator_is_rejected` | `FieldDef.coerce` leaves dotted bodies raw; `reader.validate_field` rejects `.` in all numeric fields and commas in integer fields. Only the official comma decimal separator is accepted. | Fixed |
| M2 — pipe inside value | `test_writer_rejects_pipe_inside_value` | `format_line` rejects `|` in register codes and values, preventing silently mis-framed records. | Fixed |
| M3 — 9900 sorted by code | `test_9900_follows_first_appearance_order` | `_TotalsWriter` records codes in insertion (first-appearance) order and emits `9900` lines in that order. | Fixed |
| mypy — `pdfplumber` missing in lint job | `python -m mypy --no-site-packages scripts/generate_layouts.py` (build check) | Optional dependency loaded lazily with `importlib.import_module` inside `parse_pdf`; no top-level import for mypy to resolve. | Fixed |

Notes:

* No snapshot files tracked in this repository locked in the listed bugs; none needed regeneration.
* New rule IDs were added to `CASES` in `tests/test_validation_rules.py` so every rule still has a broken and a valid fixture.
* `late_participant` fixture now regenerates its structural records after moving a line, so it isolates the ordering warning as intended.
