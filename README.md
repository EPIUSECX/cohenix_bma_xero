
# ERPNext-Xero Integration

## Overview

This is a comprehensive, enterprise-grade ERPNext–Xero integration providing bidirectional synchronization between ERPNext and Xero accounting systems. The integration has been enhanced to production-ready standards with advanced features, professional monitoring, robust error handling, and a complete sync dashboard.

**Status: Beta — verify against the Xero Demo Company before production use.** Run `bench migrate` and `bench run-tests --app xero` after install; review the integration's findings/remediation notes before go-live.

This release adds full bidirectional sync support via manual-, periodic- and all supported* webhook triggers. 
*Note: Xero currently only emits webhook triggers for updates to Billing subscriptions, Invoices and Contacts — the integration leverages these webhooks for near-real-time updates where available and combines them with the extensive polling/queued syncs for other entity changes.

## Features

### Core Synchronization (15+ Entity Types)

#### ERPNext → Xero Sync
- **Sales Invoices** - Complete invoice sync with line items, taxes, and payments
- **Purchase Invoices** - Full bill sync including tax calculations and account mappings
- **Payment Entries** - Payment reconciliation with automatic matching
- **Journal Entries** - Manual journal sync with multi-line support
- **Customers & Suppliers** - Contact management with address and tax details
- **Items** - Product catalog synchronization with pricing and inventory
- **Accounts** - Chart of accounts sync with proper hierarchy
- **Quotations** - Quote management and conversion tracking
- **Bank Transactions** - Bank feed integration and reconciliation

#### Xero → ERPNext Sync
- **Sync Xero Accounts** - Import Xero chart of accounts to ERPNext
- **Sync Xero Contacts** - Import Xero contacts as Customers/Suppliers
- **Sync Xero Items** - Import Xero items to ERPNext catalog
- **Sync Xero Payments** - Import Xero payments as Payment Entries
- **Sync Xero Bank Transactions** - Import bank transactions from Xero

#### Added Sync Operations
In addition to the core 15 entity types, this release adds the following sync operations (these are not inherently financial transactions but are useful for operational reconciliation and inventory/workflow integration):
- **Stock Entries**
- **Delivery Notes**
- **Purchase Receipts**
- **Expense Claims**

### Advanced Features
- **Tracking Categories** - Dimensional accounting support for projects and cost centers
- **Financial Reporting** - Trial Balance, P&L, and Balance Sheet sync
- **Aged Receivables/Payables** - Aging reports and customer/supplier analysis
- **Manual Journals** - Complete CRUD operations (note: Multi-Currency Support is not built-in; currency changes must be handled in ERPNext itself)
- **Payment Reconciliation** - Advanced matching algorithms and bulk processing
- **Bulk Operations** - Batch processing for large datasets with progress tracking
- **Retry Mechanisms** - Exponential backoff with intelligent error handling

### Professional Sync Dashboard (Fully Working)
The integration includes a fully working, production-grade dashboard with real-time connection status, monitoring, manual controls and analytics. The dashboard provides:
- Overview (health & connection status)
- Sync Operations (manual triggers, bulk runs, scheduled jobs)
- Analytics (success/failure trends and performance)
- Entity Status (detailed per-entity progress and counts)
- Sync Logs (searchable audit trail with retry actions)
- Configuration (token management and mapping controls)

## Architecture

### Core Components

#### 1. API Layer (`/api/`)
- **xero_client.py** - Core Xero API client with OAuth2 authentication and token management
- **xero_invoices.py** - Invoice synchronization with complete line item support
- **xero_payments.py** - Payment processing, reconciliation, and matching
- **xero_contacts.py** - Customer/Supplier management with address sync
- **xero_items.py** - Product catalog sync with inventory tracking
- **xero_journals.py** - Manual journal operations
- **xero_quotes.py** - Quotation management and conversion tracking
- **xero_bank_transactions.py** - Bank feed integration and reconciliation
- **xero_reports.py** - Financial reporting sync (Trial Balance, P&L, Balance Sheet)
- **xero_accounts.py** - Chart of accounts sync with hierarchy management
- **xero_tracking_categories.py** - Dimensional accounting support

