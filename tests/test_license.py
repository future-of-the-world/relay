"""relay license: add, refuse on differ, check (missing, changed, headers), and setup --license."""
import os
import tomllib
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from relay_testbase import Base, ROOT  # noqa: E402
from test_gate import Fixture, git, read, write  # noqa: E402

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
        relay_license.add(root, "Apache-2.0", "amidman", 2026)
        with open(os.path.join(ROOT, "data", "licenses", "Apache-2.0.txt"), encoding="utf-8", newline="") as handle:
            bundled = handle.read()
        self.assertEqual(self.read(root, "LICENSE"), bundled)
        self.assertEqual(self.read(root, "LICENSES/Apache-2.0.txt"), bundled)
        self.assertEqual(self.read(root, "REUSE.toml").count("2026 amidman"), 1)

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
        # LICENSE, LICENSES/MIT.txt and REUSE.toml are all missing: three lines
        self.assertEqual(len(relay_license.check(root)), 3)
        self.assertIn("LICENSE is missing", relay_license.check(root)[0])
        relay_license.add(root, "MIT", "amidman", 2019)   # any year is fine
        self.assertEqual(relay_license.check(root), [])
        self.write(root, "LICENSE", self.read(root, "LICENSE").replace("Permission", "Permissions"))
        self.assertEqual(relay_license.check(root), ["LICENSE differs from the bundled MIT text"])
        # a different holder is a difference too
        self.write(root, "LICENSE", self.read(root, "LICENSE").replace("Permissions", "Permission").replace("amidman", "someone"))
        self.assertEqual(len(relay_license.check(root)), 1)

    def test_check_cli_exit_codes_one_line_per_problem(self):
        root = self.proj(kit='[license]\nid = "MIT"\nholder = "amidman"\nheaders = ["code", "config"]\n', files={"a.py": "x = 1\n", "b.sh": "echo\n"})
        r = self.cli("check", "-C", root)
        self.assertEqual(r.returncode, 1)
        # LICENSE, LICENSES/MIT.txt, REUSE.toml missing, then .claude/kit.toml (config group), a.py, b.sh (code group)
        self.assertEqual(len(r.stdout.strip().split("\n")), 6)
        self.assertEqual(self.cli("add", "MIT", "--holder", "amidman", "--headers", "code,config", "-C", root).returncode, 0)
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
        root = self.proj(kit='[license]\nid = "MIT"\nholder = "amidman"\nheaders = ["code"]\n', files=files)
        relay_license.add(root, "MIT", "amidman")
        problems = relay_license.check(root)
        # only the code files without the MIT line in the first 5 lines; json, md, txt, log never (kit.toml is config, not asked)
        self.assertEqual(sorted(p.split(":")[0] for p in problems), ["late_line6.py", "wrong_id.rs"])

    def test_add_headers_after_shebang_and_encoding_line_and_is_repeatable(self):
        import relay_license
        files = {"run.sh": "#!/bin/sh\necho hi\n", "m.py": "#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\nimport os\n",
                 "c.go": "package x\n", "d.json": "{}\n", "w.py": "a = 1\r\nb = 2\r\n"}
        root = self.proj(files=files)
        relay_license.add(root, "MIT", "amidman", 2026, headers=["code"])
        self.assertEqual(self.read(root, "run.sh"), "#!/bin/sh\n# SPDX-License-Identifier: MIT\necho hi\n")
        self.assertEqual(self.read(root, "m.py"), "#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\n# SPDX-License-Identifier: MIT\nimport os\n")
        self.assertEqual(self.read(root, "c.go"), "// SPDX-License-Identifier: MIT\npackage x\n")
        self.assertEqual(self.read(root, "d.json"), "{}\n")
        self.assertEqual(self.read(root, "w.py"), "# SPDX-License-Identifier: MIT\r\na = 1\r\nb = 2\r\n")
        before = {n: self.read(root, n) for n in files}
        relay_license.add(root, "MIT", "amidman", 2026, headers=["code"])
        self.assertEqual(before, {n: self.read(root, n) for n in files})


