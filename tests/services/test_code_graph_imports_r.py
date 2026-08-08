"""Tests for EDGE_IMPORTS emission from the R parser."""

from __future__ import annotations

from app.services.code_index.parsers.r_lang import RParser
from app.services.code_index.graph_types import EDGE_IMPORTS


def _import_names(result):
    return [e.dst_name for e in result.edges if e.kind == EDGE_IMPORTS]


def test_r_library_call():
    source = b"""library(dplyr)
"""
    result = RParser().parse(file_path="main.R", source=source)
    names = _import_names(result)
    assert "dplyr" in names


def test_r_require_call():
    source = b"""require(ggplot2)
"""
    result = RParser().parse(file_path="main.R", source=source)
    names = _import_names(result)
    assert "ggplot2" in names


def test_r_library_call_string_literal():
    source = b"""library("data.table")
"""
    result = RParser().parse(file_path="main.R", source=source)
    names = _import_names(result)
    assert "data.table" in names


def test_r_multiple_loader_calls():
    source = b"""library(dplyr)
require(ggplot2)
suppressMessages(library(purrr))
"""
    result = RParser().parse(file_path="main.R", source=source)
    names = _import_names(result)
    assert "dplyr" in names
    assert "ggplot2" in names
    assert "purrr" in names


def test_r_namespace_operator():
    source = b"""x <- stats::sd(1:10)
y <- MASS::select
"""
    result = RParser().parse(file_path="main.R", source=source)
    names = _import_names(result)
    assert "stats" in names
    assert "MASS" in names


def test_r_namespace_loaders_and_literal_source_file():
    source = b"""requireNamespace("dplyr")
loadNamespace("rlang")
source("helpers.R")
source(dynamic_path)
"""
    result = RParser().parse(file_path="main.R", source=source)
    imports = [edge for edge in result.edges if edge.kind == EDGE_IMPORTS]

    assert [(edge.dst_name, edge.module_path) for edge in imports] == [
        ("dplyr", "dplyr"),
        ("rlang", "rlang"),
        ("helpers", "helpers.R"),
    ]
