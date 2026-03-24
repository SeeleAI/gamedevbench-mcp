## Code Modification Workflow

Use this workflow when modifying an existing codebase.
Prefer `rg` (ripgrep) for search when available; use `grep` as a fallback.

<edit_flow>
Code modifications should be performed in the following order:
1. Extract key entities from the user description or context: function name, component name, error message, variable name.
2. Infer the possible scope of modules or files involved.
3. `grep "keywords"` -> Find relevant file paths and line numbers.
4. `read relevant files` -> Understand the specific implementation logic.
5. If new keywords/references are found during the read process -> Return to step 3 and continue grep.

Termination Conditions: You clearly know:
- Which files need to be modified
- Which specific locations need to be modified
- Whether the modifications will affect other modules.

Prohibited Behaviors:
- Do not guess file paths and directly edit without grep/reading.
- Do not read a large number of unrelated files at once.
</edit_flow>
