import frappe

from hr_addon.hr_addon.doctype.workday.workday import (
	create_background_job_for_workday_generation_after_install,
)

# Monthly naming series (suncycle#2483). The counter starts again every month,
# so it can no longer run past 99999. Frappe adds ".#####" to the series.
# Keep these in sync with the naming_series field in each doctype JSON.
WORKDAY_NAMING_SERIES = {
	"Workday": "WD-.YYYY.-.MM.-",
	"Workday Creation Log": "WCL-.YYYY.-.MM.-",
	"Workday Generation Log": "WGL-.YYYY.-.MM.-",
}


def after_install():
	create_background_job_for_workday_generation_after_install()
	setup_workday_naming_series()


def setup_workday_naming_series():
	"""Make the naming series from the doctype JSON the active one on this site.

	The series itself ships in the doctype JSON. A site can override it with
	Property Setters (set by hand in Document Naming Settings or Customize Form),
	so remove those for the naming fields of the Workday doctypes.
	"""
	for doctype in WORKDAY_NAMING_SERIES:
		if not frappe.db.exists("DocType", doctype):
			continue

		overrides = frappe.get_all(
			"Property Setter",
			filters={"doc_type": doctype, "field_name": "naming_series", "property": ["in", ["options", "default"]]},
			pluck="name",
		) + frappe.get_all(
			"Property Setter",
			filters={"doc_type": doctype, "doctype_or_field": "DocType", "property": ["in", ["autoname", "naming_rule"]]},
			pluck="name",
		)
		for name in overrides:
			frappe.delete_doc("Property Setter", name, ignore_permissions=True, force=True)

		frappe.clear_cache(doctype=doctype)
