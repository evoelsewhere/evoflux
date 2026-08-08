"""Structural fallback parser (parsers/structural.py) — config-driven regex
extraction for legacy languages without tree-sitter grammars.

The COBOL/JCL/VB6 cases use test-owned configs. Production stack extractors are
project artifacts under ``<kb>/rulebook/``; EvoFlux ships no language catalog.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.code_index.parsers.registry import build_registry
from app.services.code_index.parsers.structural import (
    StructuralConfig,
    StructuralParser,
    load_structural_parsers,
)
from app.services.code_index.graph_types import (
    EDGE_CALLS,
    EDGE_CONTAINS,
    EDGE_IMPORTS,
    EDGE_REFERENCES,
)

COBOL_CONFIG = StructuralConfig.model_validate(
    {
        "id": "cobol-structural",
        "file_extensions": [".cbl", ".cob", ".cpy"],
        "ignore_case": True,
        "node_rules": [
            {
                "kind": "program",
                "scope": "file",
                "match": r"PROGRAM-ID\s*\.?\s+(?P<name>[A-Za-z0-9][A-Za-z0-9-]*)",
            },
            {
                "kind": "division",
                "scope": "block",
                "match": r"^[\s0-9]{0,7}(?P<name>IDENTIFICATION|ENVIRONMENT|DATA|PROCEDURE)\s+DIVISION\b",
            },
            {
                "kind": "section",
                "scope": "block",
                "match": r"^[\s0-9]{0,7}(?P<name>[A-Za-z][A-Za-z0-9-]*)\s+SECTION\s*\.",
            },
            {
                "kind": "paragraph",
                "scope": "block",
                "match": r"^[\s0-9]{0,7}(?P<name>[A-Za-z][A-Za-z0-9-]*)\s*\.\s*$",
            },
        ],
        "edge_rules": [
            {
                "kind": "calls",
                "from": "paragraph",
                "match": r"\bPERFORM\s+(?P<target>[A-Za-z][A-Za-z0-9-]*)",
            },
            {
                "kind": "calls",
                "from": "paragraph",
                "match": r"\bCALL\s+['\"](?P<target>[A-Za-z0-9-]+)['\"]",
            },
            {
                "kind": "imports",
                "from": "section",
                "match": r"\bCOPY\s+(?P<target>[A-Za-z0-9][A-Za-z0-9-]*)",
            },
            {
                "kind": "imports",
                "from": "paragraph",
                "match": r"EXEC\s+SQL\s+INCLUDE\s+(?P<target>[A-Za-z0-9-]+)",
            },
        ],
        "keyword_denylist": ["UNTIL", "VARYING", "TIMES"],
    }
)

JCL_CONFIG = StructuralConfig.model_validate(
    {
        "id": "jcl-structural",
        "file_extensions": [".jcl", ".proc"],
        "ignore_case": True,
        "node_rules": [
            {
                "kind": "job",
                "scope": "file",
                "match": r"^//(?P<name>[A-Z0-9@#$]+)\s+JOB\b",
            },
            {
                "kind": "step",
                "scope": "block",
                "match": r"^//(?P<name>[A-Z0-9@#$]+)\s+EXEC\b",
            },
        ],
        "edge_rules": [
            {
                "kind": "calls",
                "from": "step",
                "match": r"\bPGM=(?P<target>[A-Z0-9@#$]+)",
            },
            {
                "kind": "imports",
                "from": "step",
                "match": r"\bPROC=(?P<target>[A-Z0-9@#$]+)",
            },
            {
                "kind": "imports",
                "from": "step",
                "match": r"\bEXEC\s+(?P<target>[A-Z0-9@#$]+)(?![=A-Z0-9@#$])",
            },
            {
                "kind": "references",
                "from": "step",
                "match": r"\bDSN=(?P<target>[A-Z0-9.@#$&+-]+)",
            },
        ],
        "keyword_denylist": ["PGM", "PROC"],
    }
)

VB6_CONFIG = StructuralConfig.model_validate(
    {
        "id": "vb6-structural",
        "file_extensions": [".bas", ".cls", ".frm"],
        "ignore_case": True,
        "node_rules": [
            {
                "kind": "module",
                "scope": "file",
                "match": r'^Attribute\s+VB_Name\s*=\s*"(?P<name>[^"]+)"',
            },
            {
                "kind": "procedure",
                "scope": "block",
                "match": r"^\s*(?:Public|Private|Friend|Static)?\s*(?:Sub|Function|Property\s+(?:Get|Let|Set))\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)",
                "end_match": r"^\s*End\s+(?:Sub|Function|Property)\b",
            },
        ],
        "edge_rules": [
            {
                "kind": "calls",
                "from": "procedure",
                "match": r"^\s*(?:Call\s+)?(?P<target>[A-Za-z_][A-Za-z0-9_]*)\s*(?:\(|$)",
            },
            {
                "kind": "calls",
                "from": "procedure",
                "match": r"=\s*(?P<target>[A-Za-z_][A-Za-z0-9_]*)\s*\(",
            },
            {
                "kind": "references",
                "from": "procedure",
                "match": r"\bOn\s+Error\s+GoTo\s+(?P<target>[A-Za-z_][A-Za-z0-9_]*)",
            },
            {
                "kind": "references",
                "from": "procedure",
                "match": r"\b(?P<object>[A-Za-z_][A-Za-z0-9_]*)\.",
                "target_group": "object",
            },
        ],
        "keyword_denylist": ["IF", "MSGBOX", "ERR"],
    }
)


def _names(nodes, kind):
    return [n.name for n in nodes if n.kind == kind]


def _edge_targets(edges, kind):
    return [e.dst_name for e in edges if e.kind == kind and e.dst_name]


# ── COBOL ─────────────────────────────────────────────────────────────────────

COBOL_SOURCE = b"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PAYROLL01.
       ENVIRONMENT DIVISION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-TOTAL PIC 9(7)V99.
           COPY PAYCOPY.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM INIT-PARA.
           PERFORM CALC-PARA UNTIL WS-DONE = 'Y'.
           CALL 'TAXCALC' USING WS-TOTAL.
           STOP RUN.
       INIT-PARA.
           MOVE ZERO TO WS-TOTAL.
       CALC-PARA.
           ADD 1 TO WS-TOTAL.
           EXEC SQL INCLUDE SQLCA END-EXEC.
"""


