"""The `casino` and `blackjack` shell aliases: bin/casino and bin/blackjack run the games from any folder (nothing
there named casino or blackjack can be picked up instead, and the folder you're in stays yours), and
bin/install-aliases writes the aliases into a shell startup file in one marked block -- added once, updated in
place, backed up first, written through a symlink, nothing else in the file touched. (The games themselves, run
through the launchers in a terminal, are in check_ui.py.)"""
import os
import runpy
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from _support import *  # noqa: F401,F403
import _support as S

check = S.Checker()
BIN = S.REPO / "bin"
installer = runpy.run_path(str(BIN / "install-aliases"), run_name="install_aliases")
install, alias_block, BEGIN = installer["install"], installer["alias_block"], installer["BEGIN"]

# =============================================================== A. the launchers, from somewhere else
elsewhere = Path(tempfile.mkdtemp(prefix="csbj-elsewhere-"))
(elsewhere / "casino").mkdir()
(elsewhere / "casino" / "__init__.py").write_text('raise SystemExit("the decoy casino package was imported")\n')
(elsewhere / "blackjack.py").write_text('raise SystemExit("the decoy blackjack module was imported")\n')
for name, usage in (("casino", "usage: casino [-h]"), ("blackjack", "usage: blackjack [-h] [--db FILE]")):
    res = subprocess.run([sys.executable, str(BIN / name), "--help"], cwd=elsewhere, capture_output=True, text=True)
    check(res.returncode == 0 and res.stdout.startswith(usage) and "decoy" not in res.stdout + res.stderr,
          f"bin/{name} runs from another folder -- and a '{name}' sitting in that folder isn't picked up instead")
check(all(os.access(BIN / n, os.X_OK) for n in ("casino", "blackjack", "install-aliases")), "the launchers and the installer are executable")

# =============================================================== B. the installer
rc = elsewhere / "zshrc"
mine = '# my own settings\nalias ll="ls -l"\nexport EDITOR=vim\n'
rc.write_text(mine)
os.chmod(rc, 0o600)
msg = install(rc)
text = rc.read_text()
backups = list(elsewhere.glob("zshrc.bak-*"))
check(text.startswith(mine) and text.count(BEGIN) == 1 and text.endswith(alias_block()), "the alias block is added after what was there, which is untouched")
check(f"alias casino='python3 {BIN / 'casino'}'" in text and f"alias blackjack='python3 {BIN / 'blackjack'}'" in text,
      "...with `casino` and `blackjack` running this repository's launchers")
check(len(backups) == 1 and backups[0].read_text() == mine and "backup" in msg, f"the file is backed up first: {msg}")
check(stat.S_IMODE(rc.stat().st_mode) == 0o600, "...and keeps its permissions")
msg = install(rc)
check(rc.read_text() == text and len(list(elsewhere.glob("zshrc.bak-*"))) == 1 and "nothing to change" in msg,
      "running it again changes nothing (and makes no new backup)")
moved = Path("/Volumes/Somewhere Else/Baddies-Casino")
install(rc, repo=moved)
text = rc.read_text()
alias_line = next(line for line in text.splitlines() if line.startswith("alias casino="))
words = shlex.split(shlex.split(alias_line)[1].split("=", 1)[1])          # what the shell runs for `casino`
check(text.count(BEGIN) == 1 and text.startswith(mine) and words == ["python3", str(moved / "bin" / "casino")],
      f"after the repository moves, the block is updated in place -- not added twice -- quoting a path with spaces: {words}")
with open(rc, "a") as fh:
    fh.write('alias blackjack="echo something else"\n')
check("note:" in install(rc) and "`blackjack`" in install(rc, repo=moved), "a `blackjack` defined elsewhere in the file is pointed out")

dotfiles = elsewhere / "dotfiles"
dotfiles.mkdir()
(dotfiles / "zshrc").write_text(mine)
link = elsewhere / "linked-zshrc"
link.symlink_to(dotfiles / "zshrc")
install(link)
check(link.is_symlink() and BEGIN in (dotfiles / "zshrc").read_text(), "a symlinked startup file is written through, and stays a symlink")
fresh = elsewhere / "brand-new-zshrc"
install(fresh)
check(fresh.read_text() == alias_block() and not list(elsewhere.glob("brand-new-zshrc.bak-*")), "a startup file that doesn't exist yet is created, with nothing to back up")

# =============================================================== C. the aliases themselves, in zsh
zsh = shutil.which("zsh")
if zsh:
    res = subprocess.run([zsh, "-f", "-c", f"source {fresh}; cd /; eval 'casino --help'; eval 'blackjack --help'"],
                         capture_output=True, text=True)
    check(res.returncode == 0 and "usage: casino" in res.stdout and "usage: blackjack" in res.stdout,
          "in zsh, the aliases run both games from any folder")
else:
    check(True, "(no zsh on this machine -- the aliases weren't run)")

check.finish("check_launchers")
