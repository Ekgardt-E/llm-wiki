# A deferred night is not complete

Research date: 2026-10-01. Installed Linux systemd 255.4, Python 3.14.6.

The native nightly reached its existing 1800-second compile-following bound,
skipped lint/index/graph, and recorded success. The compiler still ran in its
oneshot unit's cgroup; ending the unit terminated it. Its last state remained
running. A previous deferred run was examined only after a new compile could
overwrite the start stamp, so that unfinished outcome could disappear.

Sources read on the research date:

- [systemd v255 run implementation](https://github.com/systemd/systemd/blob/v255/src/run/run.c)
  and [kill contract](https://github.com/systemd/systemd/blob/v255/man/systemd.kill.xml):
  a session is not an independent service lifecycle; scope execution migrates its
  own PID and then execs the command. A separate managed scope is a candidate for
  preserving the existing PID/identity and environment contract.
- [Linux cgroup v2](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html):
  grouping and process migration are independent of process parentage.
- [Python signals](https://docs.python.org/3/library/signal.html): SIGINT normally
  raises KeyboardInterrupt, while SIGTERM does not automatically become a Python
  exception caught by the compiler's existing BaseException finalization.

Alternatives: longer wait, disabling cgroup cleanup, a separate managed compiler,
or cooperative batch-boundary deferral. Longer waits do not repair ownership;
disabling KillMode leaves unmanaged work. Independent ownership still requires
native qualification and is not claimed implemented by this status correction.

This change preserves the existing wait and scheduling bounds. A pending compile
marker yields deferred maintenance, never a new successful completion timestamp.
Real errors still take precedence. Doctor and session context name the deferred
work. A live compiler is not declared lost. An old dead compiler's missing outcome
is counted before the next compile can replace the start stamp; the established
marker and state schema are retained. Once compilation is complete, the ordinary
post-compile pass can record success. Nothing deletes failed attempts or journals.

Four regressions distinguish old success/lost-live-run/overwritten-loss/unknown-
doctor behavior; a fifth distinguishes the empty session-context warning.
This is a partial delivery: it makes the existing lifecycle truthful, but does
not itself let a compiler outlive its nightly cgroup. Native ownership proof was
blocked by user-bus access in the available sandbox. Full compiler/nightly
acceptance and that ownership correction remain open; no timeout is enlarged.
