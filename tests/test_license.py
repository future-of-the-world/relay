"""relay license: add, refuse on differ, check (missing, changed, headers), and setup --license."""
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from relay_testbase import Base, ROOT  # noqa: E402

RELAY = os.path.join(ROOT, "bin", "relay")


class License(Base):
    def proj(self, kit=None, files=None):
        root = os.path.join(self.tmp, "proj")
        os.makedirs(os.path.join(root, ".claude"), exist_ok=True)
        if kit is not None:
            self.write(root, ".claude/kit.toml", kit)
        for name, text in (files or {}).items():
            self.write(root, name, text)
        return root

    def write(self, root, name, text):
        path = os.path.join(root, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)

    def read(self, root, name):
        with open(os.path.join(root, name), encoding="utf-8", newline="") as handle:
            return handle.read()

    def cli(self, *args):
        return subprocess.run([sys.executable, RELAY, "license", *args], capture_output=True, text=True, env={**os.environ, "RELAY_ROOT": ROOT})

    def test_add_mit_fills_year_and_holder(self):
        import relay_license
        root = self.proj()
        relay_license.add(root, "MIT", "amidman", 2026)
        lines = self.read(root, "LICENSE").split("\n")
        # SPDX MIT text: line 1 "MIT License", line 3 the copyright line with <year> <copyright holders>
        self.assertEqual(lines[0], "MIT License")
        self.assertEqual(lines[2], "Copyright (c) 2026 amidman")
        self.assertNotIn("<", self.read(root, "LICENSE"))

    def test_text_without_holder_line_is_written_as_is(self):
        import relay_license
        root = self.proj()
        said = relay_license.add(root, "Apache-2.0", "amidman", 2026)
        with open(os.path.join(ROOT, "data", "licenses", "Apache-2.0.txt"), encoding="utf-8", newline="") as handle:
            self.assertEqual(self.read(root, "LICENSE"), handle.read())
        self.assertTrue(any("SPDX-FileCopyrightText: 2026 amidman" in s for s in said))

    def test_holder_required_where_the_text_has_one(self):
        import relay_license
        with self.assertRaisesRegex(ValueError, "--holder"):
            relay_license.add(self.proj(), "BSD-3-Clause")

    def test_unknown_id_names_the_bundled_ones(self):
        import relay_license
        with self.assertRaisesRegex(ValueError, "MIT"):
            relay_license.add(self.proj(), "WTFPL", "x")

    def test_add_refuses_a_different_license_and_changes_nothing(self):
        root = self.proj(files={"LICENSE": "my own terms\n"})
        r = self.cli("add", "MIT", "--holder", "amidman", "-C", root)
        self.assertEqual(r.returncode, 1)
        self.assertIn("mv LICENSE", r.stderr)
        self.assertEqual(self.read(root, "LICENSE"), "my own terms\n")

    def test_add_twice_is_quiet_success(self):
        root = self.proj()
        self.assertEqual(self.cli("add", "MIT", "--holder", "amidman", "--year", "2026", "-C", root).returncode, 0)
        r = self.cli("add", "MIT", "--holder", "amidman", "--year", "2026", "-C", root)
        self.assertEqual(r.returncode, 0)
        self.assertIn("nothing changed", r.stdout)

    def test_check_without_license_table_does_nothing(self):
        import relay_license
        self.assertEqual(relay_license.check(self.proj(kit='[project]\nname = "x"\n')), [])
        self.assertEqual(relay_license.check(self.proj()), [])

    def test_check_missing_changed_and_good(self):
        import relay_license
        root = self.proj(kit='[license]\nid = "MIT"\nholder = "amidman"\n')
        self.assertEqual(len(relay_license.check(root)), 1)
        self.assertIn("LICENSE is missing", relay_license.check(root)[0])
        relay_license.add(root, "MIT", "amidman", 2019)   # any year is fine
        self.assertEqual(relay_license.check(root), [])
        self.write(root, "LICENSE", self.read(root, "LICENSE").replace("Permission", "Permissions"))
        self.assertEqual(relay_license.check(root), ["LICENSE differs from the bundled MIT text"])
        # a different holder is a difference too
        self.write(root, "LICENSE", self.read(root, "LICENSE").replace("Permissions", "Permission").replace("amidman", "someone"))
        self.assertEqual(len(relay_license.check(root)), 1)

    def test_check_cli_exit_codes_one_line_per_problem(self):
        root = self.proj(kit='[license]\nid = "MIT"\nholder = "amidman"\nheaders = true\n', files={"a.py": "x = 1\n", "b.sh": "echo\n"})
        r = self.cli("check", "-C", root)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(len(r.stdout.strip().split("\n")), 4)   # LICENSE missing, .claude/kit.toml (toml is a code extension), a.py, b.sh
        self.assertEqual(self.cli("add", "MIT", "--holder", "amidman", "--headers", "-C", root).returncode, 0)
        r = self.cli("check", "-C", root)
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_headers_are_checked_only_when_asked(self):
        import relay_license
        root = self.proj(kit='[license]\nid = "MIT"\nholder = "amidman"\n', files={"a.py": "x = 1\n"})
        relay_license.add(root, "MIT", "amidman")
        self.assertEqual(relay_license.check(root), [])

    def test_header_rules_by_extension_and_position(self):
        import relay_license
        mit = "SPDX-License-Identifier: MIT"
        files = {
            "ok_line5.py": "a\nb\nc\nd\n# " + mit + "\n",
            "late_line6.py": "a\nb\nc\nd\ne\n# " + mit + "\n",
            "ok.go": "// " + mit + "\npackage x\n",
            "wrong_id.rs": "// SPDX-License-Identifier: GPL-3.0-or-later\n",
            "data.json": "{}\n", "README.md": "text\n", "notes.txt": "t\n", "run.log": "l\n",
        }
        root = self.proj(kit='[license]\nid = "MIT"\nholder = "amidman"\nheaders = true\n', files=files)
        relay_license.add(root, "MIT", "amidman")
        problems = relay_license.check(root)
        # only the code files without the MIT line in the first 5 lines; json, md, txt, log never
        self.assertEqual(sorted(p.split(":")[0] for p in problems), [".claude/kit.toml", "late_line6.py", "wrong_id.rs"])

    def test_add_headers_after_shebang_and_encoding_line_and_is_repeatable(self):
        import relay_license
        files = {"run.sh": "#!/bin/sh\necho hi\n", "m.py": "#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\nimport os\n",
                 "c.go": "package x\n", "d.json": "{}\n", "w.py": "a = 1\r\nb = 2\r\n"}
        root = self.proj(files=files)
        relay_license.add(root, "MIT", "amidman", 2026, headers=True)
        self.assertEqual(self.read(root, "run.sh"), "#!/bin/sh\n# SPDX-License-Identifier: MIT\necho hi\n")
        self.assertEqual(self.read(root, "m.py"), "#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\n# SPDX-License-Identifier: MIT\nimport os\n")
        self.assertEqual(self.read(root, "c.go"), "// SPDX-License-Identifier: MIT\npackage x\n")
        self.assertEqual(self.read(root, "d.json"), "{}\n")
        self.assertEqual(self.read(root, "w.py"), "# SPDX-License-Identifier: MIT\r\na = 1\r\nb = 2\r\n")
        before = {n: self.read(root, n) for n in files}
        relay_license.add(root, "MIT", "amidman", 2026, headers=True)
        self.assertEqual(before, {n: self.read(root, n) for n in files})


