# Phase 5: Payment Entries Creation Plan

**Date:** 2025-12-08  
**Priority:** HIGH (Critical for complete financial workflow testing)  
**Complexity:** High (requires invoice references, account validations)

---

## Objective

Create comprehensive Payment Entry test data to validate:
- Customer payment processing (Receive)
- Supplier payment processing (Pay)
- Advance payments (no invoice reference)
- Payment reconciliation with invoices
- Xero Payment sync functionality

---

## Prerequisites ✅

### Available Resources:
1. **Submitted Sales Invoices:** 3 invoices
   - ACC-SINV-2025-00001: Customer=TEST CUSTOMER A, Total=500.0, Outstanding=500.0
   - ACC-SINV-2025-00002: Customer=TEST CUSTOMER B, Total=700.0, Outstanding=700.0
   - ACC-SINV-2025-00003: Customer=TEST CUSTOMER C, Total=1000.0, Outstanding=1000.0

2. **Submitted Purchase Invoices:** 3 invoices
   - ACC-PINV-2025-00001: Supplier=TEST SUPPLIER A, Total=1125.0, Outstanding=1125.0
   - ACC-PINV-2025-00002: Supplier=TEST SUPPLIER B, Total=1500.0, Outstanding=1500.0
   - ACC-PINV-2025-00003: Supplier=TEST SUPPLIER C, Total=1875.0, Outstanding=1875.0

3. **Bank/Cash Accounts:**
   - Cash - E (Cash account)

4. **Modes of Payment:**
   - Cash (Enabled)
   - Cheque (Enabled)
   - Credit Card (Enabled)
   - Wire Transfer (Enabled)
   - Bank Draft (Enabled)

5. **Company:** EPIUSE
6. **Currency:** ZAR

---

## Payment Entry Types

### Type 1: Receive (Customer Payments)
**Purpose:** Record payments received from customers against sales invoices

**Key Fields:**
- payment_type: "Receive"
- party_type: "Customer"
- party: Customer name
- paid_from: Customer's receivable account (Debtors - E)
- paid_to: Bank/Cash account (Cash - E)
- references: Link to Sales Invoice(s)

### Type 2: Pay (Supplier Payments)
**Purpose:** Record payments made to suppliers against purchase invoices

**Key Fields:**
- payment_type: "Pay"
- party_type: "Supplier"
- party: Supplier name
- paid_from: Bank/Cash account (Cash - E)
- paid_to: Supplier's payable account (Employee Advances - E)
- references: Link to Purchase Invoice(s)

### Type 3: Internal Transfer
**Purpose:** Record advance payments without invoice reference

**Key Fields:**
- payment_type: "Internal Transfer" OR "Receive"/"Pay" without references
- No invoice references
- Used for advance payments or general transfers

---

## Planned Payment Entries (7 Total)

### Customer Payments (3 entries)

#### PE-1: Full Payment for Sales Invoice 1
- **Payment Type:** Receive
- **Customer:** TEST CUSTOMER A
- **Amount:** 500.0 ZAR (full payment)
- **Mode of Payment:** Cash
- **Reference:** ACC-SINV-2025-00001
- **Paid From:** Debtors - E
- **Paid To:** Cash - E
- **Status:** Draft (docstatus=0)

#### PE-2: Partial Payment for Sales Invoice 2
- **Payment Type:** Receive
- **Customer:** TEST CUSTOMER B
- **Amount:** 400.0 ZAR (partial: 400 of 700)
- **Mode of Payment:** Cheque
- **Reference:** ACC-SINV-2025-00002
- **Paid From:** Debtors - E
- **Paid To:** Cash - E
- **Status:** Draft (docstatus=0)

#### PE-3: Full Payment for Sales Invoice 3
- **Payment Type:** Receive
- **Customer:** TEST CUSTOMER C
- **Amount:** 1000.0 ZAR (full payment)
- **Mode of Payment:** Wire Transfer
- **Reference:** ACC-SINV-2025-00003
- **Paid From:** Debtors - E
- **Paid To:** Cash - E
- **Status:** Draft (docstatus=0)

### Supplier Payments (3 entries)

#### PE-4: Full Payment for Purchase Invoice 1
- **Payment Type:** Pay
- **Supplier:** TEST SUPPLIER A
- **Amount:** 1125.0 ZAR (full payment)
- **Mode of Payment:** Cash
- **Reference:** ACC-PINV-2025-00001
- **Paid From:** Cash - E
- **Paid To:** Employee Advances - E
- **Status:** Draft (docstatus=0)