class SetupLicense(Base):
    def run_setup(self, **kw):
        import relay_setup
        proj = os.path.join(self.tmp, "p")
        os.makedirs(proj)
        subprocess.run(["git", "init", "-q", proj], check=True)
        with open(os.path.join(proj, "go.mod"), "w") as handle:
            handle.write("module x\n")
        relay_setup.setup(proj, install_runner=lambda r, k: (True, ""), **kw)
        return proj

    def test_setup_with_license_writes_table_license_and_no_check_step(self):
        import tomllib
        proj = self.run_setup(license_id="MIT", holder="amidman")
        with open(os.path.join(proj, ".claude", "kit.toml"), "rb") as handle:
            self.assertEqual(tomllib.load(handle)["license"], {"id": "MIT", "holder": "amidman"})
        self.assertIn("amidman", open(os.path.join(proj, "LICENSE")).read())
        self.assertTrue(os.path.isfile(os.path.join(proj, "LICENSES", "MIT.txt")))
        self.assertTrue(os.path.isfile(os.path.join(proj, "REUSE.toml")))
        # the gate runs the license check itself: no license step in bin/check
        self.assertNotIn("license", open(os.path.join(proj, "bin", "check")).read())

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
            relay_setup.setup(proj, license_id="MIT")
        self.assertFalse(os.path.exists(os.path.join(proj, ".claude")))

    def test_setup_keeps_a_different_license_and_says_what_to_do(self):
        import relay_setup
        proj = os.path.join(self.tmp, "p")
        os.makedirs(proj)
        open(os.path.join(proj, "LICENSE"), "w").write("mine\n")
        d, flow, done, todo = relay_setup.setup(proj, install_runner=lambda r, k: (True, ""), license_id="MIT", holder="a")
        self.assertEqual(open(os.path.join(proj, "LICENSE")).read(), "mine\n")
        self.assertTrue(any("mv LICENSE" in t for t in todo))


def tomls(root, name):
    with open(os.path.join(root, name), "rb") as handle:
        return tomllib.load(handle)


def run(cwd, *cmd):
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True)


