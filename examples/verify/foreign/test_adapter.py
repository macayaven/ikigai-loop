import copy
import unittest

from adapter import MissingProvenance, to_verify_input

AGENT = {
    "report": {
        "statements": [
            {
                "sid": "s1",
                "sentence": "November deploys hit 12 with the queue steady",
                "figures": [{"field": "november_deploys", "figure": 12}],
                "note_refs": [],
            },
            {
                "sid": "s2",
                "sentence": "The support queue note is filed",
                "figures": [],
                "note_refs": ["n1"],
            },
        ]
    }
}

SOURCE = {
    "ledger": {
        "monthly_deploys": {"november": 7, "october": 5},
        "ticket_notes": {"n1": "Support queue note filed on Monday"},
    }
}


class TestAdapter(unittest.TestCase):
    def test_disagreement_keeps_both_values(self):
        out = to_verify_input(copy.deepcopy(AGENT), copy.deepcopy(SOURCE))
        claim = next(c for c in out["claims"] if c["id"] == "s1")
        self.assertEqual(claim["metric_refs"][0]["value"], 12)
        self.assertEqual(out["metrics"]["monthly_deploys.november"], 7)

    def test_changing_agent_figure_changes_no_metric(self):
        agent = copy.deepcopy(AGENT)
        agent["report"]["statements"][0]["figures"][0]["figure"] = 99
        out = to_verify_input(agent, copy.deepcopy(SOURCE))
        self.assertEqual(out["metrics"]["monthly_deploys.november"], 7)
        claim = next(c for c in out["claims"] if c["id"] == "s1")
        self.assertEqual(claim["metric_refs"][0]["value"], 99)

    def test_figure_with_no_table_entry_raises(self):
        agent = copy.deepcopy(AGENT)
        agent["report"]["statements"][0]["figures"].append(
            {"field": "december_deploys", "figure": 3}
        )
        with self.assertRaises(MissingProvenance):
            to_verify_input(agent, copy.deepcopy(SOURCE))

    def test_missing_provenance_is_value_error(self):
        self.assertTrue(issubclass(MissingProvenance, ValueError))

    def test_facts_come_from_source_only(self):
        agent = copy.deepcopy(AGENT)
        out = to_verify_input(agent, copy.deepcopy(SOURCE))
        self.assertEqual(out["facts"], {"n1": "Support queue note filed on Monday"})

    def test_unknown_note_ref_stays_in_fact_ids(self):
        agent = copy.deepcopy(AGENT)
        agent["report"]["statements"][1]["note_refs"] = ["nX"]
        out = to_verify_input(agent, copy.deepcopy(SOURCE))
        claim = next(c for c in out["claims"] if c["id"] == "s2")
        self.assertEqual(claim["fact_ids"], ["nX"])
        self.assertNotIn("nX", out["facts"])

    def test_labels_use_agent_words(self):
        out = to_verify_input(copy.deepcopy(AGENT), copy.deepcopy(SOURCE))
        words = (
            " ".join(c["text"] for c in out["claims"] if c["id"] == "s1")
            .lower()
            .split()
        )
        for lab in out["labels"]["monthly_deploys.november"]:
            self.assertIn(lab.lower(), words)

    def test_order_is_earliest_first(self):
        out = to_verify_input(copy.deepcopy(AGENT), copy.deepcopy(SOURCE))
        self.assertEqual(
            out["order"], [["monthly_deploys.october", "monthly_deploys.november"]]
        )


if __name__ == "__main__":
    unittest.main()