#### 2. DocTypes (Persistent Data Storage)
- **Xero Settings** - Main configuration, authentication, and sync preferences
- **Xero Account Mapping** - Chart of accounts mapping with validation
- **Xero Tax Mapping** - Tax rate synchronization and mapping
- **Xero Account** - Local storage for Xero accounts with caching
- **Xero Tax Rate** - Local storage for Xero tax rates
- **Xero Log** - Comprehensive audit trail with status tracking (Success/Error/Info/Warning)

#### 3. Dashboard (`/page/xero_sync_dashboard/`)
- **Professional Interface** - Multi-tab dashboard with real-time updates and confirmed working sync controls
- **Monitoring & Analytics** - Performance metrics, health indicators, and trend analysis
- **Manual Controls** - Trigger syncs, retry failed operations, and bulk management
- **Configuration Management** - Settings, token refresh, and mapping tools
- **Error Analysis** - Detailed error categorization and resolution guidance

#### 4. Custom Fields System (`/setup/`)
- **Programmatic Installation** - Automated custom field creation for all entity types
- **Complete Coverage** - Xero ID tracking for 50+ fields across all DocTypes
- **Sync Status Fields** - Progress tracking, error handling, and retry counters
- **Validation Fields** - Data integrity and mapping validation

#### 5. Utilities (`/utils/`)
- **Retry Handler** - Exponential backoff with intelligent error categorization
- **Logging System** - Comprehensive audit trail with status tracking
- **Webhook Handler** - Real-time sync triggers from Xero (used where Xero webhooks are available)
- **Validation Tools** - Data integrity and mapping validation

### Data Flow Architecture

```
ERPNext Document → Validation → Queue → Xero API → Response → Update → Log
      ↑                                                              ↓
Custom Fields ← Status Update ← Error Handling ← Retry Logic ← Success/Failure
      ↑                                                              ↓
Dashboard ← Real-time Monitoring ← Analytics ← Health Scoring ← Performance Metrics
```

## Installation

### Prerequisites
- **ERPNext** v13+ or v14+ (tested and compatible)
- **Python** 3.8+ with required dependencies
- **Redis** for background job processing
- **Valid Xero Developer Account** with API access
- **System Administrator** access to ERPNext

### Step-by-Step Installation

#### 1. Install the App
```bash
# Clone the repository
git clone https://github.com/your-repo/xero.git

# Install the app
bench get-app xero /path/to/xero
bench install-app xero --site your-site

# Restart services
bench restart
```

#### 2. Install Custom Fields (Critical Step)
```bash
# Install all required custom fields
bench execute xero.setup.custom_fields.install_custom_fields --site your-site

# Verify installation
bench execute xero.setup.custom_fields.verify_installation --site your-site
```