class ReuseLayout(License):
    def gitproj(self, kit=None, files=None):
        root = self.proj(kit, files)
        run(root, "git", "init", "-q")
        run(root, "git", "add", "-A")
        return root

    def test_f1_add_writes_the_reuse_layout(self):
        root = self.proj()
        self.assertEqual(self.cli("add", "MIT", "--holder", "amidman", "--year", "2026", "-C", root).returncode, 0)
        self.assertEqual(self.read(root, "LICENSE"), self.read(root, "LICENSES/MIT.txt"))
        self.assertEqual(tomls(root, "REUSE.toml")["annotations"], [{"path": "**", "precedence": "closest",
                         "SPDX-FileCopyrightText": "2026 amidman", "SPDX-License-Identifier": "MIT"}])
        self.assertEqual(tomls(root, ".claude/kit.toml")["license"], {"id": "MIT", "holder": "amidman"})
        r = self.cli("check", "-C", root)
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_f1_second_add_changes_no_file(self):
        root = self.proj()
        self.cli("add", "MIT", "--holder", "amidman", "--year", "2026", "-C", root)
        names = ["LICENSE", "LICENSES/MIT.txt", "REUSE.toml", ".claude/kit.toml"]
        before = {n: self.read(root, n) for n in names}
        self.assertEqual(self.cli("add", "MIT", "--holder", "amidman", "--year", "2026", "-C", root).returncode, 0)
        self.assertEqual(before, {n: self.read(root, n) for n in names})

    def test_f1_differing_license_refused_and_nothing_else_written(self):
        root = self.proj(files={"LICENSE": "mine\n"})
        self.assertEqual(self.cli("add", "MIT", "--holder", "amidman", "-C", root).returncode, 1)
        self.assertFalse(os.path.exists(os.path.join(root, "LICENSES")))
        self.assertFalse(os.path.exists(os.path.join(root, "REUSE.toml")))
        self.assertNotIn("license", self.read(root, ".claude/kit.toml") if os.path.exists(os.path.join(root, ".claude/kit.toml")) else "")

    def test_f1_kit_toml_other_tables_stay_byte_for_byte(self):
        kit = '[project]\nname = "x"\n'
        root = self.proj(kit=kit)
        self.cli("add", "MIT", "--holder", "amidman", "-C", root)
        self.assertTrue(self.read(root, ".claude/kit.toml").startswith(kit))
        self.assertEqual(tomls(root, ".claude/kit.toml")["license"]["id"], "MIT")

    def test_f2_check_names_the_three_reuse_problems(self):
        import relay_license
        root = self.gitproj(kit='[license]\nid = "MIT"\nholder = "me"\n', files={"vendor/lib/z.c": "int x;\n"})
        self.write(root, "LICENSE", relay_license.license_text("MIT", "me", 2026))
        r = self.cli("check", "-C", root)
        lines = r.stdout.strip().split("\n")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[0].startswith("LICENSES/MIT.txt") and lines[1].startswith("REUSE.toml") and lines[2].startswith("vendor/"))

    def test_f2_wrong_id_and_changed_licenses_file_one_line_each(self):
        root = self.proj()
        self.cli("add", "MIT", "--holder", "me", "-C", root)
        self.write(root, "REUSE.toml", self.read(root, "REUSE.toml").replace('"MIT"', '"Apache-2.0"'))
        r = self.cli("check", "-C", root)
        self.assertEqual((r.returncode, len(r.stdout.strip().split("\n"))), (1, 1))
        self.assertIn("REUSE.toml", r.stdout)
        self.cli("add", "MIT", "--holder", "me", "-C", self.proj())   # no-op on a fresh dir; restore the file for the next case
        self.write(root, "REUSE.toml", self.read(root, "REUSE.toml").replace('"Apache-2.0"', '"MIT"'))
        self.write(root, "LICENSES/MIT.txt", self.read(root, "LICENSES/MIT.txt").replace("Permission", "Permissions"))
        r = self.cli("check", "-C", root)
        self.assertEqual((r.returncode, r.stdout.count("\n")), (1, 1))
        self.assertIn("LICENSES/MIT.txt differs", r.stdout)

    def test_f2_annotated_vendor_untracked_node_modules_and_old_year_are_fine(self):
        root = self.gitproj(kit='[license]\nid = "MIT"\nholder = "me"\n', files={"vendor/x.c": "int x;\n", ".gitignore": "node_modules/\n"})
        self.cli("add", "MIT", "--holder", "me", "--year", "2019", "-C", root)
        self.write(root, "node_modules/m.js", "x\n")
        self.write(root, "REUSE.toml", self.read(root, "REUSE.toml") + '\n[[annotations]]\npath = "vendor/**"\nprecedence = "closest"\n'
                   'SPDX-FileCopyrightText = "them"\nSPDX-License-Identifier = "Apache-2.0"\n')
        run(root, "git", "add", "-A")
        r = self.cli("check", "-C", root)
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_f4_headers_never_touch_vendored_or_foreign_spdx_files(self):
        root = self.gitproj(files={"vendor/lib/z.c": "int x;\n", "a/b/node_modules/m.js": "m\n", "a.py": "x = 1\n",
                                   "third_party/t.c": "// SPDX-License-Identifier: Apache-2.0\nint y;\n", "src/x.py": "# SPDX-License-Identifier: Apache-2.0\n"})
        r = self.cli("add", "MIT", "--holder", "me", "--headers", "code", "-C", root)
        self.assertIn("header line added to 1 file(s)", r.stdout)
        self.assertEqual(self.read(root, "vendor/lib/z.c"), "int x;\n")
        self.assertEqual(self.read(root, "a/b/node_modules/m.js"), "m\n")
        self.assertEqual(self.read(root, "third_party/t.c"), "// SPDX-License-Identifier: Apache-2.0\nint y;\n")
        self.assertEqual(self.read(root, "src/x.py"), "# SPDX-License-Identifier: Apache-2.0\n")
        self.assertEqual(self.read(root, "a.py"), "# SPDX-License-Identifier: MIT\nx = 1\n")
        # a foreign id is reported by check as a header problem
        # (the two tracked vendored folders without headers are reported too; third_party/ has its own SPDX line)
        self.assertEqual([p.split(":")[0].split(" ")[0] for p in self.cli("check", "-C", root).stdout.strip().split("\n")],
                         ["a/b/node_modules/", "vendor/", "src/x.py"])

    def test_f4_walk_outside_git_skips_vendor(self):
        root = self.proj(files={"vendor/z.c": "int x;\n", "a.py": "x\n"})
        self.cli("add", "MIT", "--holder", "me", "--headers", "code", "-C", root)
        self.assertEqual(self.read(root, "vendor/z.c"), "int x;\n")

    def test_f5_header_groups(self):
        files = {"Dockerfile": "FROM x\n", "Makefile": "all:\n", "a.java": "class A {}\n", "b.yaml": "k: v\n", "c.md": "# t\n",
                 "x.toml": "a = 1\n", "data.json": "{}\n", "package-lock.json": "{}\n", "Cargo.lock": "x\n"}
        root = self.proj(files=files)
        self.cli("add", "MIT", "--holder", "me", "--headers", "code", "-C", root)
        line = "SPDX-License-Identifier: MIT"
        self.assertEqual(self.read(root, "Dockerfile"), "# " + line + "\nFROM x\n")
        self.assertEqual(self.read(root, "Makefile"), "# " + line + "\nall:\n")
        self.assertEqual(self.read(root, "a.java"), "// " + line + "\nclass A {}\n")
        for name in ("b.yaml", "c.md", "x.toml"):
            self.assertEqual(self.read(root, name), files[name])

    def test_f5_docs_and_config_groups(self):
        files = {"b.yaml": "k: v\n", "c.md": "# t\n", "x.toml": "a = 1\n", "data.json": "{}\n", "package-lock.json": "{}\n", "Cargo.lock": "x\n", "a.py": "a\n"}
        root = self.proj(files=files)
        self.cli("add", "MIT", "--holder", "me", "--headers", "docs", "-C", root)
        self.assertEqual(self.read(root, "c.md"), "<!-- SPDX-License-Identifier: MIT -->\n# t\n")
        self.assertEqual(self.read(root, "b.yaml"), files["b.yaml"])
        root = self.proj(files=files)   # same folder, config group now (kit.toml records docs: ask for the same groups)
        self.assertEqual(self.cli("add", "MIT", "--holder", "me", "--headers", "docs", "--headers", "config", "-C", root).returncode, 1)

    def test_f5_config_group_alone(self):
        files = {"b.yaml": "k: v\n", "c.md": "# t\n", "x.toml": "a = 1\n", "data.json": "{}\n", "package-lock.json": "{}\n", "Cargo.lock": "x\n"}
        root = self.proj(files=files)
        self.cli("add", "MIT", "--holder", "me", "--headers", "config", "-C", root)
        self.assertEqual(self.read(root, "b.yaml"), "# SPDX-License-Identifier: MIT\nk: v\n")
        self.assertEqual(self.read(root, "x.toml"), "# SPDX-License-Identifier: MIT\na = 1\n")
        for name in ("c.md", "data.json", "package-lock.json", "Cargo.lock"):
            self.assertEqual(self.read(root, name), files[name])

    def test_f5_no_headers_flag_changes_no_source_and_check_asks_none(self):
        root = self.proj(files={"a.py": "x\n"})
        self.cli("add", "MIT", "--holder", "me", "-C", root)
        self.assertEqual(self.read(root, "a.py"), "x\n")
        self.assertEqual(self.cli("check", "-C", root).stdout, "")

    def test_f5_kit_headers_list_decides_which_files_check_lists(self):
        root = self.proj(kit='[license]\nid = "MIT"\nholder = "me"\nheaders = ["code"]\n', files={"a.py": "x\n", "b.yaml": "k: v\n"})
        self.cli("add", "MIT", "--holder", "me", "-C", root)
        out = self.cli("check", "-C", root).stdout
        self.assertIn("a.py", out)
        self.assertNotIn("b.yaml", out)

    def test_f6_isc_names_the_holder_not_isc(self):
        root = self.proj()
        self.assertEqual(self.cli("add", "ISC", "--holder", "me", "--year", "2026", "-C", root).returncode, 0)
        text = self.read(root, "LICENSE")
        self.assertIn("Copyright (c) 2026 me", text)
        self.assertNotIn("Internet Systems Consortium", text)
        self.assertEqual(self.cli("check", "-C", root).stdout, "")
        self.assertEqual(self.cli("add", "ISC", "-C", self.proj()).returncode, 1)

    def test_f7_year_must_be_four_digits(self):
        root = self.proj()
        r = self.cli("add", "MIT", "--holder", "me", "--year", "99", "-C", root)
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(root, "LICENSE")))
        self.assertEqual(self.cli("add", "MIT", "--holder", "me", "--year", "2019", "-C", root).returncode, 0)
        self.assertEqual(self.cli("check", "-C", root).stdout, "")

    def test_f8_unreadable_file_is_named_and_skipped(self):
        root = self.proj(files={"a.py": "x\n"})
        with open(os.path.join(root, "b.c"), "wb") as handle:
            handle.write(b"int caf\xe9;\n")
        r = self.cli("add", "MIT", "--holder", "me", "--headers", "code", "-C", root)
        self.assertEqual(r.returncode, 0)
        self.assertIn("b.c: not readable as text", r.stdout)
        self.assertEqual(self.read(root, "a.py"), "# SPDX-License-Identifier: MIT\nx\n")
        with open(os.path.join(root, "b.c"), "rb") as handle:
            self.assertEqual(handle.read(), b"int caf\xe9;\n")


