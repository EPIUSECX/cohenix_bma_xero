# Codebase Cleanup Plan

> **Purpose**: Organize AI plans, documentation, and test files to create a tidy, maintainable codebase structure.
> **Date**: 2026-02-18
> **Status**: ✅ COMPLETED

---

## Executive Summary

This plan addressed the cleanup and reorganization of scattered AI documentation, implementation plans, test files, and temporary artifacts across the workspace. All functionality has been preserved while creating a cleaner, more organized project structure.

---

## Completed Actions

### Phase 1: DELETE - Temporary Files ✅

| Action | Path | Status |
|--------|------|--------|
| **DELETED** | `test-env/` | ✅ Removed Python venv |
| **KEPT** | `cloudflared.deb` | ✅ Left per user request |

### Phase 2: MOVE - AI Documentation ✅

| Action | Source | Destination | Status |
|--------|--------|-------------|--------|
| **MOVED** | `ai_docs/CODEBASE_REFERENCE_SHEET.md` | → `docs/CODEBASE_REFERENCE_SHEET.md` | ✅ |
| **MOVED** | `ai_docs/CRITICAL_KNOWLEDGE_FOR_FUTURE_TASKS.md` | → `docs/CRITICAL_KNOWLEDGE_FOR_FUTURE_TASKS.md` | ✅ |
| **MOVED** | `ai_docs/INVOICE_SYNC_IMPLEMENTATION_SUMMARY.md` | → `docs/INVOICE_SYNC_IMPLEMENTATION_SUMMARY.md` | ✅ |
| **MOVED** | `ai_docs/ACCOUNT_SYNC_IMPLEMENTATION_SUMMARY.md` | → `docs/ACCOUNT_SYNC_IMPLEMENTATION_SUMMARY.md` | ✅ |
| **MOVED** | `ai_docs/CONTACT_SYNC_BEHAVIOR_AND_LIMITATIONS.md` | → `docs/CONTACT_SYNC_BEHAVIOR_AND_LIMITATIONS.md` | ✅ |
| **MOVED** | `ai_docs/REMOVAL_SUMMARY.md` | → `docs/REMOVAL_SUMMARY.md` | ✅ |
| **DELETED** | `ai_docs/` (folder) | ✅ Removed after move |

### Phase 3: MOVE - Images ✅

| Action | Source | Destination | Status |
|--------|--------|-------------|--------|
| **MOVED** | `images/` | → `docs/images/` | ✅ |
| **UPDATED** | `README.md` | Image paths updated | ✅ |

### Phase 4: REORGANIZE - Test Files ✅

| Action | Source | Destination | Status |
|--------|--------|-------------|--------|
| **MOVED** | `xero/test_*.py` (12 files) | → `xero/tests/` | ✅ |
| **MOVED** | `xero/utils/create_test_data/` | → `xero/tests/test_data/` | ✅ |
| **MOVED** | `xero/utils/sync_test_data_to_xero/` | → `xero/tests/sync_test_data/` | ✅ |
| **MOVED** | `xero/utils/test_outbound_sync_2026.py` | → `xero/tests/` | ✅ |
| **MOVED** | `xero/utils/outbound_sync_test_results_*.json` | → `xero/tests/` | ✅ |
| **CREATED** | `xero/tests/__init__.py` | ✅ |

### Phase 5: UPDATE - Configuration ✅

| Action | File | Status |
|--------|------|--------|
| **UPDATED** | `.gitignore` | Added `test-env/` and `*.deb` entries |
| **UPDATED** | `docs/*.md` | Fixed relative paths |

---

## Final Directory Structure

```
/workspace/
├── .devcontainer/
├── .gitignore (updated)
├── README.md (updated image paths)
├── installer.py
├── cloudflared.deb
├── docs/
│   ├── CODEBASE_REFERENCE_SHEET.md
│   ├── CRITICAL_KNOWLEDGE_FOR_FUTURE_TASKS.md
│   ├── INVOICE_SYNC_IMPLEMENTATION_SUMMARY.md
│   ├── ACCOUNT_SYNC_IMPLEMENTATION_SUMMARY.md
│   ├── CONTACT_SYNC_BEHAVIOR_AND_LIMITATIONS.md
│   ├── REMOVAL_SUMMARY.md
│   └── images/
│       └── devcontainer_*.png (18 files)
├── plans/
│   ├── account-sync-fix-plan.md
│   ├── contact-sync-fix-plan.md
│   ├── item-sync-fix-plan.md
│   ├── credit-note-sync-fix-plan.md
│   ├── already-exists-detection-plan.md
│   └── codebase-cleanup-plan.md (this file)
├── resources/
│   └── Dockerfile
└── cohenix-bench/ (gitignored)
    └── apps/xero/xero/
        ├── tests/
        │   ├── __init__.py
        │   ├── test_account_sync.py
        │   ├── test_credit_note_bidirectional_sync.py
        │   ├── test_credit_note_sync.py
        │   ├── test_invoice_bidirectional_sync.py
        │   ├── test_invoice_roundtrip.py
        │   ├── test_invoice_standalone.py
        │   ├── test_invoice_sync.py
        │   ├── test_item_bidirectional_sync.py
        │   ├── test_item_sync.py
        │   ├── test_outbound_sync_2026.py
        │   ├── test_pattern_consistency.py
        │   ├── outbound_sync_test_results_*.json
        │   ├── test_data/ (create_test_data contents)
        │   └── sync_test_data/ (sync_test_data_to_xero contents)
        └── (existing structure)
```

---

## Notes

1. **Functionality Preservation**: All moves maintain file content; only paths changed
2. **Test Imports**: Tests use absolute imports (`from xero.api.xero_invoices import ...`) so they should work from the new location
3. **Documentation Paths**: Updated references in docs to reflect new locations
4. **Plans Kept**: All plans kept as reference for future agentic operations
