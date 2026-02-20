# Phase 6: Quotations Creation Plan

**Date:** 2025-12-08  
**Priority:** HIGH (Critical for complete sales workflow testing)  
**Complexity:** Medium (similar to Sales Orders)

---

## Objective

Create comprehensive Quotation test data to validate:
- Quote creation and management
- Customer quote workflow
- Quote-to-order conversion tracking
- Xero Quote sync functionality
- Sales pipeline testing

---

## Prerequisites ✅

### Available Resources:
1. **Customers:** 5 customers available
   - TEST CUSTOMER A (Company)
   - TEST CUSTOMER B (Company)
   - TEST CUSTOMER C (Individual)
   - TEST CUSTOMER D (Individual)
   - TEST CUSTOMER_FT (Company)

2. **Items:** 10 items available
   - TEST-SALES-001, 002, TEST-SALES_FT (Sales items)
   - TEST-MULTI-001 (Multi-purpose item)
   - Other items available

3. **Price List:** Standard Selling (enabled, ZAR currency)

4. **Company:** EPIUSE

5. **Currency:** ZAR

---

## Quotation Entity Overview

### Xero Mapping
- **ERPNext:** Quotation
- **Xero:** Quote
- **Sync Direction:** ERPNext → Xero
- **Trigger:** on_submit

### Custom Fields
- xero_quote_id (Data)
- xero_quote_sync_status (Select: Pending/Synced/Error/Skipped)
- xero_last_quote_sync (Datetime)

### Key Characteristics
- Starting point of sales workflow
- Can be converted to Sales Order
- Tracks quote status (Draft, Submitted, Ordered, Lost, Expired)
- Contains line items with pricing
- Customer-specific

---

## Planned Quotations (3 Total)

### QTN-1: Standard Quote - Accepted
- **Customer:** TEST CUSTOMER A
- **Items:** 
  - TEST-SALES-001: Qty 5, Rate 100.0
- **Total Amount:** 500.0 ZAR
- **Valid Until:** 30 days from creation
- **Status:** Draft (can be submitted later)
- **Purpose:** Test standard quote creation

### QTN-2: Multi-Item Quote - Pending
- **Customer:** TEST CUSTOMER B
- **Items:**
  - TEST-SALES-002: Qty 3, Rate 150.0
  - TEST-MULTI-001: Qty 2, Rate 200.0
- **Total Amount:** 850.0 ZAR (450 + 400)
- **Valid Until:** 30 days from creation
- **Status:** Draft
- **Purpose:** Test multi-item quote

### QTN-3: Large Quote - Under Review
- **Customer:** TEST CUSTOMER_FT
- **Items:**
  - TEST-SALES_FT: Qty 10, Rate 250.0
- **Total Amount:** 2,500.0 ZAR
- **Valid Until:** 30 days from creation
- **Status:** Draft
- **Purpose:** Test large value quote

---

## Quotation Structure

### Required Fields:
```python
quotation = frappe.new_doc("Quotation")
quotation.quotation_to = "Customer"  # or "Lead"
quotation.party_name = "Customer Name"
quotation.transaction_date = today()
quotation.valid_till = add_days(today(), 30)
quotation.company = "EPIUSE"
quotation.currency = "ZAR"
quotation.selling_price_list = "Standard Selling"
```

### Line Items:
```python
quotation.append("items", {
    "item_code": "ITEM-CODE",
    "item_name": "Item Name",
    "qty": quantity,
    "rate": price,
    "amount": quantity * price
})
```

---

## Implementation Strategy

### Script 1: Create Quotations
**Purpose:** Create 3 quotation entries
- QTN-1: Single item quote
- QTN-2: Multi-item quote
- QTN-3: Large value quote

### Script 2: Validate Quotations
**Purpose:** Verify all quotations created successfully
- Check quotation count
- Verify line items
- Validate pricing calculations
- Confirm customer references

---

## Expected Outcomes

### Quotations Created: 3 total
- **Single Item:** 1 quotation
- **Multi-Item:** 1 quotation
- **Large Value:** 1 quotation

### Total Quote Values:
- QTN-1: 500.0 ZAR
- QTN-2: 850.0 ZAR
- QTN-3: 2,500.0 ZAR
- **Grand Total:** 3,850.0 ZAR

### Quote Status:
- All quotations in Draft status (docstatus=0)
- Ready for submission when needed
- Can be converted to Sales Orders

---

## Testing Scenarios

### Scenario 1: Single Item Quote
- Create quote with one line item
- Verify pricing calculation
- Check customer reference

### Scenario 2: Multi-Item Quote
- Create quote with multiple line items
- Verify total calculation
- Check item references

### Scenario 3: Large Value Quote
- Create high-value quote
- Test quantity and pricing
- Verify currency handling

---

## Xero Sync Considerations

### Quotation Sync to Xero:
1. **Quotation → Xero Quote**
   - Maps to Xero Quote entity
   - Syncs customer, items, amounts
   - Tracks quote status

2. **Sync Triggers:**
   - on_submit: Triggers automatic sync to Xero
   - Manual sync: Via dashboard or API call
   - Retry mechanism: For failed syncs

3. **Expected Xero Fields:**
   - xero_quote_id: Unique Xero quote identifier
   - xero_quote_sync_status: Sync state tracking
   - xero_last_quote_sync: Last sync timestamp

---

## Success Criteria

### Phase 6 Complete When:
- ✅ All 3 quotations created successfully
- ✅ Line items properly configured
- ✅ Pricing calculations correct
- ✅ Customer references validated
- ✅ Mix of single/multi-item quotes tested
- ✅ All entries ready for Xero sync testing

---

## Risk Mitigation

### Potential Issues:
1. **Item Validation Errors**
   - Mitigation: Verify items exist and are sales items
   - Fallback: Use known working items

2. **Price List Issues**
   - Mitigation: Verify price list is enabled
   - Fallback: Use default selling price list

3. **Customer Reference Errors**
   - Mitigation: Ensure customers exist
   - Fallback: Use verified test customers

---

## Execution Timeline

**Estimated Time:** 1 hour

1. **Script 1 - Create Quotations:** 30 minutes
2. **Script 2 - Validation:** 15 minutes
3. **Testing & Debugging:** 15 minutes

---

**Status:** Ready for Implementation  
**Next Step:** Create Script 1 - Create Quotations  
**Dependencies:** Phase 1 (Master Data) must be complete ✅
