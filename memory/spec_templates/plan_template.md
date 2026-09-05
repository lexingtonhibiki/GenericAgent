# Implementation Plan: [FEATURE]

**Branch**: `[###-feature-name]` | **Date**: [DATE] | **Spec**: [link]
**Input**: Feature specification from `specs/[###-feature-name]/spec.md`

## Summary
[Extract from spec: primary requirement + technical approach]

## Technical Context
**Language/Version**: [e.g., Python 3.13]
**Primary Dependencies**: [e.g., FastAPI]
**Storage**: [if applicable]
**Testing**: [e.g., pytest]
**Target Platform**: [e.g., Windows]
**Project Type**: [e.g., library/cli/web-service]
**Performance Goals**: [domain-specific]
**Constraints**: [domain-specific]

## Constitution Check
*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| P1: Simplicity First | ✅/⚠️/❌ | [notes] |
| P2: Merge-Friendly | ✅/⚠️/❌ | [notes] |
| P3: SOP-Driven | ✅/⚠️/❌ | [notes] |
| P4: Context Efficiency | ✅/⚠️/❌ | [notes] |
| P5: Verify Before Declare | ✅/⚠️/❌ | [notes] |

## Project Structure

### Documentation (this feature)
```
specs/[###-feature]/
├── spec.md          # Feature specification
├── plan.md          # This file
├── research.md      # Phase 0 output
├── data-model.md    # Phase 1 output (optional)
├── contracts/       # Phase 1 output (optional)
└── tasks.md         # Phase 2 output
```

### Source Code (repository root)
```
[Project-specific structure]
```

## Complexity Tracking
| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
