"""The ledger's agent_stop line gains run, label and phase for an agent that a workflow script started (read from the
agent's .meta.json beside its transcript), and only names: a hand-started agent's free-text description never enters."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from relay_testbase import ROOT  # noqa: E402

HOOK = os.path.join(ROOT, "plugins", "observe", "hooks", "ledger.py")
LINE = '{"type":"assistant","timestamp":"2026-10-19T10:00:00Z","requestId":"r1","message":{"model":"claude-sonnet-5","usage":{"input_tokens":100,"cache_read_input_tokens":0,"cache_creation_input_tokens":0,"output_tokens":5}}}\n'


class WorkflowFields(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="ledger-wf-")
        self.home = os.path.join(self.tmp, "home")
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)

    def stop(self, folder: str, meta: str | None) -> dict:
        """Run the hook on a SubagentStop whose transcript is <tmp>/<folder>/agent-a1.jsonl; return the ledger line."""
        directory = os.path.join(self.tmp, folder)
        os.makedirs(directory, exist_ok=True)
        transcript = os.path.join(directory, "agent-a1.jsonl")
        with open(transcript, "w") as handle:
            handle.write(LINE)
        if meta is not None:
            with open(os.path.join(directory, "agent-a1.meta.json"), "w") as handle:
                handle.write(meta)
        event = {"hook_event_name": "SubagentStop", "session_id": "s", "cwd": "/p", "agent_id": "a1", "agent_type": "delegate:runner",
                 "agent_transcript_path": transcript}
        done = subprocess.run([sys.executable, HOOK], input=json.dumps(event), capture_output=True, text=True, env=dict(os.environ, RELAY_HOME=self.home), timeout=30)
        self.assertEqual(done.returncode, 0)
        lines = []
        ledger = os.path.join(self.home, "ledger")
        for name in sorted(os.listdir(ledger)):
            with open(os.path.join(ledger, name)) as handle:
                lines += [json.loads(l) for l in handle if l.strip()]
        stops = [l for l in lines if l["event"] == "agent_stop"]
        self.assertEqual(len(stops), 1)
        return stops[0]

    def test_workflow_agent_gets_run_label_and_phase(self):
        line = self.stop("sub/workflows/wf_abc", '{"agentType":"delegate:runner","description":"gate 1: x","workflowPhase":"Gate","spawnDepth":1}')
        self.assertEqual((line["run"], line["label"], line["phase"]), ("wf_abc", "gate 1: x", "Gate"))
        self.assertEqual(line["requests"], 1)   # the rest of the line is as before

    def test_hand_started_agent_gets_no_field_and_no_text(self):
        line = self.stop("sub", '{"agentType":"delegate:runner","description":"Gate the eval fix after master merge"}')
        self.assertFalse({"run", "label", "phase"} & set(line))
        self.assertNotIn("eval fix", json.dumps(line))

    def test_label_outside_the_stage_grammar_is_not_stored(self):
        line = self.stop("sub/workflows/wf_abc", '{"description":"Gate the eval fix","workflowPhase":"Gate"}')
        self.assertEqual(line["run"], "wf_abc")
        self.assertFalse({"label", "phase"} & set(line))
        self.assertNotIn("eval fix", json.dumps(line))

    def test_missing_meta_adds_no_label_and_still_writes_the_line(self):
        line = self.stop("sub/workflows/wf_abc", None)
        self.assertFalse({"label", "phase"} & set(line))
        self.assertEqual(line["requests"], 1)

    def test_meta_is_read_only_to_its_first_4_kb(self):
        """A description placed after 4096 bytes is never seen (the file is 100 KB)."""
        late = '{"pad":"%s","description":"gate 1: x"}' % ("a" * 100000)
        line = self.stop("sub/workflows/wf_abc", late)
        self.assertNotIn("label", line)


if __name__ == "__main__":
    unittest.main()