#### 3. Configure Xero Developer App
1. Go to [Xero Developer Console](https://developer.xero.com/)
2. Create a new app with these settings:
    - **App Type**: Web App
    /* Lines 139-140 omitted */
    - **Scopes**: `accounting.transactions`, `accounting.contacts`, `accounting.settings`

#### 4. Configure ERPNext Settings
1. Navigate to **Xero Settings** in ERPNext
2. Enter your Xero app credentials:
    - **Client ID**: From Xero Developer Console
    /* Lines 146-147 omitted */
    - **Redirect URI**: Your callback URL (for cloud tunnels, use your tunnel base URL + the app callback path, for example: `https://<your-tunnel>/api/method/xero.utils.xero_client.handle_oauth_callback`)
3. Click **Authorize with Xero** to complete OAuth2 flow
4. Select your Xero organization/tenant
5. Enable **Auto Sync** if desired

## Configuration

### Authentication Setup

#### OAuth2 Flow
1. **Initial Setup**: Enter Client ID and Secret in Xero Settings
2. **Authorization**: Click "Authorize with Xero" to start OAuth2 flow
3. **Tenant Selection**: Choose your Xero organization
4. **Token Management**: Tokens are automatically refreshed (no manual intervention required)

#### Security Features
- **Encrypted Token Storage**: All tokens stored securely in ERPNext
- **Automatic Refresh**: Tokens refreshed before expiry
- **Multi-tenant Support**: Handle multiple Xero organizations
- **Access Control**: Role-based permissions for sync operations

### Account Mapping Configuration

#### Automatic Setup
```bash
# Fetch and populate Xero accounts
bench execute xero.api.xero_accounts.sync_accounts_from_xero --site your-site

# Fetch and populate Xero tax rates
- **Max Retries**: Maximum retry attempts for failed syncs (default: 3)
- **Retry Delay**: Base delay for exponential backoff (default: 60 seconds)
- **Webhook Support**: Enable real-time sync triggers from Xero

## Usage Guide

### Dashboard Operations

#### 1. Overview Tab
**Purpose**: System health monitoring and quick status overview
- **Connection Status**: Real-time Xero API connectivity
- **Health Score**: Overall system health (0-100)
- **Recent Statistics**: Success rates and error counts
- **Active Jobs**: Currently running sync operations
- **Quick Actions**: Test connection, refresh token, view recent errors

#### 2. Sync Operations Tab  
**Purpose**: Manual sync triggers and bulk operations
- **Individual Syncs**: Trigger sync for specific entity types
  - Sales Invoice, Purchase Invoice, Payment Entry
  - Customer, Supplier, Item, Account
  - Quotation, Bank Transaction, Journal Entry
- **Bulk Operations**:
  - **Sync All Entities**: Trigger sync for all configured entities
  - **Retry Failed Jobs**: Retry all failed sync operations
  - **Clear Old Logs**: Clean up old sync logs (configurable retention)
- **Queue Management**: Monitor and manage background jobs

#### 3. Analytics Tab
**Purpose**: Performance monitoring and trend analysis
- **Success Rates**: Overall and entity-specific success percentages
- **Performance Metrics**: Average processing times and throughput
- **Entity Statistics**: Sync counts and progress by DocType
- **Trend Analysis**: Historical performance and error patterns
- **Resource Usage**: System resource consumption tracking

#### 4. Entity Status Tab
**Purpose**: Detailed entity-level sync monitoring
- **Sync Progress**: Visual progress bars for each entity type
- **Last Sync Times**: When each entity was last synchronized
- **Pending Counts**: Number of documents waiting for sync
- **Error Counts**: Failed sync attempts by entity
- **Quick Sync**: One-click sync for individual entity types

#### 5. Sync Logs Tab
**Purpose**: Comprehensive audit trail and error management
- **Advanced Filtering**: Filter by status, entity type, date range
- **Search Functionality**: Search logs by document name or message
- **Status Categories**: Success, Error, Info, Warning
- **Detailed View**: Expand logs to see full error details and stack traces
- **Retry Operations**: Retry individual failed sync operations
- **Export Capabilities**: Export logs to CSV for analysis

#### 6. Configuration Tab
**Purpose**: Settings management and system configuration
- **Connection Management**: Test connection, refresh tokens, view tenant info
- **Sync Preferences**: Configure auto-sync, batch sizes, retry settings
- **Mapping Shortcuts**: Quick access to account and tax mappings
- **System Health**: Run diagnostics and health checks
- **Token Information**: View token expiry and refresh status

### Manual Sync Operations

#### Individual Document Sync
```python
# Sync specific document
import frappe
from xero.api.xero_invoices import sync_invoice_to_xero

doc = frappe.get_doc("Sales Invoice", "INV-001")
result = sync_invoice_to_xero(doc)
```

#### Bulk Sync Operations
```python
# Sync all pending invoices
from xero.api.xero_invoices import sync_invoices_to_xero

result = sync_invoices_to_xero(
    filters={"xero_invoice_id": ["is", "not set"]},
    sync_type="bulk"
)
```

#### Dashboard API Usage
```python
# Trigger sync via dashboard API
import frappe

result = frappe.call(
    "xero.xero.page.xero_sync_dashboard.xero_sync_dashboard.trigger_manual_sync",
    entity_type="Sales Invoice",
    filters={"status": "Submitted"},
    sync_type="full"
)
```

### Automated Sync (Hooks)

#### Document Hooks
```python
# hooks.py - Automatic sync on document events
doc_events = {
    "Sales Invoice": {
        "after_submit": "xero.api.xero_invoices.enqueue_sync_invoice"
    },
    "Payment Entry": {
        "after_submit": "xero.api.xero_payments.enqueue_sync_payment"
    },
    "Customer": {
        "after_save": "xero.api.xero_contacts.enqueue_sync_contact"
    }
}
```

#### Scheduled Jobs
```python
# Automatic background sync every hour
scheduler_events = {
    "hourly": [
        "xero.tasks.sync_pending_documents",
        "xero.tasks.retry_failed_syncs"
    ],
    "daily": [
        "xero.tasks.sync_all_entities",
        "xero.tasks.cleanup_old_logs"
    ]
}
```

## Error Handling & Troubleshooting

### Error Categories

#### 1. Connection Errors
**Symptoms**: "Failed to connect to Xero API"
**Solutions**:
```bash
# Test connection (runs the Xero Settings connectivity check)
bench execute "frappe.client.get_value" --kwargs "{'doctype':'Xero Settings','fieldname':'connection_status'}" --site your-site

# Force an access-token refresh
bench execute xero.utils.xero_client.refresh_access_token --site your-site
```

#### 2. Authentication Errors  
**Symptoms**: "Token expired" or "Unauthorized"
**Solutions**:
- Go to Xero Settings → Click "Authorize with Xero"
- Check token expiry in Configuration tab
- Verify Client ID/Secret are correct

#### 3. Validation Errors
**Symptoms**: "Required field missing" or "Invalid account mapping"
**Solutions**:
```bash
# Validate mappings
bench execute xero.utils.validation.validate_account_mappings --site your-site

# Refresh Xero data
bench execute xero.api.xero_accounts.sync_accounts_from_xero --site your-site
```

#### 4. Rate Limiting
**Symptoms**: "API rate limit exceeded"
**Solutions**:
- Reduce batch size in Xero Settings
- Increase retry delay
- Monitor API usage in Analytics tab

### Diagnostic Tools

#### Health Check
```bash
# Run comprehensive health check
bench execute xero.utils.diagnostics.run_health_check --site your-site
```

#### Debug Mode
1. Enable Debug Mode in Xero Settings
2. Check Error Log for detailed information
3. Use Dashboard Logs tab for real-time monitoring

#### Log Analysis
```bash
# View recent errors
bench execute xero.utils.logging.get_recent_errors --site your-site

# Export logs for analysis
bench execute xero.utils.logging.export_logs --site your-site --days 7
```

### Common Issues & Solutions

#### Issue: "Sync function not found for entity type"
**Solution**: Ensure all custom fields are installed
```bash
bench execute xero.setup.custom_fields.install_custom_fields --site your-site
```

#### Issue: "Account mapping not found"
**Solution**: Set up account mappings
```bash
bench execute xero.api.xero_accounts.sync_accounts_from_xero --site your-site
```

#### Issue: "Dashboard not loading"
**Solution**: Check RQ Job table and restart services
```bash
bench restart
bench doctor  # Check for issues
```

## API Reference

### Core Sync Functions

#### Invoice Sync
```python
from xero.api.xero_invoices import sync_invoice_to_xero, sync_invoices_to_xero

# Single invoice
result = sync_invoice_to_xero(invoice_doc)

# Bulk sync
result = sync_invoices_to_xero(filters={"status": "Submitted"})
```

#### Payment Sync
```python
from xero.api.xero_payments import sync_payment_to_xero, sync_payments_from_xero

# ERPNext to Xero
result = sync_payment_to_xero(payment_doc)

# Xero to ERPNext
result = sync_payments_from_xero()
```

#### Contact Sync
```python
from xero.api.xero_contacts import sync_contact_to_xero, sync_contacts_from_xero

# Customer/Supplier to Xero
result = sync_contact_to_xero(customer_doc)

# Xero contacts to ERPNext
result = sync_contacts_from_xero()
```

### Dashboard API

#### Trigger Manual Sync
```python
result = frappe.call(
    "xero.xero.page.xero_sync_dashboard.xero_sync_dashboard.trigger_manual_sync",
    entity_type="Sales Invoice",
    filters={"company": "Your Company"},
    sync_type="incremental"
)
```

#### Get Sync Status
```python
status = frappe.call(
    "xero.xero.page.xero_sync_dashboard.xero_sync_dashboard.get_dashboard_overview"
)
```

#### Retry Failed Jobs
```python
result = frappe.call(
    "xero.xero.page.xero_sync_dashboard.xero_sync_dashboard.bulk_retry_failed",
    entity_type="Sales Invoice",
    date_range={"from_date": "2024-01-01", "to_date": "2024-01-31"}
)
```

## Performance Optimization

### Batch Processing Configuration
```python
# Xero Settings
{
    "batch_size": 50,           # Records per batch
    "max_concurrent_jobs": 5,   # Parallel processing
    "retry_delay": 60,          # Base retry delay (seconds)
    "max_retries": 3            # Maximum retry attempts
}
```

### Caching Strategy
- **Account Mappings**: Cached for 1 hour
- **Tax Rates**: Cached for 24 hours  
- **Connection Status**: Cached for 5 minutes
- **Dashboard Data**: Real-time with 30-second refresh

### Resource Management
- **Memory Usage**: Optimized for large datasets
- **CPU Usage**: Background processing with queue management
- **API Quotas**: Intelligent rate limiting and retry logic
- **Database**: Efficient queries with proper indexing

## Security & Compliance

### Data Protection
- **Encryption**: All tokens encrypted at rest
- **Access Control**: Role-based permissions (System Manager, Accounts Manager)
- **Audit Trail**: Complete sync history with user tracking
- **Data Validation**: Input sanitization and validation

### API Security
- **OAuth2**: Industry standard authentication
- **Token Rotation**: Automatic token refresh
- **Rate Limiting**: Respect Xero API quotas
- **HTTPS**: All communications encrypted

### Compliance Features
- **Audit Logs**: Complete activity tracking
- **Data Retention**: Configurable log retention policies
- **Access Logs**: User activity monitoring
- **Error Tracking**: Comprehensive error categorization

## Development & Customization

### Extending the Integration

#### Adding New Entity Types
1. **Create API Handler**:
```python
# /api/xero_custom_entity.py
def sync_custom_entity_to_xero(doc):
    # Implementation here
    pass
```

2. **Add Custom Fields**:
```python
# /setup/custom_fields.py
custom_fields = {
    "Custom DocType": [
        {
            "fieldname": "xero_custom_id",
            "fieldtype": "Data",
            "label": "Xero Custom ID"
        }
    ]
}
```

3. **Update Dashboard**:
```python
# Add to sync_functions in dashboard
"Custom Entity": "xero.api.xero_custom_entity.sync_custom_entity_to_xero"
```

#### Custom Sync Logic
```python
from xero.utils.xero_client import XeroClient
from xero.utils.logging import log_xero_error

def custom_sync_function(doc):
    try:
        client = XeroClient()
        
        # Prepare data
        xero_data = {
            "Name": doc.name,
            "Description": doc.description
        }
        
        # Sync to Xero
        response = client.post("CustomEndpoint", xero_data)
        
        # Update ERPNext
        doc.xero_custom_id = response["CustomID"]
        doc.save()
        
        # Log success
        log_xero_error(
            message=f"Successfully synced {doc.doctype} {doc.name}",
            status="Success",
            erpnext_doc_type=doc.doctype,
            erpnext_doc_name=doc.name,
            xero_entity_id=response["CustomID"]
        )
        
        return True
        
    except Exception as e:
        log_xero_error(
            message=f"Failed to sync {doc.doctype} {doc.name}",
            status="Error",
            erpnext_doc_type=doc.doctype,
            erpnext_doc_name=doc.name,
            error_details=frappe.get_traceback()
        )
        return False
```

### Testing

The app ships an offline test suite. Every test mocks the Xero HTTP layer and
rolls back anything it writes, so it runs on any site — no live Xero
connection, network access, or test data required:

```bash
# Run the full suite
bench run-tests --app xero --site your-site

# Run a single module
bench run-tests --app xero --module xero.tests.test_contact_sync --site your-site
```

Coverage (`xero/tests/`):

- **`test_xero_client.py`** — the auth- and money-critical client paths: token
  refresh (success, refresh-token rotation, 400/401 invalidation,
  concurrent-lock reuse), webhook HMAC signature accept/reject, 429/5xx retry
  and backoff, and Idempotency-Key propagation on mutating calls.
- **`test_contact_sync.py`** — one full entity sync round trip
  (Customer ↔ Xero Contact): outbound create/update payload correctness and
  sync-status/id/hash bookkeeping, the enqueue guards that prevent redundant
  syncs and sync loops, and inbound contact creation including the
  archived→disabled mapping.
- **`test_invoice_sync.py`** — outbound field validation against Xero's length
  and character limits, and change-detection hashing.
- **`test_inbound_behavior.py`** — ERPNext→Xero account-type mapping and the
  inbound auto-submit guards.

## Changelog

### Version 2.0.0 (Current - Production Ready)

#### Major Enhancements
- ✅ **Professional Dashboard** - Complete 6-tab monitoring and management interface
- ✅ **Enhanced Error Handling** - Comprehensive retry mechanisms with exponential backoff
- ✅ **DocType Architecture** - Persistent data storage for all Xero entities
- ✅ **Advanced Analytics** - Performance metrics, trend analysis, and health scoring
- ✅ **Bulk Operations** - Mass sync capabilities with progress tracking
- ✅ **Custom Fields System** - Programmatic field installation for 50+ fields
- ✅ **Account Management** - Complete chart of accounts sync with hierarchy
- ✅ **Bidirectional Sync** - Full ERPNext ↔ Xero synchronization for 15 entity types

#### Technical Improvements
- ✅ **SQL Query Optimization** - Fixed all column mapping and table existence issues
- ✅ **Status Validation** - Enhanced Xero Log with Warning status support
- ✅ **RQ Job Handling** - Graceful degradation when job tables don't exist
- ✅ **Account Creation** - Proper ERPNext account hierarchy with root group validation
- ✅ **Token Management** - Automatic refresh with secure storage
- ✅ **Webhook Support** - Real-time sync triggers from Xero

#### Dashboard Features
- ✅ **Overview Tab** - Real-time system health and connection monitoring
- ✅ **Sync Operations** - Manual triggers for all 15 entity types
- ✅ **Analytics** - Performance metrics and success rate tracking
- ✅ **Entity Status** - Individual entity monitoring with progress indicators
- ✅ **Sync Logs** - Complete audit trail with filtering and retry capabilities
- ✅ **Configuration** - Centralized settings and mapping management

#### Bug Fixes
- ✅ Fixed "Sync function not found for entity type: Account" error
- ✅ Fixed "Failed to load dashboard overview" RQ Job table errors
- ✅ Fixed SQL column errors (xero_doc_id → xero_entity_id, sync_direction → direction)
- ✅ Fixed Xero Log status validation (added Warning status)
- ✅ Fixed account sync validation errors with proper root account creation
- ✅ Fixed dashboard tab content accumulation issues
- ✅ Fixed add_days() parameter errors with proper timedelta usage

### Version 1.0.0 (Previous)
- Basic sync functionality for core entities
- Simple error logging
- Manual configuration
- Limited dashboard functionality

## Support & Resources

### Documentation
- **Installation Guide** - Step-by-step setup instructions
- **Configuration Manual** - Detailed configuration options
- **API Reference** - Complete function documentation
- **Troubleshooting Guide** - Common issues and solutions

### Dashboard Support
- **Built-in Diagnostics** - Health checks and system validation
- **Real-time Monitoring** - Live sync status and error tracking
- **Error Analysis** - Detailed error categorization and resolution guidance
- **Performance Metrics** - System performance and optimization recommendations

### Community Support
- **ERPNext Community** - Community forums and discussions
- **GitHub Issues** - Bug reports and feature requests
- **Documentation Wiki** - Community-contributed guides and tips

### Professional Support
- **Enterprise Deployment** - Professional installation and configuration
- **Custom Development** - Tailored sync logic and entity support
- **Performance Optimization** - System tuning and optimization
- **Training & Consulting** - User training and best practices

## License

This project is licensed under the MIT License - see the LICENSE file for details.

---

## Summary

This ERPNext-Xero integration provides **enterprise-grade functionality** with:

- ✅ **Complete Bidirectional Sync** - 15 entity types with full data integrity
- ✅ **Professional Dashboard** - 6 comprehensive tabs with real-time monitoring
- ✅ **Production Ready** - Robust error handling and graceful degradation
- ✅ **Advanced Analytics** - Performance metrics and trend analysis
- ✅ **Bulk Operations** - Mass sync capabilities with progress tracking
- ✅ **Account Management** - Complete chart of accounts synchronization
- ✅ **Security & Compliance** - OAuth2, encryption, and audit trails
- ✅ **Developer Friendly** - Extensible architecture with comprehensive API

**Status: Beta — verify against the Xero Demo Company before production use.** Run `bench migrate` and `bench run-tests --app xero` after install; review the integration's findings/remediation notes before go-live.

The dashboard provides complete visibility and control over all sync operations, making it suitable for enterprise deployments with professional monitoring and management capabilities.
