"""The library tests under unittest (what bin/ci runs) with the same temporary-folder default pytest gets."""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))  # names like tests.test_rules need the repo root

sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))

import leaked_gates
import relay_tokens
import tmp_default

def run(names: list) -> int:
    """Run the tests with TMPDIR in a folder of this run's own; any process (a `relay gate`, a script, a sleep) still living under it afterwards is a leak:
    it is stopped with its command, named, and the step fails."""
    run_dir = os.path.realpath(tempfile.mkdtemp(prefix="relay-run-"))
    saved = os.environ.get("TMPDIR")
    os.environ["TMPDIR"] = run_dir
    tempfile.tempdir = None  # tempfile re-reads TMPDIR
    try:
        tmp_default.patch_unittest()
        argv = ["unittest", *names] if names else ["unittest", "discover", "-s", HERE, "-p", "test_*.py"]
        program = unittest.main(module=None, argv=argv, exit=False)
        code = 0 if program.result.wasSuccessful() else 1
        notes: list = []
        leaked = leaked_gates.stop(run_dir, notes)
        for note in notes:
            print("NOTE leak scan: " + note)
        for pid, command in leaked:
            print("FAIL leaked process: pid %d was still running after the tests, in a temporary folder of the run (stopped): %s" % (pid, command))
        return 1 if leaked else code
    finally:
        if saved is None:
            os.environ.pop("TMPDIR", None)
        else:
            os.environ["TMPDIR"] = saved
        tempfile.tempdir = None
        shutil.rmtree(run_dir, ignore_errors=True)


def run_held(names: list) -> int:
    """`run` in this one process, on a test token: the base its holder passed down, else one shared token taken here (waiting)."""
    base = relay_tokens.acquire_run_base(dict(os.environ), lambda line: print("tests: " + line, flush=True))
    try:
        return run(names)
    finally:
        base.held.release()


def main(argv: list) -> int:
    """Names given: run them in this process. None: every library test, on RELAY_TEST_JOBS processes split by class
    (tests/parallel_unittest.py); one job is the single process below. Every process runs on a token of the machine's pool."""
    if argv:
        return run_held(argv)
    import parallel_unittest
    jobs, note = parallel_unittest.jobs_setting(dict(os.environ))
    if jobs == 1:
        if note:
            print(note)
        return run_held([])
    return parallel_unittest.run()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