class GateRunsLicenseCheck(Fixture):
    def lic_repo(self, license_files: bool, table: bool = True):
        import relay_license
        self.repo(gate="exit 0\n")
        kit = os.path.join(self.wt, ".claude", "kit.toml")
        write(kit, read(kit) + ('[license]\nid = "MIT"\nholder = "me"\n' if table else ""))
        if license_files:
            relay_license.add(self.wt, "MIT", "me", 2026)
        git(self.wt, "add", "-A")
        git(self.wt, "commit", "-q", "--allow-empty", "-m", "license")

    def log(self):
        return read(os.path.join(self.wt, ".relay", "checks", git(self.wt, "rev-parse", "HEAD~1") + ".gate.log"))

    def test_f3_missing_license_fails_the_gate_and_the_log_names_it(self):
        self.lic_repo(license_files=False)
        run_ = self.gate(self.wt)
        self.assertEqual(run_.returncode, 1)
        self.assertIn("LICENSE is missing", self.log())

    def test_f3_good_license_files_gate_is_green(self):
        self.lic_repo(license_files=True)
        self.assertEqual(self.gate(self.wt).returncode, 0)

    def test_f3_without_license_table_the_log_has_no_license_line(self):
        self.lic_repo(license_files=False, table=False)
        self.assertEqual(self.gate(self.wt).returncode, 0)
        # the cmd line holds the temporary folder, whose name carries the test's own name (it says "license")
        self.assertNotIn("license", "\n".join(l for l in self.log().splitlines() if not l.startswith("cmd ")).lower())


if __name__ == "__main__":
    unittest.main()
