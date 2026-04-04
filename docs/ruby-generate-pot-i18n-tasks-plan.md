# Plan: Ruby “Sync base” / `GENERATE_POT` without `i18n-tasks add-missing`

## Context

The **Sync base translation files** action maps to `TranslationAction.GENERATE_POT` and, for Ruby/Rails projects with a `Gemfile`, ultimately calls `RubyI18nManager.generate_pot_file()` in `i18n/ruby/ruby_i18n_manager.py`.

Today that path runs:

```text
bundle exec i18n-tasks add-missing
```

via `_run_i18n_tasks_add_missing()`. That mutates locale YAML in bulk and **does not preserve** hand-maintained comments, key ordering, or formatting choices in those files.

There is an existing note in code that this should move toward parsing **`i18n-tasks missing`** instead (see TODO on `_run_i18n_tasks_add_missing`).

## Goal

Replace reliance on **`add-missing`** with a pipeline that:

1. Runs **`bundle exec i18n-tasks missing`** (or an equivalent machine-readable export if we discover a stable one—see “Open questions”).
2. Parses the report to obtain, per row:
   - **Locale column** — whether the key is missing everywhere (`all`) or missing only in specific locales (e.g. `de es fr …`, or a single locale like `en`).
   - **Key** — the full dotted i18n key.
3. **Ignores** the third column for routing (source paths / “value in other locales”) as specified; it may still be useful later for logging or UI.
4. For keys that need new **base-locale** entries (at minimum: rows where the locale column is **`all`**, meaning the key is not defined in any locale file), **routes** each key to the correct YAML file using the same rules as the project’s **`config/i18n-tasks.yml`** (or `.yaml`) — specifically the `data.write` list when `router: pattern_router` (first matching glob wins; final catch-all entry).

5. **Merges** new keys into the existing target YAML files in a way that **preserves** as much of the existing file as practical (comments and structure). That implies **not** round-tripping the whole tree through a naive `yaml.dump` of the entire document if avoidable, or using a strategy that only appends / surgical-edits known paths.

Non-goal for the first iteration: replicating every edge case of `i18n-tasks` internal behavior beyond what is needed to match `pattern_router` routing for typical Rails layouts.

## Module layout

Implement the pipeline in a **new module under `i18n/ruby/`** (exact filename TBD during implementation, e.g. `i18n_tasks_missing_sync.py` or `i18n_tasks_base_sync.py`), rather than growing `ruby_i18n_manager.py` further.

**Responsibilities of the new module**

- Running `bundle exec i18n-tasks missing` (subprocess, env, timeout) and returning raw output or structured errors.
- Parsing CLI table output (and any future JSON/CSV branch).
- Loading `config/i18n-tasks.yml` / `.yaml` and implementing `pattern_router` matching over `data.write`.
- Merging new keys into existing locale YAML with preservation-focused behavior.

**Responsibilities of `RubyI18nManager`**

- Thin orchestration only: resolve project root, call the module’s public entry point for “sync base from missing,” map failures to `_last_generate_base_error`, and logging at the integration boundary.

This keeps table parsing, glob routing, and YAML merge logic testable in isolation and avoids another multi-hundred-line concern inside `ruby_i18n_manager.py`.

## Why `missing` and not `add-missing`

- **`missing`** is read-only with respect to locale files: it reports gaps without rewriting YAML.
- **`add-missing`** is convenient but opinionated about file updates and formatting.

The product requirement is to align “sync base” with **discover missing keys** + **targeted edits** rather than wholesale regeneration.

## Inputs and semantics (from example output)

Example header:

```text
Missing translations (276) | i18n-tasks v1.1.2
| Locale                  | Key | Value in other locales or source |
```

- **`all` in the Locale column**: key is missing across locales (in the sense reported by i18n-tasks for that row).
- **Space-separated locale list** (e.g. `de es fr …`): key exists somewhere but is missing in those locales.
- **Single locale** (e.g. `en`, `ru`): key missing in that locale; third column may show fallback or pluralization hints.

For **routing new keys into files** using `data.write`, the important case is: **keys that are not present in the base locale data at all** — in the sample, rows with **`all`** for locale. Rows that only indicate gaps in non-base locales may be handled separately (optional phase) or left to translators; the plan should state product intent explicitly during implementation.

**Pluralization / ICU-style rows** (e.g. `ru` + key + `few, many` in the third column) are still “missing key” problems but may need different **value stubs** than a simple string. The plan should include a rule: either skip with a clear log line, or insert minimal valid structures consistent with existing YAML in that file.

## Configuration: `pattern_router`

From `config/i18n-tasks.yml` (or `.yaml`):

- Read `base_locale` (e.g. `en`).
- Read `data.write`: ordered list of rules:
  - Tuple form: `[glob_pattern, path_template]` e.g. `"js.*"` → `config/locales/%{locale}/javascript.%{locale}.yml`
  - String form: catch-all path template, e.g. `config/locales/%{locale}/%{locale}.yml`
- Substitute `%{locale}` with `base_locale` when writing **base** strings for “globally missing” keys.

Implementation will need a **small router** in Python that mirrors “first match wins,” matching the dotted key against each glob (as i18n-tasks does for `pattern_router`). The router belongs in the **new `i18n/ruby/` module**, not in `RubyI18nManager`.

## Proposed implementation phases

### Phase 1 — Discovery command wrapper

