"""Exact behavioral contracts for R graph extraction."""

from __future__ import annotations

from collections import Counter

from app.services.code_index.graph_types import (
    EDGE_CALLS,
    EDGE_IMPORTS,
    EDGE_INHERITS,
    EDGE_REFERENCES,
    NODE_CLASS,
    NODE_FIELD,
    NODE_FUNCTION,
    NODE_METHOD,
    NODE_VARIABLE,
)
from app.services.code_index.parsers.r_lang import (
    RParser,
    _class_declaration_call,
    _positional_call_arg_text,
    _source_ref_name,
)


def _named_edges(result, kind: str):
    names = {node.local_id: node.qualified_name for node in result.nodes}
    return [
        (names[edge.src_local_id], edge.dst_name)
        for edge in result.edges
        if edge.kind == kind and edge.dst_name is not None
    ]


def test_r_symbols_dsl_calls_imports_docs_and_ownership_are_exact() -> None:
    source = b'''#'First line
#'Second line
documented <- 1
library(dplyr)
requireNamespace("jsonlite")
source("R/deep/utils.R")
config <- load_config()
path <- paste("x")
super_global <<- 2
equal_global = 3
99 -> backwards
100 ->> backwards_global
obj$field <- 1
1 -> obj$field
#' User class
User <- R6::R6Class("User",
  inherit = BaseUser,
  public = list(
    repo = NULL,
    initialize = function(repo) self$repo <- repo,
    run = function(input) {
      helper(input)
      client$api$call()
      client$api$list()
      stats::median(input)
    }
  )
)
#'Invoice class
setClass("Invoice",
  slots = c(id = "character", metadata = "list"),
  prototype = prototype(default = "draft"),
  contains = c("Document", "Auditable")
)
setClass("ListChild", contains = list("ParentA", "ParentB"))
setGeneric("render", function(x) standardGeneric("render"))
setMethod("render", package = "billing", "Invoice", function(x) renderer$render(x))
(function(x) x) -> handler
{function(x) x} ->> global_handler
outer <- function() {
  local_value <- 1
  nested <- function() helper()
  nested()
}
configure(handler = function() wrong())
wrapper(list())
factory()$run()
'''
    result = RParser().parse(file_path="model.R", source=source)
    nodes = {node.qualified_name: node for node in result.nodes}

    assert Counter((node.kind, node.qualified_name) for node in result.nodes) == Counter(
        {
            ("file", "model.R"): 1,
            (NODE_VARIABLE, "documented"): 1,
            (NODE_VARIABLE, "config"): 1,
            (NODE_VARIABLE, "path"): 1,
            (NODE_VARIABLE, "super_global"): 1,
            (NODE_VARIABLE, "equal_global"): 1,
            (NODE_VARIABLE, "backwards"): 1,
            (NODE_VARIABLE, "backwards_global"): 1,
            (NODE_CLASS, "User"): 1,
            (NODE_FIELD, "User.repo"): 1,
            (NODE_METHOD, "User.initialize"): 1,
            (NODE_METHOD, "User.run"): 1,
            (NODE_CLASS, "Invoice"): 1,
            (NODE_FIELD, "Invoice.id"): 1,
            (NODE_FIELD, "Invoice.metadata"): 1,
            (NODE_FIELD, "Invoice.default"): 1,
            (NODE_CLASS, "ListChild"): 1,
            (NODE_FUNCTION, "render"): 1,
            (NODE_METHOD, "Invoice.render"): 1,
            (NODE_FUNCTION, "handler"): 1,
            (NODE_FUNCTION, "global_handler"): 1,
            (NODE_FUNCTION, "outer"): 1,
            (NODE_FUNCTION, "outer.nested"): 1,
        }
    )
    assert "local_value" not in nodes
    assert "obj$field" not in nodes
    assert "handler" not in {
        node.name for node in result.nodes if node.kind == NODE_METHOD
    }
    assert nodes["documented"].docstring == "First line\nSecond line"
    assert nodes["User"].docstring == "User class"
    assert nodes["Invoice"].docstring == "Invoice class"
    assert _named_edges(result, EDGE_INHERITS) == [
        ("User", "BaseUser"),
        ("Invoice", "Document"),
        ("Invoice", "Auditable"),
        ("ListChild", "ParentA"),
        ("ListChild", "ParentB"),
    ]
    assert _named_edges(result, EDGE_CALLS) == [
        ("config", "load_config"),
        ("path", "paste"),
        ("User.run", "helper"),
        ("User.run", "client.api.call"),
        ("User.run", "client.api.list"),
        ("User.run", "stats.median"),
        ("render", "standardGeneric"),
        ("Invoice.render", "renderer.render"),
        ("outer.nested", "helper"),
        ("outer", "nested"),
        ("model.R", "configure"),
        ("model.R", "wrong"),
        ("model.R", "wrapper"),
        ("model.R", "list"),
        ("model.R", "run"),
        ("model.R", "factory"),
    ]
    assert _named_edges(result, EDGE_IMPORTS) == [
        ("model.R", "dplyr"),
        ("model.R", "jsonlite"),
        ("model.R", "utils"),
        ("User", "R6"),
        ("User.run", "stats"),
    ]
    imports = [
        (edge.dst_name, edge.module_path)
        for edge in result.edges
        if edge.kind == EDGE_IMPORTS
    ]
    assert imports == [
        ("dplyr", "dplyr"),
        ("jsonlite", "jsonlite"),
        ("utils", "R/deep/utils.R"),
        ("R6", "R6"),
        ("stats", "stats"),
    ]
    assert _named_edges(result, EDGE_REFERENCES) == []


def test_r_unassigned_reference_class_group_generic_and_replace_method() -> None:
    source = b'''setRefClass("Session", fields = list(id = "character"))
setGroupGeneric("Ops")
setReplaceMethod("name", "Session", function(x, value) storage$write(value))
'''
    result = RParser().parse(file_path="dsl.R", source=source)

    assert {(node.kind, node.qualified_name) for node in result.nodes} == {
        ("file", "dsl.R"),
        (NODE_CLASS, "Session"),
        (NODE_FIELD, "Session.id"),
        (NODE_FUNCTION, "Ops"),
        (NODE_METHOD, "Session.name"),
    }
    assert _named_edges(result, EDGE_CALLS) == [("Session.name", "storage.write")]


def test_r_language_hooks_reject_unrelated_nodes() -> None:
    parser = RParser()
    source = b"return(value)"
    root = parser._get_parser().parse(source).root_node

    assert parser.classify(root, source, inside_class=False) is None
    assert parser.call_target(root, source) is None
    assert parser.import_refs(root, source) == []
    assert parser.supertypes(root, source) == []
    assert parser.docstring(root, source) is None
    assert parser.identifier_reference_targets(root, source) == []
    assert _source_ref_name(r"R\deep\windows.R") == "windows"
    assert _source_ref_name("R/deep/unix.r") == "unix"
    assert _source_ref_name("plain") == "plain"

    assignment_source = b"fake <- builder(contains = FakeParent)"
    assignment = parser._get_parser().parse(assignment_source).root_node.named_children[0]
    assert _class_declaration_call(assignment, assignment_source) is None

    call_source = b'setMethod("lonely")'
    call = parser._get_parser().parse(call_source).root_node.named_children[0]
    assert _positional_call_arg_text(call, 1, call_source) is None
