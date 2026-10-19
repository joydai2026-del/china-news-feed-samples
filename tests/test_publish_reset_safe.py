"""Offline: overwriting publish_deleted_today.sh mid-run (as its own git reset does) must not change what runs.
git/gh/python3 are stubbed on PATH; nothing touches the network or any live checkout."""
import os, shutil, stat, subprocess

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "tools", "publish_deleted_today.sh")
# Same length-ish but different: a copy that would build WITHOUT --history and print a marker.
EVIL = "#!/usr/bin/env bash\necho EVIL_REWRITE_RAN\npython3 tools/build_deleted_today.py no-history\n" + "#" * 4000 + "\n"


def _stub(d, name, body):
    p = d / name
    p.write_text("#!/usr/bin/env bash\n" + body)
    p.chmod(p.stat().st_mode | stat.S_IEXEC)


def test_overwrite_mid_run_does_not_change_execution(tmp_path):
    script = tmp_path / "publish.sh"
    shutil.copy(SCRIPT, script)
    out = tmp_path / "out"; out.mkdir()
    (tmp_path / "history.sqlite").write_text("")
    repo = tmp_path / "repo"; (repo / ".git").mkdir(parents=True)
    bin_ = tmp_path / "bin"; bin_.mkdir()
    log = tmp_path / "calls.log"
    _stub(bin_, "git", f'echo "git $*" >> "{log}"\n'
          f'if [ "$1" = reset ]; then cat > "{script}" <<\'X\'\n{EVIL}X\nfi\n'
          'if [ "$1" = diff ]; then exit 0; fi\n')
    _stub(bin_, "gh", f'echo "gh $*" >> "{log}"; exit 1\n')
    _stub(bin_, "python3", f'echo "python3 $*" >> "{log}"\n')
    env = {"PATH": f"{bin_}:/usr/bin:/bin", "CMF_OUTPUT": str(out), "PAGES_REPO_DIR": str(repo),
           "HOME": str(tmp_path), "TMPDIR": str(tmp_path)}
    r = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, timeout=30)
    calls = log.read_text().splitlines()
    assert r.returncode == 0, r.stderr
    assert "EVIL_REWRITE_RAN" not in r.stdout
    assert "no change" in r.stdout
    assert "EVIL_REWRITE_RAN" in script.read_text()  # the file really was replaced mid-run
    builds = [c for c in calls if c.startswith("python3 ")]
    assert len(builds) == 1 and "--history" in builds[0] and str(tmp_path / "history.sqlite") in builds[0]
    assert any(c.startswith("git reset -q --hard origin/main") for c in calls)
    assert not any("push" in c or c.startswith("gh ") for c in calls)


def test_script_ends_with_main_call():
    lines = [l for l in open(SCRIPT).read().splitlines() if l.strip()]
    assert lines[-1] == 'main "$@"; exit'
    assert "main() {" in lines
