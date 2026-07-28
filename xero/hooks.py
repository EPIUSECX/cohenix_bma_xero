# Copyright (c) 2024, EPI-USE Global Services and contributors
# For license information, please see license.txt

app_name = "xero"
app_title = "Xero Integration"
app_publisher = "EPI-USE Global Services"
app_description = "Integrate ERPNext with Xero Accounting"
app_email = "support@epiuse.com"
app_license = "mit"
required_apps = ["erpnext"]

# Includes in <head>
# ------------------
add_to_apps_screen = [
 	{
 		"name": "xero",
 		"logo": "/assets/xero/Xero_software_logo.svg",
 		"title": "Xero Integration",
 		"route": "/desk",
 		#"has_permission": "liftlogic.api.permission.has_app_permission"
 	}
 ]
# include js, css files in header of desk.html
app_include_css = [
    "/assets/xero/css/xero_dashboard.css"
]
app_include_js = [
    "/assets/xero/js/quick_account_mapping_dialog.js"
]

# include js, css files in header of web template
# web_include_css = "/assets/xero/css/xero.css"
# web_include_js = "/assets/xero/js/xero.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "xero/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"Item" : "public/js/item.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

doctype_js = {
    "Xero Settings": "xero/xero/doctype/xero_settings/xero_settings.js",
    "Sales Invoice": "xero/public/js/sales_invoice.js",
    "Purchase Invoice": "xero/public/js/purchase_invoice.js",
    "Journal Entry": "xero/public/js/journal_entry.js",
    "Item": "xero/public/js/item.js",
    "Payment Entry": "xero/public/js/payment_entry.js",
    "Credit Note": "xero/public/js/credit_note.js",
    "Quotation": "xero/public/js/quotation.js",
    "Bank Transaction": "xero/public/js/bank_transaction.js"
}

# Svg Icons
# ----------
# include app icons in desk
# app_include_icons = "xero/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "xero.utils.jinja_methods",
# 	"filters": "xero.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "xero.install.before_install"
after_install = "xero.setup.custom_fields.setup_custom_fields"
after_migrate = "xero.setup.custom_fields.setup_custom_fields"

# Uninstallation
# ------------

# before_uninstall = "xero.uninstall.before_uninstall"
# after_uninstall = "xero.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being integrated is given as reference
# setup_integration = {
#	"frappe": {
#		"setup": "xero.frappe_integration.setup"
#	}
# }

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"Sales Invoice": {
		"on_submit": "xero.api.xero_invoices.enqueue_sync_invoice_or_return",
		"on_cancel": "xero.api.xero_invoices.enqueue_void_invoice"
	},
	"Purchase Invoice": {
		"on_submit": "xero.api.xero_invoices.enqueue_sync_invoice_or_return",
		"on_cancel": "xero.api.xero_invoices.enqueue_void_invoice"
	},
	"Customer": {
		"on_update": "xero.api.xero_contacts.enqueue_sync_contact"
	},
	"Supplier": {
		"on_update": "xero.api.xero_contacts.enqueue_sync_contact"
	},
	"Account": {
		"on_update": "xero.api.xero_accounts.enqueue_sync_account"
	},
    "Payment Entry": {
        "on_submit": "xero.api.xero_payments.enqueue_sync_payment"
    },
    "Journal Entry": {
        "on_submit": "xero.api.xero_journals.enqueue_sync_journal",
        "on_cancel": "xero.api.xero_journals.enqueue_delete_journal"
    },
    # NOTE: Bank Transaction outbound sync is intentionally DISABLED — bank
    # movements reach Xero via Payment Entry (-> Payment) and Journal Entry
    # (-> Manual Journal) sync. Pushing Bank Transactions as well would
    # double-count. See xero/api/xero_bank_transactions.py.
    "Quotation": {
        "on_submit": "xero.api.xero_quotes.enqueue_sync_quotation"
    },
    "Purchase Order": {
        "on_submit": "xero.api.xero_purchase_orders.enqueue_sync_purchase_order"
    },
    "Item": {
        "on_update": "xero.api.xero_items.enqueue_sync_item"
    }
}

# Scheduled Tasks
# ---------------

scheduler_events = {
    # Daily tasks
    "daily": [
        "xero.tasks.sync_all_enabled",
        "xero.tasks.validate_sync_integrity"
    ],
    # Hourly tasks
    "hourly": [
        "xero.tasks.check_payments",
        "xero.tasks.monitor_sync_health",
        "xero.tasks.sync_pending_documents",
        "xero.tasks.sync_contact_notes"
    ],
    # Weekly tasks
    "weekly": [
        "xero.tasks.reconcile_all_entities",
        "xero.tasks.cleanup_old_logs",
        "xero.tasks.purge_resolved_logs"
    ]
}

# Testing
# -------

# before_tests = "xero.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "xero.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "xero.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["xero.utils.before_request"]
# after_request = ["xero.utils.after_request"]

# Job Events
# ----------
# before_job = ["xero.utils.before_job"]
# after_job = ["xero.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"xero.auth.validate"
# ]

fixtures = [
    {
        "doctype": "Role Permission",
        "filters": {
            "role": "Xero Integration Manager",
            "parent": "Xero Settings",
            "permlevel": 0,
        },
        "update": {
            "read": 1, "write": 1, "create": 1, "delete": 1, "submit": 1, "cancel": 1, "amend": 1, "report": 1, "import": 1, "export": 1, "print": 1, "email": 1, "share": 1, "set_user_permissions": 1
        }
    },
    {
        "doctype": "Role Permission",
        "filters": {
            "role": "Xero Integration Manager",
            "parent": "Xero Log",
            "permlevel": 0,
        },
        "update": {
            "read": 1, "write": 1, "create": 1, "delete": 1, "submit": 1, "cancel": 1, "amend": 1, "report": 1, "import": 1, "export": 1, "print": 1, "email": 1, "share": 1, "set_user_permissions": 1
        }
    },
    {
        "doctype": "Role Permission",
        "filters": {
            "role": "Xero Integration Manager",
            "parent": "Xero Account Mapping",
            "permlevel": 0,
        },
        "update": {
            "read": 1, "write": 1, "create": 1, "delete": 1, "submit": 1, "cancel": 1, "amend": 1, "report": 1, "import": 1, "export": 1, "print": 1, "email": 1, "share": 1, "set_user_permissions": 1
        }
    },
    {
        "doctype": "Role Permission",
        "filters": {
            "role": "Xero Integration Manager",
            "parent": "Xero Tax Mapping",
            "permlevel": 0,
        },
        "update": {
            "read": 1, "write": 1, "create": 1, "delete": 1, "submit": 1, "cancel": 1, "amend": 1, "report": 1, "import": 1, "export": 1, "print": 1, "email": 1, "share": 1, "set_user_permissions": 1
        }
    }
]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Whitelisted Methods for API access
# Include the OAuth callback and a future webhook handler
api_method_whitelist = [
    "xero.utils.xero_client.handle_oauth_callback",
    "xero.utils.xero_client.get_available_tenants",
    "xero.utils.xero_client.select_tenant",
    "xero.utils.xero_client.get_auth_url",
    "xero.utils.webhook_handler.handle_webhook",
]

# Website Route Rules: map routes to handlers
# website_route_rules = [
#   {"from_route": "/xero/connect", "to_route": "xero_settings", "defaults": {"initiate_auth": True}},
# ]
