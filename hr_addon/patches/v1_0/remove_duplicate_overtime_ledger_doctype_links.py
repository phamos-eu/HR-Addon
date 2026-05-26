import frappe

ATTENDANCE_OLE_LINK_NAME = "overtime_ledger_entry_link_att"
LEGACY_LEAVE_OLE_LINK_NAMES = (
	"overtime_ledger_entry_link",
	"kmmh7aljsr",
)


def execute():
	"""Keep OLE dashboard link on Attendance only; remove Leave Application OLE links."""
	_remove_leave_application_ole_links()
	_deduplicate_attendance_ole_links()
	frappe.clear_cache(doctype="DocType")


def _remove_leave_application_ole_links():
	for legacy_name in LEGACY_LEAVE_OLE_LINK_NAMES:
		if not frappe.db.exists("DocType Link", legacy_name):
			continue
		if frappe.db.get_value("DocType Link", legacy_name, "parent") != "Leave Application":
			continue
		frappe.delete_doc("DocType Link", legacy_name, force=True, ignore_permissions=True)

	for name in frappe.get_all(
		"DocType Link",
		filters={
			"parenttype": "DocType",
			"parent": "Leave Application",
			"link_doctype": "Overtime Ledger Entry",
		},
		pluck="name",
	):
		frappe.delete_doc("DocType Link", name, force=True, ignore_permissions=True)

	frappe.db.commit()


def _deduplicate_attendance_ole_links():
	names = frappe.get_all(
		"DocType Link",
		filters={
			"parenttype": "DocType",
			"parent": "Attendance",
			"link_doctype": "Overtime Ledger Entry",
		},
		pluck="name",
	)
	for name in names:
		if name == ATTENDANCE_OLE_LINK_NAME:
			continue
		frappe.delete_doc("DocType Link", name, force=True, ignore_permissions=True)

	frappe.db.commit()