def test_cobol_config_extracts_program_and_paragraphs():
    parser = StructuralParser(COBOL_CONFIG)
    result = parser.parse(file_path="payroll01.cbl", source=COBOL_SOURCE)

    assert _names(result.nodes, "program") == ["PAYROLL01"]
    assert set(_names(result.nodes, "division")) == {
        "IDENTIFICATION",
        "ENVIRONMENT",
        "DATA",
        "PROCEDURE",
    }
    assert "WORKING-STORAGE" in _names(result.nodes, "section")
    paragraphs = _names(result.nodes, "paragraph")
    assert {"MAIN-PARA", "INIT-PARA", "CALC-PARA"} <= set(paragraphs)


def test_cobol_config_extracts_perform_call_copy_edges():
    parser = StructuralParser(COBOL_CONFIG)
    result = parser.parse(file_path="payroll01.cbl", source=COBOL_SOURCE)

    calls = _edge_targets(result.edges, EDGE_CALLS)
    assert "INIT-PARA" in calls
    assert "CALC-PARA" in calls
    assert "TAXCALC" in calls
    # PERFORM ... UNTIL must not emit an edge to the keyword UNTIL.
    assert "UNTIL" not in calls

    imports = _edge_targets(result.edges, EDGE_IMPORTS)
    assert "PAYCOPY" in imports
    assert "SQLCA" in imports


