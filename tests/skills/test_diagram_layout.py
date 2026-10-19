import unittest

from app.agent.tools.builtin.visualize.geometry import check_svg_layout


class CheckSvgLayoutTests(unittest.TestCase):
    def test_accepts_separated_nodes_with_boundary_to_boundary_connector(self):
        svg = """<svg viewBox="0 0 240 100" xmlns="http://www.w3.org/2000/svg">
          <path class="edge" d="M80 40 H160"/>
          <rect class="node" x="20" y="20" width="60" height="40"/>
          <rect class="node" x="160" y="20" width="60" height="40"/>
        </svg>"""
        result = check_svg_layout(svg)
        self.assertEqual([], result["errors"])

    def test_reports_overlapping_nodes_and_connector_ending_inside_target(self):
        svg = """<svg viewBox="0 0 240 100" xmlns="http://www.w3.org/2000/svg">
          <path class="edge" d="M80 40 H180"/>
          <rect class="node" x="20" y="20" width="70" height="40"/>
          <rect class="node" x="80" y="20" width="60" height="40"/>
          <rect class="node" x="160" y="20" width="60" height="40"/>
        </svg>"""
        result = check_svg_layout(svg)
        self.assertTrue(any("overlap" in error for error in result["errors"]))
        self.assertTrue(any("endpoint" in error for error in result["errors"]))

    def test_reports_artwork_outside_viewbox_and_route_through_unrelated_node(self):
        svg = """<svg viewBox="0 0 240 100" xmlns="http://www.w3.org/2000/svg">
          <path class="edge" d="M60 40 H180"/>
          <rect class="node" x="20" y="20" width="40" height="40"/>
          <rect class="node" x="100" y="20" width="40" height="40"/>
          <rect class="node" x="180" y="20" width="40" height="40"/>
          <circle cx="250" cy="50" r="4"/>
        </svg>"""
        result = check_svg_layout(svg)
        self.assertTrue(any("viewBox" in error for error in result["errors"]))
        self.assertTrue(any("crosses" in error for error in result["errors"]))

    def test_rejects_connector_that_touches_the_wrong_target_side(self):
        svg = """<svg viewBox="0 0 240 100" xmlns="http://www.w3.org/2000/svg">
          <path class="edge" d="M80 20 H180"/>
          <rect class="node" x="20" y="20" width="60" height="40"/>
          <rect class="node" x="160" y="20" width="60" height="40"/>
        </svg>"""
        result = check_svg_layout(svg)
        self.assertTrue(any("target boundary" in error for error in result["errors"]))

    def test_reports_node_label_that_does_not_fit_inside_its_box(self):
        svg = """<svg viewBox="0 0 180 100" xmlns="http://www.w3.org/2000/svg">
          <rect class="node" x="20" y="20" width="96" height="40"/>
          <text class="node-label" x="68" y="44" text-anchor="middle">Long database replication endpoint</text>
        </svg>"""
        result = check_svg_layout(svg)
        self.assertTrue(
            any("label" in error and "node" in error for error in result["errors"])
        )

    def test_accepts_sequence_edges_attached_to_lifelines(self):
        svg = """<svg viewBox="0 0 240 120" xmlns="http://www.w3.org/2000/svg">
          <line class="lifeline" x1="80" y1="40" x2="80" y2="110"/>
          <line class="lifeline" x1="160" y1="40" x2="160" y2="110"/>
          <path class="edge" d="M80 60 H152"/>
          <rect class="node" x="40" y="10" width="80" height="30"/>
          <rect class="node" x="120" y="10" width="80" height="30"/>
        </svg>"""
        result = check_svg_layout(svg)
        self.assertEqual([], result["errors"])

    def test_checks_sequence_participant_headers_and_labels(self):
        svg = """<svg viewBox="0 0 240 120" xmlns="http://www.w3.org/2000/svg">
          <rect class="seq-head" x="30" y="10" width="80" height="30"/>
          <text class="head-name" x="70" y="29" text-anchor="middle">Buyer</text>
          <rect class="seq-head" x="130" y="10" width="80" height="30"/>
          <text class="head-name" x="170" y="29" text-anchor="middle">Checkout</text>
          <line class="lifeline" x1="70" y1="40" x2="70" y2="110"/>
          <line class="lifeline" x1="170" y1="40" x2="170" y2="110"/>
          <path class="edge" d="M70 60 H170"/>
        </svg>"""
        result = check_svg_layout(svg)
        self.assertEqual([], result["errors"])
        self.assertEqual(2, result["nodes_checked"])
        self.assertEqual(1, result["connectors_checked"])

    def test_recognizes_er_boxes_and_crow_foot_edges(self):
        svg = """<svg viewBox="0 0 220 80" xmlns="http://www.w3.org/2000/svg">
          <path class="er-edge" d="M80 40 H140"/>
          <rect class="er-box" x="20" y="20" width="60" height="40"/>
          <rect class="er-box" x="140" y="20" width="60" height="40"/>
        </svg>"""
        result = check_svg_layout(svg)
        self.assertEqual([], result["errors"])
        self.assertEqual(2, result["nodes_checked"])
        self.assertEqual(1, result["connectors_checked"])


if __name__ == "__main__":
    unittest.main()