#### PE-5: Partial Payment for Purchase Invoice 2
- **Payment Type:** Pay
- **Supplier:** TEST SUPPLIER B
- **Amount:** 800.0 ZAR (partial: 800 of 1500)
- **Mode of Payment:** Cheque
- **Reference:** ACC-PINV-2025-00002
- **Paid From:** Cash - E
- **Paid To:** Employee Advances - E
- **Status:** Draft (docstatus=0)

#### PE-6: Full Payment for Purchase Invoice 3
- **Payment Type:** Pay
- **Supplier:** TEST SUPPLIER C
- **Amount:** 1875.0 ZAR (full payment)
- **Mode of Payment:** Wire Transfer
- **Reference:** ACC-PINV-2025-00003
- **Paid From:** Cash - E
- **Paid To:** Employee Advances - E
- **Status:** Draft (docstatus=0)

### Advance Payment (1 entry)

#### PE-7: Customer Advance Payment
- **Payment Type:** Receive
- **Customer:** TEST CUSTOMER_FT
- **Amount:** 500.0 ZAR (advance, no invoice)
- **Mode of Payment:** Cash
- **Reference:** None (advance payment)
- **Paid From:** Debtors - E
- **Paid To:** Cash - E
- **Status:** Draft (docstatus=0)

---

## Payment Entry Structure

### Required Fields:
```python
payment_entry = frappe.new_doc("Payment Entry")
payment_entry.payment_type = "Receive" or "Pay"
payment_entry.posting_date = today()
payment_entry.company = "EPIUSE"
payment_entry.mode_of_payment = "Cash" or "Cheque" etc.
payment_entry.party_type = "Customer" or "Supplier"
payment_entry.party = "Customer/Supplier Name"
payment_entry.paid_from = "Account Name"  # Source account
payment_entry.paid_to = "Account Name"    # Destination account
payment_entry.paid_amount = amount
payment_entry.received_amount = amount
payment_entry.reference_no = "REF-001"    # Optional reference
payment_entry.reference_date = today()
```

### For Invoice References:
```python
# Add reference to invoice
payment_entry.append("references", {
    "reference_doctype": "Sales Invoice" or "Purchase Invoice",
    "reference_name": "Invoice Name",
    "total_amount": invoice_total,
    "outstanding_amount": invoice_outstanding,
    "allocated_amount": payment_amount
})
```

---

## Account Mappings

### Customer Payments (Receive):
- **Paid From:** Debtors - E (Receivable account)
- **Paid To:** Cash - E (Cash account)
- **Party Type:** Customer

### Supplier Payments (Pay):
- **Paid From:** Cash - E (Cash account)
- **Paid To:** Employee Advances - E (Payable account)
- **Party Type:** Supplier

---

## Validation Requirements

### Payment Entry Validations:
1. ✅ Payment type must be valid ("Receive", "Pay", "Internal Transfer")
2. ✅ Party must exist (Customer or Supplier)
3. ✅ Accounts must be valid and not group accounts
4. ✅ Paid amount must be positive
5. ✅ For invoice references:
   - Invoice must be submitted (docstatus=1)
   - Allocated amount ≤ Outstanding amount
   - Invoice must belong to the specified party
6. ✅ Mode of Payment must be enabled
7. ✅ Company must match

### Xero Sync Fields:
- xero_payment_id (Data)
- xero_bank_transaction_id (Data)
- xero_sync_status (Select: Pending/Synced/Error/Skipped)
- xero_last_sync (Datetime)
- xero_payment_data (Long Text - JSON for multiple payments)

---

## Implementation Strategy

### Script 1: Verify Payment Prerequisites
**Purpose:** Validate all required data is available
- Check submitted invoices
- Verify bank/cash accounts
- Confirm modes of payment
- Validate party accounts (receivable/payable)

### Script 2: Create Customer Payments
**Purpose:** Create 3 customer payment entries
- PE-1: Full payment (Cash)
- PE-2: Partial payment (Cheque)
- PE-3: Full payment (Wire Transfer)

### Script 3: Create Supplier Payments
**Purpose:** Create 3 supplier payment entries
- PE-4: Full payment (Cash)
- PE-5: Partial payment (Cheque)
- PE-6: Full payment (Wire Transfer)