- In the **new `i18n/ruby/` module**, add a function to run `bundle exec i18n-tasks missing` with the same subprocess conventions as today’s Bundler helpers (`cwd=project_root`, `I18N_MANAGER_BUNDLE`, `I18N_MANAGER_PATH_EXTRA`, timeout, encoding). Optionally share env resolution by importing minimal helpers from `ruby_i18n_manager` or by moving `_resolve_bundle_executable` / `_bundle_subprocess_env` to a tiny shared `i18n/ruby/bundle_util.py` only if duplication is painful—prefer the new module staying self-contained where practical.
- Command: `bundle exec i18n-tasks missing`.
- Treat non-zero exit code as failure (return structured error text for the manager to store in `_last_generate_base_error`).

### Phase 2 — Parse `missing` table output

- Implement in the **new module**; parse the **ASCII table** format robustly:
  - Skip header lines until a separator row of `+---...` is seen, then parse data rows between separators.
  - Columns are pipe-separated; trim whitespace; handle `|` at line start/end.
  - **Locale column**: preserve as string for classification (`all` vs token list vs single locale).
  - **Key column**: dotted key.
- Consider a **fallback**: if table parsing fails (i18n-tasks version changes output), log and surface error; optionally document a minimum supported `i18n-tasks` version.

Optional enhancement (research task): check whether `i18n-tasks` offers JSON/CSV output for `missing` in recent versions; if yes, prefer that and keep table parsing as fallback.

### Phase 3 — Load and apply `i18n-tasks` config

- In the **new module**: locate `config/i18n-tasks.yml` or `config/i18n-tasks.yaml` under project root.
- Parse YAML with existing project dependencies.
- Extract `base_locale`, `data.write`, and `router` type; if `router` is not `pattern_router`, document behavior (warn and skip, or only support `pattern_router` initially).

### Phase 4 — Merge keys into existing files (preservation-focused)

- Implement in the **new module**.

For each parsed row classified as “needs base entry” (initially: **locale column == `all`**):

1. Compute target file path from the pattern router for `base_locale`.
2. Load existing YAML **while preserving comments** if the stack allows:
   - Prefer **ruamel.yaml** (if already a dependency or acceptable to add) for round-trip comment preservation; if not, document tradeoffs (e.g. append-only blocks with loss of comments) or restrict edits to files without comments.
3. Insert missing nested keys under the top-level locale key (Rails convention: `en:` root or per-file structure — must match how each target file is structured in real projects; inspect sample files in fixtures or dogfood repo).
4. Set placeholder values for new leaves (e.g. empty string `""`, or a configurable sentinel, or copy from key path — product decision).
5. Write back with minimal diff footprint (same key ordering policy as existing file when possible).

### Phase 5 — Wire `generate_pot_file()`

- When `Gemfile` exists, `RubyI18nManager.generate_pot_file()` calls the **new module’s** public API (single entry point preferred, e.g. `run_sync_base_from_missing(project_root) -> bool` plus a way to retrieve the last error string, or return a small result object).
  - The module runs `missing` → parse → route → merge internally.
  - Return `True` if subprocess + parse + all merges succeed; otherwise set `_last_generate_base_error` from the module’s error and return `False`.
- Remove or deprecate the **`add-missing`** path for this flow (keep function behind a feature flag only if needed for rollback).
- Update docstrings and any user-visible strings that still say `add-missing`.

### Phase 6 — Tests

- Unit tests colocated with the **new module** (or under `tests/` mirroring its package path) for:
  - Table parser (fixture strings from real `i18n-tasks` output, including `all`, multi-locale, and long third column).
  - Pattern router matching order vs `data.write` examples.
  - YAML merge into nested dicts for representative file layouts.
- Optional integration test skipped in CI if Ruby/Bundler not present; or mock subprocess.
- Thin tests for `RubyI18nManager.generate_pot_file()` ensuring it delegates to the module and propagates errors.

## Open questions / risks

1. **Machine-readable output**: Investigate `i18n-tasks missing` flags for stable formats to avoid brittle table parsing.
2. **Rows not equal to `all`**: Decide whether “Sync base” also fills missing keys only in `base_locale` when other locales list is non-empty, or whether that belongs to a different workflow (e.g. outstanding translations UI).
3. **File layout variance**: Some `write` targets may expect keys under a namespace vs at file root; verify against Rails-i18n and this app’s `write_locale_yaml_files` / existing Ruby manager behavior.
4. **Performance**: Very large `missing` output — streaming parse vs full buffer.
5. **Windows**: Path separators and `bundle.cmd` already partially addressed; ensure config paths use `os.path` after template expansion.

## References (codebase)

- New module under `i18n/ruby/` — implementation home for missing-report parsing, config routing, and YAML merge.
- `RubyI18nManager.generate_pot_file()` — entry for Gemfile projects; should remain a thin wrapper.
- `RubyI18nManager._run_i18n_tasks_add_missing()` — to be superseded for this workflow (may be removed or kept unused).
- `TranslationAction.GENERATE_POT` / `app.py` user-facing “Syncing base translation files...” copy.

## Success criteria

- Running **Sync base** on a Rails app with `pattern_router` no longer runs `i18n-tasks add-missing` by default.
- New keys reported as globally missing are added to the **correct** per-project YAML files according to `config/i18n-tasks.yml`.
- Existing comments and formatting in touched files are preserved **meaningfully** (exact definition depends on chosen YAML library and constraints documented in the implementation PR).
