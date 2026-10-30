"""`relay hosts` and the record of gate hosts (plan gates-on-the-vps-hosts-transport-watch-bring-up 5.7, 5.8, 5.9), against the fake host."""
import getpass
import json
import os
import subprocess
import unittest
from unittest import mock

from test_gate import ROOT, read, write
from vps_base import HOST, VpsBase

import relay_gate_ssh
import relay_hosts


class Record(VpsBase):
    def test_set_refuses_a_value_outside_its_bound_and_names_the_bound(self):
        with self.assertRaises(ValueError) as caught:
            relay_hosts.set_value(HOST, "slots", "4", self.home)
        self.assertIn("slots is a whole number from 1 to 3", str(caught.exception))
        with self.assertRaises(ValueError):
            relay_hosts.set_value(HOST, "memory_gib", "13", self.home)
        host = relay_hosts.set_value(HOST, "build_limit_s", "300", self.home)      # the bound itself is allowed
        self.assertEqual(relay_hosts.load(self.home)[HOST].get("build_limit_s"), host.get("build_limit_s"))
        self.assertEqual(relay_hosts.load(self.home)[HOST].get("slots"), 2)      # the default stays when never set
        relay_hosts.set_value(HOST, "watch_default", "off", self.home)
        self.assertFalse(relay_hosts.load(self.home)[HOST].watch_default)

    def test_a_record_that_is_not_valid_is_refused_naming_the_file(self):
        path = relay_hosts.record_path(self.home)
        for bad in ('{"hosts": {"h": {"user": "root", "settings": {}}}}', '{"hosts": {"h": {"user": "u", "settings": {"slots": 9}}}}',
                    '{"hosts": {"h": {"user": "u", "settings": {"bogus": 1}}}}', "not json"):
            with self.subTest(bad=bad):
                write(path, bad)
                with self.assertRaises(ValueError) as caught:
                    relay_hosts.load(self.home)
                self.assertIn("gate-hosts.json", str(caught.exception))

    def test_no_record_means_no_hosts(self):
        os.remove(relay_hosts.record_path(self.home))
        self.assertEqual(relay_hosts.load(self.home), {})
        self.assertIsNone(relay_hosts.first(self.home))

    def test_only_the_hosts_module_names_the_record(self):
        named = []
        for folder in ("lib", "bin"):
            for name in sorted(os.listdir(os.path.join(ROOT, folder))):
                path = os.path.join(ROOT, folder, name)
                if os.path.isfile(path) and "gate-hosts.json" in read(path):
                    named.append(folder + "/" + name)
        self.assertEqual(named, ["lib/relay_hosts.py"])

    def test_relays_code_never_passes_root_to_ssh(self):
        for name in ("relay_hosts.py", "relay_gate_ssh.py", "relay_gate_watch.py"):
            self.assertNotIn("root@", read(os.path.join(ROOT, "lib", name)), name)


