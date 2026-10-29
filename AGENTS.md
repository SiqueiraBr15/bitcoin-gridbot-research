# Lean Storage & Minimal Artifacts Policy

- Prefer results, diagnostics and recommendations in chat. Create persistent
  files only for necessary code, permanent tests, configuration, essential
  documentation, explicitly requested deliverables or indispensable evidence.
- Extend existing modules and tests before adding files or dependencies. Explain
  the technical purpose of new files and dependencies; avoid redundant wrappers.
- Reuse suitable test environments and browsers without compromising audit
  independence. Check storage and reuse options before large operations.
- Avoid unnecessary snapshots, clones and duplicate wheels. Bound temporary
  directories, caches and logs; keep only justified distribution artifacts.
- Close owned test processes and remove only newly created, demonstrably
  disposable temporary files within the authorized scope.
- Preserve source, Git history, financial contracts, data, unique evidence and
  important untracked files. Protected environments require separate explicit
  deletion authorization. Never trade reproducibility or integrity for space.
