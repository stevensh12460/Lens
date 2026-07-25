"""
web_git.py — commit and push the website repo, safely.

Mirrors the safety shape of services/post_scheduler.py, because that pattern is
already load-bearing here: dry_run defaults to True, a file-existence kill
switch, and a list of pre-flight guards that each earned their place.

The important split:

    dry_run=True   commit locally, DO NOT push.
    dry_run=False  push.

Cloudflare Pages deploys on push only, so a local commit is completely invisible
to the public. That makes dry_run a genuinely useful rehearsal — `git show HEAD`
afterwards is the real artifact, not a printed intention.

CREDENTIALS (established 2026-07-24): the git CLI on this Mac has NO stored
credential of its own. `git credential-osxkeychain get` returns nothing for
github.com, and there is no ~/.git-credentials and no ~/.netrc. Steven pushes
through GitHub Desktop, which keeps its token under its own keychain service
name that the git CLI never consults.

So LENS carries its own credential: an ed25519 **deploy key** at
~/.ssh/lens_shp_site, registered on the shp-site repo with write access, used
over the dedicated `lens` SSH remote. A fine-grained PAT was tried first and
abandoned — its account-level "Repository access" section silently stayed on
"Public repositories" across three attempts, leaving the token unable to even
see a private repo. A deploy key is configured from inside the repo itself, so
there is no such trap; it is scoped to this one repository and never expires.

`origin` is deliberately left on HTTPS so GitHub Desktop keeps working.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

from lens_core.tz import now_et

SITE_ROOT = Path.home() / "Code" / "shp-site"
BRANCH = "main"

# LENS pushes over its own SSH remote using a repo-scoped deploy key, NOT
# `origin`. Two reasons:
#   * origin stays HTTPS so GitHub Desktop, which is how Steven pushes by hand,
#     keeps working exactly as before. Nothing about his workflow changes.
#   * a deploy key is scoped to this single repository and never expires, unlike
#     a fine-grained PAT. No yearly renewal chore, and no credential that could
#     reach anything but the website if it leaked.
REMOTE = "lens"
SSH_KEY = Path.home() / ".ssh" / "lens_shp_site"

# One touch disables all website publishing, independent of launchd, exactly
# like ~/lens/AUTO_PUBLISH_DISABLED does for Instagram.
KILL_SWITCH = Path.home() / "lens" / "WEB_PUBLISH_DISABLED"

GIT_TIMEOUT = 60  # seconds; a credential prompt must fail fast, never hang


class GitGuardError(RuntimeError):
    """A pre-flight guard refused. Nothing was committed or pushed."""


@dataclass
class GitResult:
    status: str                  # unchanged | committed | pushed | committed_not_pushed
    commit_sha: Optional[str] = None
    pushed: bool = False
    detail: str = ""
    files: list[str] = field(default_factory=list)


def _git(*args: str, cwd: Path = SITE_ROOT) -> subprocess.CompletedProcess:
    """Run git with prompts disabled and the LENS deploy key bound.

    GIT_TERMINAL_PROMPT=0 matters more than it looks: without it, git blocks
    trying to read a username from a stdin that is /dev/null under launchd, and
    the request simply never returns. Failing fast beats hanging forever.

    IdentitiesOnly=yes stops ssh from offering every key in the agent first,
    which on a repo with a deploy key would authenticate as the wrong identity.
    """
    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "/usr/bin/true",
        "GIT_SSH_COMMAND": (
            f"ssh -i {SSH_KEY} -o IdentitiesOnly=yes -o BatchMode=yes "
            f"-o StrictHostKeyChecking=accept-new"
        ),
        "LC_ALL": "C",
    }
    return subprocess.run(
        ["git", *args], cwd=str(cwd), env=env, capture_output=True, text=True,
        timeout=GIT_TIMEOUT, check=False,
    )


def preflight(paths: Sequence[str], *, for_push: bool) -> None:
    """Every guard that must hold before we touch the repo. Raises on refusal."""
    if KILL_SWITCH.exists():
        raise GitGuardError(
            f"kill switch present: {KILL_SWITCH}. Remove it to re-enable "
            "website publishing."
        )

    if not (SITE_ROOT / ".git").exists():
        raise GitGuardError(f"{SITE_ROOT} is not a git repository")

    branch = _git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if branch != BRANCH:
        raise GitGuardError(f"on branch {branch!r}, refusing to publish from anything but {BRANCH!r}")

    # The working tree may be dirty ONLY in the paths this publish owns.
    # This is what stops a publish from sweeping up an unrelated half-finished
    # edit and shipping it to the live site.
    #
    # NOTE: normalise with a "./" prefix strip, NOT str.lstrip("./") — lstrip
    # takes a character SET, so it would turn ".gitignore" into "gitignore" and
    # the guard would reject a file it actually owns.
    def _norm(p: str) -> str:
        return p[2:] if p.startswith("./") else p

    owned = {_norm(p) for p in paths}
    dirty = []
    for line in _git("status", "--porcelain").stdout.splitlines():
        if not line.strip():
            continue
        entry = line[3:].strip()
        # Renames render as "old -> new"; both sides must be owned.
        parts = [e.strip().strip('"') for e in entry.split(" -> ")]
        if any(_norm(p) not in owned for p in parts):
            dirty.append(entry)
    if dirty:
        raise GitGuardError(
            "working tree has changes outside this publish: "
            + ", ".join(sorted(dirty)[:10])
            + ("..." if len(dirty) > 10 else "")
            + ". Commit or stash them first."
        )

    if not for_push:
        return

    # Remote checks need the network and a credential, so they only run for a
    # real push. Catches "he pushed from GitHub Desktop since we last fetched",
    # which would otherwise produce a rejected non-fast-forward and tempt a
    # --force. We never force.
    if not SSH_KEY.exists():
        raise GitGuardError(
            f"deploy key missing at {SSH_KEY}. Regenerate it and re-add the "
            "public half at https://github.com/stevensh12460/shp-site/settings/keys "
            'with "Allow write access" ticked.'
        )

    ls = _git("ls-remote", REMOTE, BRANCH)
    if ls.returncode != 0:
        raise GitGuardError(
            f"cannot reach remote {REMOTE!r}: "
            + (ls.stderr.strip() or "no detail")
            + f"\n\nCheck the deploy key {SSH_KEY} is still authorised on the repo."
        )

    remote_sha = ls.stdout.split()[0] if ls.stdout.strip() else ""
    local_remote = _git("rev-parse", f"{REMOTE}/{BRANCH}").stdout.strip()
    if remote_sha and remote_sha != local_remote:
        raise GitGuardError(
            f"{REMOTE}/{BRANCH} moved to {remote_sha[:8]} but we have "
            f"{local_remote[:8]}. Someone pushed elsewhere (GitHub Desktop?) "
            "— fetch first. Never force."
        )


def commit_and_push(
    paths: Sequence[str],
    message: str,
    *,
    dry_run: bool = True,
) -> GitResult:
    """Stage exactly `paths`, commit, and (unless dry_run) push.

    `git add -- <explicit paths>` only. Never `-A`, never `.` — the repo is one
    Steven also edits by hand and with Claude Code, and a broad add would
    publish whatever happens to be sitting there.
    """
    if not paths:
        return GitResult(status="unchanged", detail="no paths given")

    preflight(paths, for_push=not dry_run)

    add = _git("add", "--", *paths)
    if add.returncode != 0:
        raise GitGuardError(f"git add failed: {add.stderr.strip()}")

    staged = _git("diff", "--cached", "--name-only").stdout.split()
    if not staged:
        return GitResult(status="unchanged", detail="nothing staged; site already matches")

    commit = _git("commit", "-m", message)
    if commit.returncode != 0:
        raise GitGuardError(f"git commit failed: {commit.stderr.strip() or commit.stdout.strip()}")

    sha = _git("rev-parse", "HEAD").stdout.strip()

    if dry_run:
        return GitResult(
            status="committed", commit_sha=sha, pushed=False, files=staged,
            detail="dry run: committed locally, NOT pushed. Cloudflare deploys "
                   "on push only, so the live site is unchanged. "
                   f"Inspect with: git -C {SITE_ROOT} show {sha[:8]} --stat",
        )

    push = _git("push", REMOTE, BRANCH)
    if push.returncode != 0:
        # Deliberately do NOT reset or revert. A local-only commit is a safe
        # resting state, and the next attempt's guards will see it.
        return GitResult(
            status="committed_not_pushed", commit_sha=sha, pushed=False, files=staged,
            detail=(push.stderr.strip() or "push failed with no stderr")
                   + f"\n\nThe commit {sha[:8]} is safe locally. Nothing was reset.",
        )

    return GitResult(
        status="pushed", commit_sha=sha, pushed=True, files=staged,
        detail=f"pushed at {now_et().isoformat()}; Cloudflare Pages will deploy in ~1 min",
    )