class SetupLicense(Base):
    def run_setup(self, **kw):
        import relay_setup
        proj = os.path.join(self.tmp, "p")
        os.makedirs(proj)
        subprocess.run(["git", "init", "-q", proj], check=True)
        with open(os.path.join(proj, "go.mod"), "w") as handle:
            handle.write("module x\n")
        relay_setup.setup(proj, flow="none", product=False, apply_global=False, install_runner=lambda r, k: (True, ""), **kw)
        return proj

    def test_setup_with_license_writes_table_license_and_check_step(self):
        import tomllib
        proj = self.run_setup(license_id="MIT", holder="amidman")
        with open(os.path.join(proj, ".claude", "kit.toml"), "rb") as handle:
            self.assertEqual(tomllib.load(handle)["license"], {"id": "MIT", "holder": "amidman"})
        self.assertIn("amidman", open(os.path.join(proj, "LICENSE")).read())
        self.assertIn("run_step license relay license check", open(os.path.join(proj, "bin", "check")).read())

    def test_setup_without_license_writes_nothing_about_licenses(self):
        proj = self.run_setup()
        self.assertNotIn("license", open(os.path.join(proj, ".claude", "kit.toml")).read().lower())
        self.assertFalse(os.path.exists(os.path.join(proj, "LICENSE")))
        self.assertNotIn("license", open(os.path.join(proj, "bin", "check")).read())

    def test_setup_license_needs_holder_and_writes_nothing_without(self):
        import relay_setup
        proj = os.path.join(self.tmp, "p")
        os.makedirs(proj)
        with self.assertRaises(ValueError):
            relay_setup.setup(proj, flow="none", product=False, apply_global=False, license_id="MIT")
        self.assertFalse(os.path.exists(os.path.join(proj, ".claude")))

    def test_setup_keeps_a_different_license_and_says_what_to_do(self):
        import relay_setup
        proj = os.path.join(self.tmp, "p")
        os.makedirs(proj)
        open(os.path.join(proj, "LICENSE"), "w").write("mine\n")
        d, flow, product, done, todo = relay_setup.setup(proj, flow="none", product=False, apply_global=False, install_runner=lambda r, k: (True, ""), license_id="MIT", holder="a")
        self.assertEqual(open(os.path.join(proj, "LICENSE")).read(), "mine\n")
        self.assertTrue(any("mv LICENSE" in t for t in todo))


if __name__ == "__main__":
    unittest.main()
