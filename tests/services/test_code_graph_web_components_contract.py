"""Exact graph contracts for Svelte, Vue, Astro, and Liquid components."""

from __future__ import annotations

from collections import Counter

from app.services.code_index.graph_types import (
    EDGE_CALLS,
    EDGE_CONTAINS,
    EDGE_IMPORTS,
    EDGE_REFERENCES,
    NODE_FUNCTION,
    NODE_MODULE,
    NODE_VARIABLE,
)
from app.services.code_index.parsers.web_components import (
    AstroParser,
    LiquidParser,
    SvelteParser,
    VueParser,
    _quoted_template_literal,
)
from app.services.code_index.parsers.ecmascript import (
    JavaScriptParser,
    TsxParser,
    TypeScriptParser,
)


def _named_edges(result, kind: str):
    names = {node.local_id: node.qualified_name for node in result.nodes}
    return [
        (names[edge.src_local_id], edge.dst_name)
        for edge in result.edges
        if edge.kind == kind and edge.dst_name is not None
    ]


def _local_edges(result, kind: str):
    names = {node.local_id: node.qualified_name for node in result.nodes}
    return [
        (names[edge.src_local_id], names[edge.dst_local_id])
        for edge in result.edges
        if edge.kind == kind and edge.dst_local_id is not None
    ]


def test_svelte_component_scripts_template_and_external_import_are_exact() -> None:
    source = b'''<script LANG = ts>
import Widget from './Widget.svelte';
export let user: User;
function handleClick() { service.run(); }
</script>
<script src="./external?raw#fragment"></script>
<Widget on:select={handleClick} value={user} />
<svelte:component this={Current} />
<p>{user}</p>
<button on:click={handleClick}>Go</button>
'''
    result = SvelteParser().parse(file_path=r"components\App.svelte", source=source)

    assert Counter((node.kind, node.qualified_name) for node in result.nodes) == Counter(
        {
            ("file", r"components\App.svelte"): 1,
            (NODE_MODULE, "App"): 1,
            (NODE_VARIABLE, "App.user"): 1,
            (NODE_FUNCTION, "App.handleClick"): 1,
        }
    )
    assert _local_edges(result, EDGE_CONTAINS) == [
        (r"components\App.svelte", "App"),
        ("App", "App.user"),
        ("App", "App.handleClick"),
    ]
    assert _named_edges(result, EDGE_IMPORTS) == [
        ("App", "Widget"),
        ("App", "external"),
    ]
    imports = [
        (edge.dst_name, edge.module_path)
        for edge in result.edges
        if edge.kind == EDGE_IMPORTS
    ]
    assert imports == [
        ("Widget", "./Widget.svelte"),
        ("external", "./external?raw#fragment"),
    ]
    file_node, component = result.nodes[:2]
    expected_line_end = source.count(b"\n") + 1
    assert (
        file_node.local_id,
        file_node.name,
        file_node.line_start,
        file_node.line_end,
    ) == ("<file>", r"components\App.svelte", 1, expected_line_end)
    assert (
        component.local_id,
        component.name,
        component.line_start,
        component.line_end,
    ) == ("<component>", "App", 1, expected_line_end)
    contains = [edge for edge in result.edges if edge.kind == EDGE_CONTAINS]
    assert contains[0].line == 1
    external = next(
        edge
        for edge in result.edges
        if edge.kind == EDGE_IMPORTS and edge.dst_name == "external"
    )
    assert (external.local_name, external.line) == ("external", 6)
    handle = next(node for node in result.nodes if node.name == "handleClick")
    assert (handle.line_start, handle.line_end) == (4, 4)
    assert next(edge for edge in result.edges if edge.kind == EDGE_CALLS).line == 4
    assert _named_edges(result, EDGE_REFERENCES) == [
        ("App.user", "User"),
        ("App", "Widget"),
        ("App", "handleClick"),
        ("App", "user"),
        ("App", "Current"),
        ("App", "user"),
        ("App", "handleClick"),
    ]
    assert _named_edges(result, EDGE_CALLS) == [
        ("App.handleClick", "service.run")
    ]


