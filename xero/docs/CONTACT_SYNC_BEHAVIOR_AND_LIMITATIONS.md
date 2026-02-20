# Contact Sync: Expected Behavior & Known Limitations

> **Last Updated**: 2026-02-12
> **Related Files**: [`xero_contacts.py`](../../cohenix-bench/apps/xero/xero/api/xero_contacts.py)

---

## Xero's Contact Model

### Key Concept: Xero Has Only "Contacts"

Unlike ERPNext which has separate `Customer` and `Supplier` DocTypes, Xero has a single entity type: **Contact**.

The `IsCustomer` and `IsSupplier` fields on a Xero Contact are:

| Field | Behavior |
|-------|----------|
| `IsCustomer` | **Read-only**. Automatically set to `true` when an AR invoice is created against the contact |
| `IsSupplier` | **Read-only**. Automatically set to `true` when an AP invoice is created against the contact |

**These fields cannot be set via API (PUT/POST).**

### What This Means for Users

When you sync a Customer or Supplier to Xero:
- It appears in Xero as a **Contact** (not "Customer" or "Supplier")
- `IsCustomer` and `IsSupplier` will both be `false` initially
- These flags will be set automatically when invoices are created

---

## Our Solution: ContactNumber-Based Type Preservation

Since Xero doesn't allow setting the contact type, we use the `ContactNumber` field to store the ERPNext document type.

### Format

```
ERP:{type_code}:{doc_name}
```

| ERPNext Type | Type Code | Example ContactNumber |
|--------------|-----------|----------------------|
| Customer | C | `ERP:C:CUST-001` |
| Supplier | S | `ERP:S:SUPP-001` |

### How It Works

**Outbound Sync (ERPNext → Xero):**
1. Customer "CUST-001" is synced to Xero
2. ContactNumber is set to `ERP:C:CUST-001`
3. Contact appears in Xero as a plain Contact

**Inbound Sync (Xero → ERPNext):**
1. Contact is fetched from Xero with ContactNumber `ERP:C:CUST-001`
2. System parses ContactNumber: type_code = "C" → Customer
3. Contact is created/updated as a **Customer** in ERPNext

---

## Expected Behavior

### Creating a New Customer/Supplier

1. Create Customer in ERPNext
2. Sync to Xero → Appears as Contact with `ContactNumber=ERP:C:...`
3. `IsCustomer=false`, `IsSupplier=false` in Xero (until invoice is created)

### Round-Trip Sync

1. Create Customer in ERPNext → Sync to Xero
2. Delete Customer in ERPNext
3. Sync from Xero → **Customer is recreated** (not Supplier) ✅

### After Invoice Creation

1. Create Sales Invoice for the Customer in ERPNext
2. Sync invoice to Xero
3. Xero automatically sets `IsCustomer=true` on the Contact

---

## Known Limitations

### 1. Xero Contacts Show No Type Initially

**What you see**: In Xero, synced contacts show as neither Customer nor Supplier.

**Why**: Xero only sets these flags when invoices are created.

**Workaround**: None needed - this is Xero's design. The ContactNumber field preserves the ERPNext type.

### 2. Contact Type Cannot Be Forced via API

**What you see**: You cannot make a Xero contact appear as "Customer" via API.

**Why**: `IsCustomer`/`IsSupplier` are read-only fields.

**Workaround**: Create an invoice against the contact - Xero will set the flag automatically.

### 3. Contacts Without ContactNumber Are Skipped on Inbound Sync

**What you see**: Contacts created manually in Xero (not via sync) are not synced to ERPNext.

**Why**: Without ContactNumber, we cannot determine if it should be a Customer or Supplier.

**Workaround**: 
- Option A: Create the contact in ERPNext first, then sync to Xero
- Option B: Create an invoice for the contact in Xero - the `IsCustomer`/`IsSupplier` flag will be set, enabling sync

### 4. Name Changes in Xero May Cause Duplicates

**What you see**: If you rename a contact in Xero, inbound sync may create a new Customer/Supplier.

**Why**: Matching is done by `xero_contact_id` first, then by name.

**Workaround**: Avoid renaming contacts directly in Xero. Rename in ERPNext and sync.

### 5. ContactPersons Limited to 5

**What you see**: Only 5 contact persons are synced from Xero to ERPNext.

**Why**: Xero API limit - max 5 ContactPersons per contact.

**Workaround**: None - this is a Xero limitation.

---

## Troubleshooting

### Contact Not Syncing to Xero

1. Check `xero_sync_status` on the Customer/Supplier
2. Check Xero Log for error details
3. Verify name is not empty and doesn't exceed 255 characters
4. Check that Xero sync is enabled in Xero Settings

### Contact Not Syncing from Xero

1. Check if ContactNumber starts with `ERP:` - if not, check `IsCustomer`/`IsSupplier` flags
2. If both flags are false, the contact will be skipped (cannot determine type)
3. Create an invoice for the contact in Xero to set the appropriate flag

### Contact Created as Wrong Type

1. Check ContactNumber in Xero - should be `ERP:C:...` for Customer, `ERP:S:...` for Supplier
2. If ContactNumber is missing or wrong, the contact was likely created manually in Xero
3. Delete the ERPNext document and re-sync from Xero after fixing ContactNumber

---

## Technical Reference

### Key Functions

| Function | Purpose |
|----------|---------|
| `build_contact_number()` | Creates `ERP:{C|S}:{name}` string |
| `parse_erpnext_reference()` | Extracts doc_type and doc_name from ContactNumber |
| `validate_and_sanitize_name()` | Validates name for Xero (max 255, no brackets) |
| `compute_data_hash()` | Creates hash for change detection |

### Custom Fields

| Field | DocTypes | Purpose |
|-------|----------|---------|
| `xero_contact_id` | Customer, Supplier | Links to Xero Contact |
| `xero_sync_status` | Customer, Supplier | Sync status (Pending/Synced/Error) |
| `xero_data_hash` | Customer, Supplier | Hash of last synced data |

---

*Document created as part of Contact Bidirectional Sync Fix - 2026-02-12*
