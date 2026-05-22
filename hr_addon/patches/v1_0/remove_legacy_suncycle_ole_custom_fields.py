import frappe

# Custom fields now owned by hr_addon fixtures (module HR Addon).
LEGACY_OLE_CUSTOM_FIELDS = {
	"Attendance": (
		"custom_working_hours_details",
		"custom_target_hours",
		"custom_workday",
		"custom_actual_working_hours",
		"custom_hour_variance",
		"custom_column_break_salzc",
		"custom_create_overtime_ledger_entry",
		"custom_overtime_ledger_entry",
	),
	"Employee": (
		"custom_working_hours",
		"custom_weekly_working_hours",
		"custom_working_hours_cb",
		"custom_total_work_hours",
		"custom_overtime_ledger_details",
		"custom_current_overtime_hours",
		"custom_column_break_r4uli",
		"custom_overtime_ledger_entry",
	),
	"Leave Type": ("custom_is_deducted_from_overtime_ledger",),
}


def execute():
	"""Remove duplicate OLE/working-hours custom fields still registered under Suncycle."""
	for dt, fieldnames in LEGACY_OLE_CUSTOM_FIELDS.items():
		for fieldname in fieldnames:
			legacy_names = frappe.get_all(
				"Custom Field",
				filters={"dt": dt, "fieldname": fieldname, "module": ["!=", "HR Addon"]},
				pluck="name",
			)
			for name in legacy_names:
				frappe.delete_doc("Custom Field", name, force=True, ignore_permissions=True)

	frappe.clear_cache(doctype="Custom Field")