def test_cobol_paragraph_spans_run_to_next_paragraph():
    parser = StructuralParser(COBOL_CONFIG)
    result = parser.parse(file_path="payroll01.cbl", source=COBOL_SOURCE)

    by_name = {n.name: n for n in result.nodes if n.kind == "paragraph"}
    main = by_name["MAIN-PARA"]
    init = by_name["INIT-PARA"]
    # MAIN-PARA's body ends the line before INIT-PARA opens.
    assert main.line_end == init.line_start - 1
    # Qualified names carry the program container prefix.
    assert main.qualified_name == "PAYROLL01.MAIN-PARA"


# ── JCL ───────────────────────────────────────────────────────────────────────

JCL_SOURCE = b"""\
//NIGHTJOB JOB (ACCT),'NIGHTLY BATCH',CLASS=A
//STEP010  EXEC PGM=PAYROLL1
//INFILE   DD DSN=PROD.PAYROLL.INPUT,DISP=SHR
//OUTFILE  DD DSN=PROD.PAYROLL.OUTPUT,DISP=(NEW,CATLG)
//STEP020  EXEC BILLPROC
//STEP030  EXEC PROC=RPTPROC
"""


def test_jcl_config_extracts_job_steps_and_edges():
    parser = StructuralParser(JCL_CONFIG)
    result = parser.parse(file_path="nightjob.jcl", source=JCL_SOURCE)

    assert _names(result.nodes, "job") == ["NIGHTJOB"]
    assert _names(result.nodes, "step") == ["STEP010", "STEP020", "STEP030"]

    calls = _edge_targets(result.edges, EDGE_CALLS)
    assert calls == ["PAYROLL1"]

    imports = _edge_targets(result.edges, EDGE_IMPORTS)
    assert "BILLPROC" in imports
    assert "RPTPROC" in imports
    # EXEC PGM= must not leak PGM as a bare-proc import.
    assert "PGM" not in imports

    refs = _edge_targets(result.edges, EDGE_REFERENCES)
    assert "PROD.PAYROLL.INPUT" in refs
    assert "PROD.PAYROLL.OUTPUT" in refs


def test_jcl_dd_cards_attach_to_their_step():
    parser = StructuralParser(JCL_CONFIG)
    result = parser.parse(file_path="nightjob.jcl", source=JCL_SOURCE)

    step010 = next(n for n in result.nodes if n.name == "STEP010")
    dsn_edges = [e for e in result.edges if e.kind == EDGE_REFERENCES and e.dst_name]
    assert dsn_edges and all(e.src_local_id == step010.local_id for e in dsn_edges)


# ── VB6 ───────────────────────────────────────────────────────────────────────

VB6_SOURCE = b"""\
Attribute VB_Name = "modBilling"
Option Explicit

Public Function CalcTotal(ByVal amount As Currency) As Currency
    On Error GoTo ErrHandler
    ValidateAmount (amount)
    CalcTotal = ApplyTax(amount)
    Exit Function
ErrHandler:
    Err.Raise vbObjectError
End Function

Private Sub ValidateAmount(ByVal amount As Currency)
    If amount < 0 Then
        MsgBox "bad amount"
    End If
End Sub
"""


def test_vb6_config_extracts_module_and_procedures():
    parser = StructuralParser(VB6_CONFIG)
    result = parser.parse(file_path="modBilling.bas", source=VB6_SOURCE)

    assert _names(result.nodes, "module") == ["modBilling"]
    procedures = _names(result.nodes, "procedure")
    assert procedures == ["CalcTotal", "ValidateAmount"]
    calc = next(n for n in result.nodes if n.name == "CalcTotal")
    assert calc.qualified_name == "modBilling.CalcTotal"
    # End Function closes the block.
    validate = next(n for n in result.nodes if n.name == "ValidateAmount")
    assert calc.line_end < validate.line_start


