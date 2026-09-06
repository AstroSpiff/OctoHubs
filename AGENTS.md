 # Project context

 This is a FastAPI web application.
 Backend: Python.
 Frontend: HTML (Jinja templates), JavaScript, CSS.

 Structure rules:
 - Avoid monolithic files. Keep modules focused on a single responsibility or domain.
 - Prefer creating new files/modules over extending already-large ones.
- If a file grows beyond ~400–500 lines, split it into smaller, well-named modules when it makes sense; keep it together when cohesion is strong and separation would reduce clarity.
 - Avoid "mega utils" files; create targeted utilities per feature/domain.
 - When introducing a new feature, create or extend a dedicated module for it rather than piling onto unrelated files.
 - Default to a scalable structure: prefer solutions that remain easy to extend, test, and maintain as the codebase grows.
 - When similar logic appears in more than one place, prefer extracting shared helpers or focused modules instead of duplicating behavior.
 - Prefer small, composable functions with clear names and single-purpose responsibilities over long inline blocks.
 - Unify equivalent behaviors where practical: if two code paths do the same job, prefer one shared implementation unless separation is clearly safer.
 - Keep refactors incremental and behavior-preserving: improve structure without changing APIs, selectors, templates, or outputs unless explicitly requested.
 - Before adding new code to an existing large file, check whether the responsibility belongs in a dedicated module instead.
 - Favor feature-local helpers over generic catch-all helpers; shared code should be reused because it is genuinely common, not just to centralize unrelated logic.
 - When possible, organize frontend code by feature/domain, and backend code by responsibility/domain, so future changes stay localized.
 - Write code so future extensions are straightforward: avoid hardcoded branching or tightly coupled logic when a small abstraction would keep the code easier to evolve.
 - Prefer a single canonical instruction source per repo; other agent-specific files should stay as thin pointers when possible, to avoid drift and duplicated maintenance.
 - Optimize for high-signal work: read only the files and line ranges needed for the current task before expanding scope.
 - Avoid re-reading large files end-to-end when targeted searches or focused excerpts are enough to make progress.
 - Keep changes surgical: touch the minimum number of files and lines needed to solve the problem safely.
 - Reuse existing patterns before inventing new ones, unless the current pattern is clearly harmful or blocks maintainability.
 - Avoid explanatory or structural duplication in code and docs; update the canonical source and reference it elsewhere when practical.
 - Prefer concise comments and concise documentation updates; add detail only where it materially improves maintainability.
 - For analysis and reviews, summarize findings and decisions compactly; avoid repeating obvious code context when file references are enough.
 - When verifying changes, prefer targeted checks for the touched area before broader validation, unless the change is cross-cutting.

 Rules specific to this project:
 - Do not change route URLs, HTTP methods, or response formats unless requested.
 - Do not rename template variables unless all references are updated.
 - Do not rename CSS classes/IDs or JS selectors unless all references are updated.

 Remediation completeness standard:
 - Apply this standard whenever fixing code-review findings, defects, regressions, or security issues; the user does not need to request it explicitly.
 - Start from the root cause and identify the invariant that the corrected system must preserve. Do not stop at the first local patch that makes the reported reproduction pass.
 - Search every analogous implementation and caller for the same failure pattern. When multiple findings share a cause, prefer one canonical, reusable solution over duplicated local fixes.
 - Pay particular attention to cross-cutting invariants for transactions and concurrency; lifecycle, reset, shutdown, and server deletion; WebSocket ownership, generation, timeout, cancellation, backpressure, and bounded queues; backend authorization and frontend capabilities; credential and URL redaction; and OpenAPI/backend/TypeScript contract alignment.
 - Add a focused regression test for every reported reproduction. Also add an invariant, parametrized, or contract test that covers analogous implementations when the defect class can recur elsewhere.
 - Exercise failure and concurrency paths deliberately: overlapping requests, stale snapshots, rollback, cancellation, restart, client backpressure, timeout, and partial external failure where relevant.
 - Trace side effects beyond the originally reported file and continue the remediation when a complete fix requires adjacent in-scope changes. Preserve public routes, methods, response formats, selectors, and stored data unless an incompatible change is indispensable and explicitly approved.
 - After implementation, perform an independent review of the remediation specifically looking for incomplete coverage, parallel implementations, and newly introduced regressions.
 - Update the current code-review report with the root cause, applied solution, regression and invariant tests, analogous paths reviewed, and any residual risk. Update English and Italian operational documentation whenever configuration or deployment behavior changes.
 - Before declaring remediation complete, run targeted tests first and then the applicable full gate: backend suite, real PostgreSQL suite, Ruff, Pyright, frontend tests, ESLint, TypeScript/Vite production build, dependency audits, Compose validation, and `git diff --check`.
 - A green pre-existing test suite is not sufficient evidence by itself. Add and run deterministic canaries for the reported edge case, especially for races and blocked I/O.
 - Stop for user direction only when remediation requires a product decision, an incompatible external contract, destructive data handling, or authority outside the requested scope. Otherwise continue through implementation, independent review, documentation, and verification.

 Review and remediation lifecycle:
 - Treat each completed review/remediation pair as a versioned quality cycle. Record the base commit, whether the worktree was already dirty, the report ID, and the exact final gate results. Do not silently move the review baseline while the cycle is in progress.
 - Keep analysis and remediation as separate phases. A review phase may add only its report and must not fix candidates; a remediation phase updates that same report rather than creating a second competing source of truth.
 - Assign every finding a stable ID and a root-cause family. Before accepting it as new, compare it with all earlier reports and classify it as new, explicit reopening/incomplete remediation, analogous surface, or accepted decision.
 - During remediation, build a caller and analogous-surface inventory before editing. Close the finding only after the original reproduction, every identified analogous path, and a failure-path canary pass against the corrected invariant.
 - If a finding reopens a previously closed family, strengthen the canonical abstraction and add a repository-wide invariant or static gate where practical. A second local patch without a class-level guard is not sufficient closure.
 - Use one final verification snapshot: after the last source change, run targeted regressors and then every applicable full gate. Any failure found by a later gate invalidates the earlier closure until it is fixed and the affected gate sequence is repeated.
 - A report may use only these terminal states: `resolved`, `accepted decision`, or `blocked pending user decision`. `Resolved` requires recorded evidence; an accepted decision must identify the approving product/deployment constraint and must not be counted as an open defect.
 - At the end of each cycle, include a recurrence audit: open actionable findings, accepted decisions, explicit reopenings, analogous variants, and recurring families that still lack complete closure. State the counting method and deduplicate repeated headings in review/remediation sections.
 - Once a cycle is green, recommend a local checkpoint commit before beginning another complete review. Create the commit only when the user explicitly requests it. Use that verified commit as the next baseline and prefer delta-first review between periodic full-project reviews.
 - Do not start an unbounded sequence of full-project reviews on an ever-changing worktree. Finish the current cycle, document residual risk, establish the checkpoint, and review subsequent changes against it; perform another full-project pass only when explicitly requested or before a release milestone.

 Accepted architecture and deployment decisions:
 - PostgreSQL is always external and provisioned and administered by the installer; OctoHubs must not create, bundle, or manage its own PostgreSQL service.
 - Direct HTTP operation is supported. Reverse proxies and TLS are external and optional; OctoHubs must not depend internally on Nginx.
 - The supported deployment model is a single application worker unless the user explicitly changes that decision.
 - Release tags are created and numbered manually by the user.
 - Do not reintroduce runtime legacy paths or compatibility layers that have already been removed unless the user explicitly requests them.

 UI migration standards:
 - The legacy interface is the primary visual and functional contract during the React migration. Reproduce its information hierarchy, page composition, tab structure, action placement, compactness, and successful interaction details before considering an alternative layout.
 - React replaces rendering and state management; it is not permission to redesign an established workflow. Preserve a legacy arrangement unless there is a concrete usability, accessibility, responsiveness, or consistency defect to solve.
 - Restrict visual unification to genuinely shared primitives and semantics: buttons, inputs, dialogs, status language, spacing tokens, focus states, loading/error feedback, and responsive rules. Do not flatten page-specific layouts into a generic dashboard pattern.
 - Keep associated functionality where users already expect it. Do not move contextual controls to a separate page, tab, or menu merely to make the component tree look more uniform.
 - Before implementing a legacy area in React, inventory its visible regions, tab nesting, controls, action availability, and compact interaction patterns. Use that inventory as an acceptance checklist for the replacement.
 - Treat a divergence from the legacy UI as an explicit product decision: document the reason in the implementation or migration checklist and make sure the replacement is demonstrably better for the same workflow.
 - Work as a senior product designer, visual designer, UI engineer, and UX engineer: make deliberate decisions about information hierarchy, interaction affordance, content density, typography, spacing, state feedback, accessibility, and responsive composition.
 - Hold every screen to an exceptional professional standard. Do not accept accidental-looking placement, inconsistent visual weight, incomplete workflows, or a layout that only works at one viewport size.
 - Treat each legacy screen as a functional migration, not a visual mock-up: inventory its actions, filters, dialogs, empty/loading/error states, and information before replacing it.
 - Do not remove a legacy navigation path or call a React screen complete until the replacement covers the same user-facing workflow or an intentional product decision documents the omission.
 - Keep React pages as composition roots only. Put toolbars, data regions, dialogs, status summaries, and domain actions in focused feature components.
 - Use one consistent visual language for labels, status terms, buttons, icons, form controls, spacing, and responsive behavior across the application.
 - Design every feature for narrow, medium, and wide viewports. Controls must wrap or reflow predictably, never overlap, clip, or depend on horizontal scrolling except for genuinely tabular data.
 - Keep related controls visibly grouped with an explicit label where needed; do not use decorative containers or visual hierarchy that obscures the workflow.
 - Preserve keyboard access, visible focus, semantic labels, accessible names/tooltips for icon-only controls, and clear feedback for pending, successful, empty, and failed operations.
 - Validate changes with the relevant unit tests, linting, a production build, and a deliberate responsive review before marking a page complete.

 Notes:
 - Ignore virtual environments, build artifacts, cache directories, and dependency folders.
 - Focus only on application source files.
