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