class Add(VpsBase):
    def setUp(self):
        super().setUp()
        os.remove(relay_hosts.record_path(self.home))
        os.remove(os.path.join(self.home, "keys", "gate-host"))      # add makes its own key
        self.subuid = os.path.join(self.tmp, "subuid")
        write(self.subuid, getpass.getuser() + ":100000:65536\n")      # the fake host's /etc/subuid; the fake ssh runs as this user on this machine
        patcher = mock.patch.object(relay_gate_ssh, "SUBUID_FILE", self.subuid)
        patcher.start()
        self.addCleanup(patcher.stop)
        # The clean image has no ssh-keygen: a fake on PATH (as the fake ssh) writes the key pair at the -f path. add() only needs the files to
        # exist and the program to exit 0; what a real key is made of is ssh-keygen's business, not relay's.
        keygen = os.path.join(self.vps.bin, "ssh-keygen")
        write(keygen, '#!/bin/sh\nwhile [ $# -gt 0 ]; do [ "$1" = -f ] && out="$2"; shift; done\n'
                      'echo "fake private key" > "$out"; echo "ssh-ed25519 AAAAfake relay-gate" > "$out.pub"\n', 0o755)

    def test_add_proves_the_host_installs_the_program_and_records_it_without_building_or_gating(self):
        lines = relay_hosts.add(HOST, "relay-gate", self.main, self.home)
        self.assertEqual(relay_hosts.load(self.home)[HOST].user, "relay-gate")
        self.assertTrue(os.path.exists(os.path.join(self.home, "keys", "gate-host.pub")))
        self.assertEqual(read(os.path.join(self.vps.root, "home", "relay-gate-remote.py")), self.program_text())
        self.assertEqual(set(self.vps.podman_calls()), {"info"})      # no build, no create, no gate
        self.assertTrue(all(call["target"] == "relay-gate@" + HOST for call in self.vps.ssh_calls()))
        self.assertIn("recorded %s as relay-gate" % HOST, lines)

    def test_a_refused_key_prints_the_three_root_commands_and_writes_no_record(self):
        self.vps.mode({"refuse": True})
        with self.assertRaises(ValueError) as caught:
            relay_hosts.add(HOST, "relay-gate", self.main, self.home)
        text = str(caught.exception)
        for part in ("useradd --create-home --shell /bin/bash relay-gate", "install -d -m 700 -o relay-gate -g relay-gate ~relay-gate/.ssh",
                     "restrict ", "authorized_keys", "relay hosts add %s --user relay-gate" % HOST):
            self.assertIn(part, text)
        self.assertFalse(os.path.exists(relay_hosts.record_path(self.home)))
        self.assertEqual([c["target"] for c in self.vps.ssh_calls()], ["relay-gate@" + HOST])      # one login, as the gate account, never root

    def test_add_stops_and_names_a_missing_cgroup_controller(self):
        self.vps.mode({"info": "true v2 [cpu io memory]"})
        with self.assertRaises(ValueError) as caught:
            relay_hosts.add(HOST, "relay-gate", self.main, self.home)
        self.assertIn("pids", str(caught.exception))
        self.assertFalse(os.path.exists(relay_hosts.record_path(self.home)))

    def test_add_stops_when_the_account_has_no_subuid_range(self):
        write(self.subuid, "someone-else:100000:65536\n")
        with self.assertRaises(ValueError) as caught:
            relay_hosts.add(HOST, "relay-gate", self.main, self.home)
        self.assertIn("subuid", str(caught.exception))
        self.assertFalse(os.path.exists(relay_hosts.record_path(self.home)))

    def test_add_refuses_root(self):
        with self.assertRaises(ValueError):
            relay_hosts.add(HOST, "root", self.main, self.home)
        self.assertEqual(self.vps.ssh_calls(), [])


class Remove(VpsBase):
    def test_remove_deletes_the_record_and_the_key_and_prints_the_one_root_command(self):
        lines = relay_hosts.remove(HOST, self.home)
        self.assertEqual(relay_hosts.load(self.home), {})
        self.assertFalse(os.path.exists(os.path.join(self.home, "keys", "gate-host")))
        self.assertTrue(any("userdel -r relay-gate" in line for line in lines))
        self.assertEqual(self.vps.ssh_calls(), [])      # relay runs no root command


class Cli(VpsBase):
    def test_relay_hosts_set_and_status_run_from_the_command_line(self):
        run = lambda *a: subprocess.run(["python3", os.path.join(ROOT, "bin", "relay"), "hosts", *a, "-C", self.main], capture_output=True, text=True, env=self.env)
        done = run("set", HOST, "stop_after", "5")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("stop_after=5", done.stdout)
        done = run("set", HOST, "stop_after", "99")
        self.assertEqual(done.returncode, 1)
        self.assertIn("stop_after is a whole number from 1 to 10", done.stderr)
        done = run("status")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("default branch: not gated on %s yet" % HOST, done.stdout)
        self.assertIn("stop-sending rule: does not hold", done.stdout)
        json.loads(read(relay_hosts.record_path(self.home)))


if __name__ == "__main__":
    unittest.main()