### Script 4: Create Advance Payment
**Purpose:** Create 1 advance payment (no invoice reference)
- PE-7: Customer advance (Cash)

### Script 5: Validate Payment Entries
**Purpose:** Verify all payment entries created successfully
- Check payment entry count
- Verify invoice allocations
- Validate account postings
- Confirm outstanding amounts updated

---

## Expected Outcomes

### Payment Entries Created: 7 total
- **Customer Payments:** 3 (2 full, 1 partial)
- **Supplier Payments:** 3 (2 full, 1 partial)
- **Advance Payments:** 1 (no invoice reference)

### Invoice Outstanding Updates:
- ACC-SINV-2025-00001: 500.0 → 0.0 (fully paid)
- ACC-SINV-2025-00002: 700.0 → 300.0 (partially paid)
- ACC-SINV-2025-00003: 1000.0 → 0.0 (fully paid)
- ACC-PINV-2025-00001: 1125.0 → 0.0 (fully paid)
- ACC-PINV-2025-00002: 1500.0 → 700.0 (partially paid)
- ACC-PINV-2025-00003: 1875.0 → 0.0 (fully paid)

### Total Payment Amounts:
- **Customer Payments:** 1,900.0 ZAR (500 + 400 + 1000)
- **Supplier Payments:** 3,800.0 ZAR (1125 + 800 + 1875)
- **Advance Payments:** 500.0 ZAR
- **Grand Total:** 6,200.0 ZAR

---

## Testing Scenarios

### Scenario 1: Full Payment Reconciliation
- Create payment for full invoice amount
- Verify outstanding becomes 0
- Check payment status updates

### Scenario 2: Partial Payment Handling
- Create payment for partial amount
- Verify outstanding reduces correctly
- Confirm invoice remains open

### Scenario 3: Advance Payment Processing
- Create payment without invoice reference
- Verify payment recorded correctly
- Test advance allocation to future invoices

### Scenario 4: Multiple Payment Methods
- Test different modes of payment (Cash, Cheque, Wire Transfer)
- Verify all methods work correctly
- Check payment method tracking

---

## Xero Sync Considerations

### Payment Sync to Xero:
1. **Payment Entry → Xero Payment**
   - Maps to Xero Payment entity
   - Links to Xero Invoice via xero_invoice_id
   - Syncs payment amount and date

2. **Bank Transaction Sync:**
   - May also create Xero Bank Transaction
   - Links to bank account in Xero
   - Tracks bank reconciliation

3. **Sync Triggers:**
   - on_submit: Triggers automatic sync to Xero
   - Manual sync: Via dashboard or API call
   - Retry mechanism: For failed syncs

### Expected Xero Fields:
- xero_payment_id: Unique Xero payment identifier
- xero_bank_transaction_id: Bank transaction reference
- xero_sync_status: Sync state tracking
- xero_last_sync: Last sync timestamp

---

## Success Criteria

### Phase 5 Complete When:
- ✅ All 7 payment entries created successfully
- ✅ Invoice outstanding amounts updated correctly
- ✅ Account postings validated
- ✅ Mix of full/partial payments tested
- ✅ Advance payment created without invoice
- ✅ Multiple payment methods used
- ✅ All entries ready for Xero sync testing

---

## Risk Mitigation

### Potential Issues:
1. **Account Validation Errors**
   - Mitigation: Verify accounts exist and are not group accounts
   - Fallback: Use default company accounts

2. **Invoice Reference Errors**
   - Mitigation: Ensure invoices are submitted before payment
   - Fallback: Create payments without references first

3. **Outstanding Amount Mismatches**
   - Mitigation: Fetch current outstanding before allocation
   - Fallback: Use partial payments to avoid over-allocation

4. **Mode of Payment Issues**
   - Mitigation: Verify modes are enabled
   - Fallback: Use default "Cash" mode

---

## Execution Timeline

**Estimated Time:** 2-3 hours

1. **Script 1 - Prerequisites:** 15 minutes
2. **Script 2 - Customer Payments:** 30 minutes
3. **Script 3 - Supplier Payments:** 30 minutes
4. **Script 4 - Advance Payment:** 15 minutes
5. **Script 5 - Validation:** 30 minutes
6. **Testing & Debugging:** 30-60 minutes

---

**Status:** Ready for Implementation  
**Next Step:** Create Script 1 - Verify Payment Prerequisites  
**Dependencies:** Phase 3 (Invoices) must be complete ✅