def test_vue_component_setup_template_components_bindings_and_events_are_exact() -> None:
    source = b'''<script setup LANG=TypeScript>
import UserCard from './UserCard.vue';
const user: User = loadUser();
const handle = () => submit();
</script>
<template>
  <UserCard @select="handle" :user="user" v-on:close="onClose" v-bind:owner="owner" />
  <user-badge />
  <Teleport />
  <p>{{ user }}</p>
  <p>{{ XtitleX }}</p>
  <button @click="handle" />
</template>
'''
    result = VueParser().parse(file_path="Dashboard.vue", source=source)

    assert Counter((node.kind, node.qualified_name) for node in result.nodes) == Counter(
        {
            ("file", "Dashboard.vue"): 1,
            (NODE_MODULE, "Dashboard"): 1,
            (NODE_VARIABLE, "Dashboard.user"): 1,
            (NODE_FUNCTION, "Dashboard.handle"): 1,
        }
    )
    assert _named_edges(result, EDGE_IMPORTS) == [("Dashboard", "UserCard")]
    assert _named_edges(result, EDGE_REFERENCES) == [
        ("Dashboard.user", "User"),
        ("Dashboard", "UserCard"),
        ("Dashboard", "handle"),
        ("Dashboard", "user"),
        ("Dashboard", "onClose"),
        ("Dashboard", "owner"),
        ("Dashboard", "UserBadge"),
        ("Dashboard", "user"),
        ("Dashboard", "XtitleX"),
        ("Dashboard", "handle"),
    ]
    assert _named_edges(result, EDGE_CALLS) == [
        ("Dashboard.user", "loadUser"),
        ("Dashboard.handle", "submit"),
    ]


def test_astro_frontmatter_client_script_template_and_external_script_are_exact() -> None:
    source = b'''---
import Layout from './Layout.astro';
const title: Title = loadTitle();
function handle() { submit(); }
---
<Fragment><Layout><UserCard value={title} client:load /></Layout></Fragment>
<button on:click={handle}>{title}</button>
<p>{XtitleX}</p>
<script>function clientOnly() { browser.start(); }</script>
<script src="./island.js#client"></script>
'''
    result = AstroParser().parse(file_path="Page.astro", source=source)

    assert Counter((node.kind, node.qualified_name) for node in result.nodes) == Counter(
        {
            ("file", "Page.astro"): 1,
            (NODE_MODULE, "Page"): 1,
            (NODE_VARIABLE, "Page.title"): 1,
            (NODE_FUNCTION, "Page.handle"): 1,
            (NODE_FUNCTION, "Page.clientOnly"): 1,
        }
    )
    assert _named_edges(result, EDGE_IMPORTS) == [
        ("Page", "Layout"),
        ("Page", "island"),
    ]
    assert _named_edges(result, EDGE_REFERENCES) == [
        ("Page.title", "Title"),
        ("Page", "Layout"),
        ("Page", "UserCard"),
        ("Page", "title"),
        ("Page", "handle"),
        ("Page", "title"),
        ("Page", "XtitleX"),
    ]
    assert _named_edges(result, EDGE_CALLS) == [
        ("Page.title", "loadTitle"),
        ("Page.handle", "submit"),
        ("Page.clientOnly", "browser.start"),
    ]


def test_liquid_component_variables_static_dependencies_and_references_are_exact() -> None:
    source = b'''{% assign title = product.title %}
{% capture body %}Hi{% endcapture %}
{% for item in items %}{{ item }}{% endfor %}
{% increment counter %}
{% decrement remaining %}
{% render 'cards/product', card: product %}
{% include helper_template %}
{{ title }}
'''
    result = LiquidParser().parse(file_path="card.liquid", source=source)

    assert Counter((node.kind, node.qualified_name) for node in result.nodes) == Counter(
        {
            ("file", "card.liquid"): 1,
            (NODE_MODULE, "card"): 1,
            (NODE_VARIABLE, "card.title"): 1,
            (NODE_VARIABLE, "card.body"): 1,
            (NODE_VARIABLE, "card.item"): 1,
            (NODE_VARIABLE, "card.counter"): 1,
            (NODE_VARIABLE, "card.remaining"): 1,
        }
    )
    assert _named_edges(result, EDGE_REFERENCES) == [
        ("card", "product.title"),
        ("card", "items"),
        ("card", "item"),
        ("card", "product"),
        ("card", "helper_template"),
        ("card", "title"),
    ]
    assert _named_edges(result, EDGE_CALLS) == [("card", "cards/product")]
    assert _named_edges(result, EDGE_IMPORTS) == [("card", "product")]
    imported = next(edge for edge in result.edges if edge.kind == EDGE_IMPORTS)
    assert imported.module_path == "cards/product"
    assert result.language == "liquid"
    assert result.nodes[0].line_end == source.count(b"\n") + 1
    assert result.nodes[1].line_end == source.count(b"\n") + 1
    assert _quoted_template_literal("''") is True
    assert _quoted_template_literal('"double"') is True
    assert _quoted_template_literal("'broken") is False


def test_component_script_language_dispatch_is_exact() -> None:
    parser = SvelteParser()

    def selected(source: bytes):
        script = parser._get_parser().parse(source).root_node.named_children[0]
        return parser._parser_for_script(script, source)

    assert isinstance(selected(b'<script lang="tsx"></script>'), TsxParser)
    assert isinstance(selected(b'<script lang="ts"></script>'), TypeScriptParser)
    assert isinstance(selected(b'<script lang="typescript"></script>'), TypeScriptParser)
    assert isinstance(selected(b"<script></script>"), JavaScriptParser)
    assert isinstance(selected(b"<script lang></script>"), JavaScriptParser)
