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

 Notes:
 - Ignore virtual environments, build artifacts, cache directories, and dependency folders.
 - Focus only on application source files.
