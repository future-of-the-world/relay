"""docs/macos.md: the recommended PATH fix must not shadow python3; numbers must agree."""
import pathlib
import re
import unittest

DOC = (pathlib.Path(__file__).resolve().parent.parent / "docs" / "macos.md").read_text()


class MacosDoc(unittest.TestCase):
    def test_path_line_does_not_use_whole_developer_tools_folder(self) -> None:
        # F1: dirname of xcrun's git is the folder that also holds python3 3.9.
        self.assertNotIn('$(dirname "$(xcrun --find git)")', DOC)

    def test_git_only_folder_with_symlink(self) -> None:
        # F1 pass cases 2 and 3: a symlink folder, and the reason why not the whole folder.
        self.assertIn('ln -sf "$(xcrun --find git)"', DOC)
        self.assertRegex(DOC, r"python3.{0,10}3\.9")

    def test_the_recipe_lays_all_three_links_and_gives_the_measured_numbers(self) -> None:
        # a bare symlink makes git look for its helpers next to the link (29 Oct): bin, libexec/git-core and share/git-core
        for link in ("$HOME/.local/bin/git", "$HOME/.local/libexec/git-core", "$HOME/.local/share/git-core"):
            self.assertIn(link, DOC)
        self.assertNotIn("git-bin", DOC)   # the old recipe's folder, which broke git
        self.assertIn("20.9 ms per start", DOC)
        self.assertIn("6.6 ms", DOC)
        self.assertIn("1225 s", DOC)
        self.assertIn("720 s", DOC)

    def test_homebrew_alternative_and_decision_stay(self) -> None:
        self.assertIn("Homebrew", DOC)
        self.assertIn("relay does not change `PATH`", DOC)

    def test_extra_cost_matches_measured_means(self) -> None:
        # F2: 11.8 - 4.1 = 7.7 ms, so "8-12 ms more" contradicts the example.
        self.assertNotIn("8-12 ms", DOC)
        self.assertIn("11.8 ms against 4.1 ms", DOC)
        self.assertIn("30 interleaved rounds", DOC)
        self.assertTrue(re.search(r"29,000", DOC) and "81%" in DOC)

    def test_python_share_explains_the_5_10_percent(self) -> None:
        # F3: 1-1.5% (own logic) + 4-7% (child interpreter starts) ~ 5-10% ceiling.
        self.assertIn("1-1.5%", DOC)
        self.assertNotIn("about 1.5% of the test suite", DOC)
        self.assertIn("744 `python3` runs", DOC)
        self.assertIn("4-7%", DOC)
        self.assertIn("at most 5-10%", DOC)


if __name__ == "__main__":
    unittest.main()
