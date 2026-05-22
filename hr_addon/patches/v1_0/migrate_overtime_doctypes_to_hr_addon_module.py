import frappe


OLE_DOCTYPES = ("Overtime Ledger Entry", "Overtime Payout", "Repost Employees OLE")
OLE_REPORTS = ("Overtime Ledger",)


def execute():
	"""Point OLE DocTypes/reports at HR Addon after migration."""
	for name in OLE_DOCTYPES:
		if frappe.db.exists("DocType", name):
			frappe.db.set_value("DocType", name, "module", "HR Addon", update_modified=False)

	for name in OLE_REPORTS:
		if frappe.db.exists("Report", name):
			frappe.db.set_value("Report", name, "module", "HR Addon", update_modified=False)

	_migrate_overtime_frozen_setting()
	frappe.clear_cache()


def _migrate_overtime_frozen_setting():
	"""Copy overtime_frozen from  Settings when HR Addon Settings is empty."""
	if not frappe.db.exists("DocType", "HR Addon Settings"):
		return

	current = frappe.db.get_single_value("HR Addon Settings", "overtime_frozen")
	if current:
		return

	if not frappe.db.exists("DocType", "Suncycle Settings"):
		return

	meta = frappe.get_meta("Suncycle Settings")
	if not meta.has_field("overtime_frozen"):
		return

	legacy = frappe.db.get_single_value("Suncycle Settings", "overtime_frozen")
	if legacy:
		frappe.db.set_single_value("HR Addon Settings", "overtime_frozen", legacy)
