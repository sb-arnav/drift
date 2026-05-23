# drift

[![tests](https://github.com/sb-arnav/drift/actions/workflows/test.yml/badge.svg)](https://github.com/sb-arnav/drift/actions/workflows/test.yml)
[![MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

> Surface git workspace decay across many projects. Companion to [paleo](https://github.com/sb-arnav/paleo).

For each git repo under one or more root directories, report: branch, ahead/behind vs upstream, dirty file count, last commit age. Designed to answer "what have I been ignoring?" in one screen.

```bash
$ drift
drift · 9 repos

  repo            branch     dirty   ahead/behind  last commit  flags
  --------------- ---------- ----- -------------- ------------  ----------------
  primary-app     master       19            0/0          <1d  D19
  side-project    master        4           16/0          <1d  D4 ↑16
  parked-thing    main          2            1/0          2mo  D2 ↑1 stalled
  shipped-thing   main          0            0/0          12d
  tooling         master        0              —           3d  no-upstream
  …
```

## Flags

- `D<N>` — dirty file count
- `↑<N>` / `↓<N>` — ahead/behind upstream
- `no-upstream` — branch tracks nothing
- `no-commits` — repo initialized but has no commits yet
- `stalled` — dirty **and** untouched (no commit *or* edit) for `>= --stale-days`

A detached HEAD shows as `detached@<sha>` in the branch column.

## Use

```bash
drift                                   # scan $HOME up to depth 2
drift ~/work ~/personal                 # scan multiple roots
drift --only-flagged                    # hide clean repos
drift --sort age                        # most-neglected repo first
drift --max-depth 3                     # deeper walk
drift --stale-days 7                    # tighter stall threshold
drift --exclude 'backup-*'             # skip repos matching a glob
drift --exclude 'archive-*' --exclude '*.bak'  # multiple exclusions
drift --json | jq                       # machine-readable
watch -ct drift --color always --only-flagged   # live dashboard, like top for repos
```

Output is colorized on a TTY (stalled in red, dirty in yellow, clean rows dimmed) and plain when piped. `--color always|never` overrides; `NO_COLOR` is honored. Sort with `--sort signal|age|dirty|name` (default `signal` = most actionable first).

Exit code: `1` if any repo needs attention — dirty above `--dirty-warn` (default 1) or `stalled`. `0` otherwise. A clean repo that's merely old (a finished, shipped project) does **not** fail.

## Install

```bash
git clone https://github.com/sb-arnav/drift ~/drift
ln -s ~/drift/drift.py ~/.local/bin/drift   # optional
```

Stdlib only. Python 3.10+.

## Why not just `gita` / `mu-repo` / `myrepos`?

- Self-contained single file, stdlib only. No `gita add`, no YAML, no `mrconfig` — point it at a directory and go.
- Looks at the mtime of *dirty* files, not just commit dates — so "I edited but never committed" counts as activity, and an old commit with fresh edits isn't mistaken for abandoned.
- `stalled` combines staleness + dirtiness into a single attention signal that no other tool in this space names.

## License

MIT.