def test_vb6_config_extracts_calls_and_denies_keywords():
    parser = StructuralParser(VB6_CONFIG)
    result = parser.parse(file_path="modBilling.bas", source=VB6_SOURCE)

    calls = _edge_targets(result.edges, EDGE_CALLS)
    assert "ValidateAmount" in calls
    assert "ApplyTax" in calls
    # Keywords/intrinsics stay out.
    assert "If" not in calls
    assert "MsgBox" not in calls

    refs = _edge_targets(result.edges, EDGE_REFERENCES)
    assert "ErrHandler" in refs  # On Error GoTo target
    assert "Err" not in refs  # denylisted object reference


# ── contains topology ─────────────────────────────────────────────────────────


def test_container_owns_blocks_and_file_owns_container():
    parser = StructuralParser(VB6_CONFIG)
    result = parser.parse(file_path="modBilling.bas", source=VB6_SOURCE)

    module = next(n for n in result.nodes if n.kind == "module")
    contains = [e for e in result.edges if e.kind == EDGE_CONTAINS]
    file_children = {e.dst_local_id for e in contains if e.src_local_id == "<file>"}
    module_children = {
        e.dst_local_id for e in contains if e.src_local_id == module.local_id
    }
    assert module.local_id in file_children
    procedure_ids = {n.local_id for n in result.nodes if n.kind == "procedure"}
    assert procedure_ids == module_children


# ── config validation ─────────────────────────────────────────────────────────


def test_node_rule_requires_name_group():
    with pytest.raises(ValueError, match="name"):
        StructuralConfig.model_validate(
            {
                "id": "bad",
                "file_extensions": [".x"],
                "node_rules": [{"kind": "thing", "scope": "block", "match": r"\w+"}],
            }
        )


def test_edge_rule_rejects_unknown_kind():
    with pytest.raises(ValueError, match="edge kind"):
        StructuralConfig.model_validate(
            {
                "id": "bad",
                "file_extensions": [".x"],
                "node_rules": [
                    {"kind": "thing", "scope": "block", "match": r"(?P<name>\w+)"}
                ],
                "edge_rules": [
                    {"kind": "explodes", "from": "thing", "match": r"(?P<t>\w+)"}
                ],
            }
        )


def test_edge_rule_with_two_groups_requires_target_group():
    with pytest.raises(ValueError, match="target_group"):
        StructuralConfig.model_validate(
            {
                "id": "bad",
                "file_extensions": [".x"],
                "node_rules": [
                    {"kind": "thing", "scope": "block", "match": r"(?P<name>\w+)"}
                ],
                "edge_rules": [
                    {
                        "kind": "calls",
                        "from": "thing",
                        "match": r"(?P<a>\w+)\.(?P<b>\w+)",
                    }
                ],
            }
        )


def test_load_structural_parsers_skips_broken_configs(tmp_path: Path):
    good = tmp_path / "good.yaml"
    good.write_text(
        "id: good\n"
        "file_extensions: ['.zzz']\n"
        "node_rules:\n"
        "  - kind: unit\n"
        "    scope: block\n"
        "    match: 'UNIT (?P<name>\\w+)'\n",
        encoding="utf-8",
    )
    broken = tmp_path / "broken.yaml"
    broken.write_text("id: broken\nfile_extensions: []\n", encoding="utf-8")

    parsers = load_structural_parsers([good, broken])
    assert [p.name for p in parsers] == ["good"]


# ── registry hook ─────────────────────────────────────────────────────────────


def test_build_registry_extra_parsers_extend_and_win_collisions():
    cobol = StructuralParser(COBOL_CONFIG)
    registry = build_registry(extra_parsers=[cobol])

    assert registry.for_path("estate/payroll.cbl") is cobol
    # Builtins still present.
    assert registry.for_path("app/main.py") is not None

    # An extra parser claiming .py wins over the builtin.
    override = StructuralParser(
        StructuralConfig.model_validate(
            {
                "id": "py-override",
                "file_extensions": [".py"],
                "node_rules": [
                    {"kind": "unit", "scope": "block", "match": r"UNIT (?P<name>\w+)"}
                ],
            }
        )
    )
    registry2 = build_registry(extra_parsers=[override])
    assert registry2.for_path("app/main.py") is override
