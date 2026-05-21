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
- `stalled` — `>= --stale-days` since last commit AND dirty (worth attention)

## Use

```bash
drift                            # scan $HOME up to depth 2
drift ~/work ~/personal          # scan multiple roots
drift --only-flagged             # hide clean repos
drift --max-depth 3              # deeper walk
drift --stale-days 7             # tighter stall threshold
drift --json | jq                # machine-readable
```

Exit code: `1` if any repo is dirty above `--dirty-warn` (default 1) or older than `--stale-days` (default 14). `0` otherwise.

## Install

```bash
git clone https://github.com/sb-arnav/drift ~/drift
ln -s ~/drift/drift.py ~/.local/bin/drift   # optional
```

Stdlib only. Python 3.10+.

## Why not just `gita` / `mu-repo` / `myrepos`?

- Self-contained single file. No multi-step setup.
- Looks at working-tree mtime too, not just commits — surfaces "I edited but didn't commit" decay.
- "stalled" flag combines staleness + dirtiness into a single attention signal.

## License

MIT.
