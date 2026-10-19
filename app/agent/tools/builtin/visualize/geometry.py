"""Conservative geometry preflight for SVG node/edge layouts.

Supports explicit untransformed rect nodes and absolute M/L/H/V connector paths.
Unrecognized SVG path commands are reported as warnings; they are never treated
as proof that geometry is clear.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree


@dataclass(frozen=True)
class Box:
    key: str
    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    def contains(self, x: float, y: float, tolerance: float = 0) -> bool:
        return (
            self.x - tolerance <= x <= self.right + tolerance
            and self.y - tolerance <= y <= self.bottom + tolerance
        )

    def contains_box(self, other: Box) -> bool:
        return (
            self.x <= other.x
            and self.y <= other.y
            and self.right >= other.right
            and self.bottom >= other.bottom
        )


@dataclass(frozen=True)
class Lifeline:
    key: str
    x: float
    y1: float
    y2: float


Point = tuple[float, float]
Segment = tuple[Point, Point]
_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
_PATH_TOKEN = re.compile(rf"[A-Za-z]|{_NUMBER}")
_NODE_CLASSES = {
    "node",
    "state",
    "entity",
    "participant",
    "actor",
    "service-node",
    "er-box",
    "entity-box",
    "state-box",
    "actor-box",
    "seq-head",
}
_EDGE_CLASSES = {"edge", "connector", "transition", "relationship", "er-edge"}
_NODE_LABEL = re.compile(
    r"(?:^|-)(?:node|state|entity|participant|actor)(?:-name)?-label$|"
    r"(?:^|-)(?:er-name|head-name)$"
)
_EXTERNAL_LABEL = re.compile(r"(?:^|-)(?:edge|connector|transition)-label$")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _number(value: str | None, default: float = 0) -> float:
    if value is None:
        return default
    match = re.match(_NUMBER, value.strip())
    return float(match.group(0)) if match else default


def _path_segments(path: str) -> tuple[list[Segment] | None, str | None]:
    tokens = _PATH_TOKEN.findall(path)
    if not tokens:
        return None, "empty path"
    segments: list[Segment] = []
    current: Point | None = None
    index = 0
    while index < len(tokens):
        command = tokens[index]
        index += 1
        if command not in {"M", "L", "H", "V"}:
            return None, f"unsupported path command {command}"
        try:
            if command in {"M", "L"}:
                point = (float(tokens[index]), float(tokens[index + 1]))
                index += 2
                if current is not None and command == "L":
                    segments.append((current, point))
                current = point
            elif command == "H":
                if current is None:
                    return None, "horizontal segment has no start point"
                point = (float(tokens[index]), current[1])
                index += 1
                segments.append((current, point))
                current = point
            else:
                if current is None:
                    return None, "vertical segment has no start point"
                point = (current[0], float(tokens[index]))
                index += 1
                segments.append((current, point))
                current = point
        except (IndexError, ValueError):
            return None, "incomplete path coordinates"
        if index < len(tokens) and not tokens[index][0].isalpha():
            return None, "repeated path coordinates are unsupported"
    return segments, None


def _segment_crosses_interior(segment: Segment, box: Box) -> bool:
    (x1, y1), (x2, y2) = segment
    if y1 == y2:
        return box.y < y1 < box.bottom and max(min(x1, x2), box.x) < min(
            max(x1, x2), box.right
        )
    if x1 == x2:
        return box.x < x1 < box.right and max(min(y1, y2), box.y) < min(
            max(y1, y2), box.bottom
        )
    return False


def _endpoint_on_boundary(
    segment: Segment, box: Box, *, is_start: bool, tolerance: float = 1.5
) -> bool:
    point, neighbor = (segment[0], segment[1]) if is_start else (segment[1], segment[0])
    x, y = point
    if not box.contains(x, y, tolerance):
        return False
    horizontal = abs(segment[0][1] - segment[1][1]) <= tolerance
    vertical = abs(segment[0][0] - segment[1][0]) <= tolerance
    if horizontal:
        if abs(x - box.x) <= tolerance:
            return neighbor[0] < box.x - tolerance
        if abs(x - box.right) <= tolerance:
            return neighbor[0] > box.right + tolerance
    if vertical:
        if abs(y - box.y) <= tolerance:
            return neighbor[1] < box.y - tolerance
        if abs(y - box.bottom) <= tolerance:
            return neighbor[1] > box.bottom + tolerance
    return False


def _point_on_box_boundary(point: Point, box: Box, tolerance: float = 1.5) -> bool:
    x, y = point
    return box.contains(x, y, tolerance) and (
        abs(x - box.x) <= tolerance
        or abs(x - box.right) <= tolerance
        or abs(y - box.y) <= tolerance
        or abs(y - box.bottom) <= tolerance
    )


def _endpoint_on_lifeline(
    segment: Segment, lifeline: Lifeline, *, is_start: bool, tolerance: float = 10
) -> bool:
    point, neighbor = (segment[0], segment[1]) if is_start else (segment[1], segment[0])
    x, y = point
    if (
        abs(segment[0][1] - segment[1][1]) > 1.5
        or abs(x - lifeline.x) > tolerance
        or not min(lifeline.y1, lifeline.y2) <= y <= max(lifeline.y1, lifeline.y2)
    ):
        return False
    if abs(x - lifeline.x) <= 1.5:
        return abs(neighbor[0] - x) > 1.5
    if is_start:
        return neighbor[0] > x if x > lifeline.x else neighbor[0] < x
    return neighbor[0] > x if x > lifeline.x else neighbor[0] < x


def check_svg_layout(source: str) -> dict[str, object]:
    """Report overlap, connector, and viewBox errors for recognizable SVG geometry."""
    match = re.search(r"<svg\b[\s\S]*?</svg\s*>", source, re.IGNORECASE)
    svg = match.group(0) if match else source
    errors: list[str] = []
    warnings: list[str] = []
    try:
        root = ElementTree.fromstring(svg)
    except ElementTree.ParseError as exc:
        return {
            "errors": [f"invalid SVG: {exc}"],
            "warnings": [],
            "nodes_checked": 0,
            "connectors_checked": 0,
        }

    view_values = [
        float(value) for value in re.findall(_NUMBER, root.attrib.get("viewBox", ""))
    ]
    view_box = None
    if len(view_values) == 4:
        view_box = Box("viewBox", *view_values)
    else:
        errors.append("missing or invalid viewBox")

    nodes: list[Box] = []
    lifelines: list[Lifeline] = []
    connectors: list[tuple[str, list[Segment], Point, Point]] = []
    parents = {child: parent for parent in root.iter() for child in parent}
    for element in root.iter():
        ancestor = parents.get(element)
        in_defs = False
        while ancestor is not None:
            if _local_name(ancestor.tag) == "defs":
                in_defs = True
                break
            ancestor = parents.get(ancestor)
        if in_defs:
            continue
        tag = _local_name(element.tag)
        classes = set(element.attrib.get("class", "").split())
        if tag == "rect" and classes.intersection(_NODE_CLASSES):
            transform = element.attrib.get("transform")
            if transform:
                warnings.append(
                    f"node {element.attrib.get('id', len(nodes) + 1)} has transform; bounds not checked"
                )
                continue
            node = Box(
                element.attrib.get("id", f"node-{len(nodes) + 1}"),
                _number(element.attrib.get("x")),
                _number(element.attrib.get("y")),
                _number(element.attrib.get("width")),
                _number(element.attrib.get("height")),
            )
            if node.width <= 0 or node.height <= 0:
                errors.append(f"node {node.key} has non-positive dimensions")
            else:
                nodes.append(node)
        elif tag == "path" and classes.intersection(_EDGE_CLASSES):
            path = element.attrib.get("d", "")
            segments, warning = _path_segments(path)
            if warning:
                warnings.append(
                    f"connector {element.attrib.get('id', len(connectors) + 1)}: {warning}; inspect manually"
                )
            elif segments:
                connectors.append(
                    (
                        element.attrib.get("id", f"connector-{len(connectors) + 1}"),
                        segments,
                        segments[0][0],
                        segments[-1][1],
                    )
                )
        elif tag == "line" and "lifeline" in classes:
            x1, y1 = (
                _number(element.attrib.get("x1")),
                _number(element.attrib.get("y1")),
            )
            x2, y2 = (
                _number(element.attrib.get("x2")),
                _number(element.attrib.get("y2")),
            )
            if abs(x1 - x2) <= 1.5:
                lifelines.append(
                    Lifeline(
                        element.attrib.get("id", f"lifeline-{len(lifelines) + 1}"),
                        x1,
                        y1,
                        y2,
                    )
                )
            if view_box and (
                min(x1, x2) < view_box.x
                or max(x1, x2) > view_box.right
                or min(y1, y2) < view_box.y
                or max(y1, y2) > view_box.bottom
            ):
                errors.append("lifeline extends outside viewBox")
        elif view_box and tag in {"rect", "circle", "ellipse", "line"}:
            if tag == "rect":
                x, y = (
                    _number(element.attrib.get("x")),
                    _number(element.attrib.get("y")),
                )
                right = x + _number(element.attrib.get("width"))
                bottom = y + _number(element.attrib.get("height"))
            elif tag == "circle":
                cx, cy, radius = (
                    _number(element.attrib.get(name)) for name in ("cx", "cy", "r")
                )
                x, y, right, bottom = cx - radius, cy - radius, cx + radius, cy + radius
            elif tag == "ellipse":
                cx, cy = (
                    _number(element.attrib.get("cx")),
                    _number(element.attrib.get("cy")),
                )
                rx, ry = (
                    _number(element.attrib.get("rx")),
                    _number(element.attrib.get("ry")),
                )
                x, y, right, bottom = cx - rx, cy - ry, cx + rx, cy + ry
            else:
                x1, y1 = (
                    _number(element.attrib.get("x1")),
                    _number(element.attrib.get("y1")),
                )
                x2, y2 = (
                    _number(element.attrib.get("x2")),
                    _number(element.attrib.get("y2")),
                )
                x, y, right, bottom = min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)
            stroke = _number(element.attrib.get("stroke-width"), 1) / 2
            if (
                x - stroke < view_box.x
                or y - stroke < view_box.y
                or right + stroke > view_box.right
                or bottom + stroke > view_box.bottom
            ):
                errors.append(f"{tag} artwork extends outside viewBox")

    for index, first in enumerate(nodes):
        for second in nodes[index + 1 :]:
            intersects = (
                first.x < second.right
                and second.x < first.right
                and first.y < second.bottom
                and second.y < first.bottom
            )
            intentional_nesting = first.contains_box(second) or second.contains_box(
                first
            )
            if intersects and not intentional_nesting:
                errors.append(f"node overlap: {first.key} overlaps {second.key}")

    if view_box:
        for node in nodes:
            if (
                node.x < view_box.x
                or node.y < view_box.y
                or node.right > view_box.right
                or node.bottom > view_box.bottom
            ):
                errors.append(f"node {node.key} extends outside viewBox")

    for element in root.iter():
        if _local_name(element.tag) != "text":
            continue
        classes = set(element.attrib.get("class", "").split())
        class_name = next(iter(classes), "text")
        content = " ".join("".join(element.itertext()).split())
        if not content:
            continue
        x, baseline = _number(element.attrib.get("x")), _number(element.attrib.get("y"))
        font_size = _number(element.attrib.get("font-size"), 12)
        style_size = re.search(
            rf"font-size\s*:\s*({_NUMBER})", element.attrib.get("style", "")
        )
        if style_size:
            font_size = float(style_size.group(1))
        text_width = len(content) * font_size * 0.58
        anchor = element.attrib.get("text-anchor", "start")
        left = (
            x - text_width / 2
            if anchor == "middle"
            else x - text_width
            if anchor == "end"
            else x
        )
        right = left + text_width
        top = baseline - font_size
        if view_box and (
            left < view_box.x
            or top < view_box.y
            or right > view_box.right
            or baseline > view_box.bottom
        ):
            errors.append(f"{class_name} label extends outside viewBox")
        if any(_NODE_LABEL.fullmatch(value) for value in classes):
            containing = [node for node in nodes if node.contains(x, baseline)]
            if not containing:
                errors.append(f"{class_name} label anchor is outside every node box")
            elif not any(
                left >= node.x + 6
                and right <= node.right - 6
                and top >= node.y + 2
                and baseline <= node.bottom - 2
                for node in containing
            ):
                errors.append(f"{class_name} label does not fit inside its node box")
        elif any(_EXTERNAL_LABEL.fullmatch(value) for value in classes):
            for node in nodes:
                overlaps = (
                    left < node.right
                    and right > node.x
                    and top < node.bottom
                    and baseline > node.y
                )
                if overlaps:
                    errors.append(f"{class_name} label overlaps node {node.key}")
                    break

    for key, segments, start, end in connectors:
        start_nodes = [
            node
            for node in nodes
            if _endpoint_on_boundary(segments[0], node, is_start=True)
        ]
        end_nodes = [
            node
            for node in nodes
            if _endpoint_on_boundary(segments[-1], node, is_start=False)
        ]
        start_lifelines = [
            line
            for line in lifelines
            if _endpoint_on_lifeline(segments[0], line, is_start=True)
        ]
        end_lifelines = [
            line
            for line in lifelines
            if _endpoint_on_lifeline(segments[-1], line, is_start=False)
        ]
        if not start_nodes and not start_lifelines:
            errors.append(
                f"connector {key} start endpoint misses a valid source boundary or lifeline"
            )
        if not end_nodes and not end_lifelines:
            containing_end = [node.key for node in nodes if node.contains(*end)]
            boundary_end = [
                node.key for node in nodes if _point_on_box_boundary(end, node)
            ]
            if boundary_end:
                errors.append(
                    f"connector {key} touches node {boundary_end[0]} on a non-facing target boundary"
                )
            elif containing_end:
                errors.append(f"connector {key} ends inside node {containing_end[0]}")
            else:
                errors.append(
                    f"connector {key} end endpoint misses a valid target boundary"
                )
        allowed = {node.key for node in start_nodes + end_nodes}
        for node in nodes:
            if node.key not in allowed and any(
                _segment_crosses_interior(segment, node) for segment in segments
            ):
                errors.append(f"connector {key} crosses non-endpoint node {node.key}")
                break
        if view_box:
            for (x1, y1), (x2, y2) in segments:
                if not (
                    view_box.x <= x1 <= view_box.right
                    and view_box.y <= y1 <= view_box.bottom
                    and view_box.x <= x2 <= view_box.right
                    and view_box.y <= y2 <= view_box.bottom
                ):
                    errors.append(f"connector {key} extends outside viewBox")
                    break

    if not nodes and not lifelines:
        warnings.append("no explicit node rectangles found; overlap checks are limited")
    if not connectors:
        warnings.append(
            "no supported connector paths found; endpoint checks are limited"
        )
    return {
        "errors": errors,
        "warnings": warnings,
        "nodes_checked": len(nodes),
        "connectors_checked": len(connectors),
        "viewBox": root.attrib.get("viewBox"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path, help="HTML or SVG file to preflight")
    args = parser.parse_args()
    result = check_svg_layout(args.file.read_text(encoding="utf-8"))
    print(json.dumps(result, indent=2))
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
