# Copyright (c) 2026, phamos.eu and contributors
# For license information, please see license.txt

"""Kurzarbeit: top a working day up to contractual hours when that leave type is approved."""

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate, today


def get_kurzarbeit_leave_type():
	"""Leave Type selected on HR Addon Settings > Kurzarbeit.

	HR Addon Settings is a Single, so the value lives in tabSingles, not a table column.
	"""
	meta = frappe.get_meta("HR Addon Settings")
	if not meta.has_field("kurzarbeit_leave_type"):
		return None
	return frappe.db.get_single_value("HR Addon Settings", "kurzarbeit_leave_type")


def is_kurzarbeit_leave_type(leave_type):
	if not leave_type:
		return False
	configured = get_kurzarbeit_leave_type()
	return bool(configured) and leave_type == configured


def get_approved_kurzarbeit_leave(employee, log_date):
	"""Submitted, approved Kurzarbeit leave covering log_date, or None."""
	leave_type = get_kurzarbeit_leave_type()
	if not employee or not log_date or not leave_type:
		return None

	log_date = getdate(log_date)
	name = frappe.db.exists(
		"Leave Application",
		{
			"employee": employee,
			"leave_type": leave_type,
			"from_date": ("<=", log_date),
			"to_date": (">=", log_date),
			"docstatus": 1,
			"status": "Approved",
		},
	)
	if not name:
		return None
	return frappe._dict(name=name, leave_type=leave_type)


def kurzarbeit_submit_block_reason(doc):
	"""Why this Kurzarbeit leave cannot be submitted, or None when it can."""
	if not is_kurzarbeit_leave_type(getattr(doc, "leave_type", None)):
		return None
	if getattr(doc, "_action", None) != "submit":
		return None
	if cint(getattr(doc, "half_day", 0)):
		return _("Half Day is not allowed for Kurzarbeit.")
	to_date = getattr(doc, "to_date", None)
	if not to_date or getdate(to_date) >= getdate(today()):
		return _(
			"Kurzarbeit can only be submitted after the To Date. "
			"The whole period must already be in the past so check-ins are final."
		)
	return None


def validate_kurzarbeit_leave(doc):
	reason = kurzarbeit_submit_block_reason(doc)
	if reason:
		frappe.throw(reason)


def apply_kurzarbeit_to_workday(doc):
	"""
	When an approved Kurzarbeit leave covers this day, Actual Working Hours
	become at least the contractual target. Hours above the target stay as they are.
	Kurzarbeit Hours is the amount added. Days without check-ins are On Leave;
	days with check-ins stay Present. Holidays and missing check-ins are left alone.
	"""
	if getattr(doc, "status", None) in ("Not Workday", "Missing Checkin"):
		doc.kurzarbeit_hours = 0
		return

	leave = get_approved_kurzarbeit_leave(getattr(doc, "employee", None), getattr(doc, "log_date", None))
	if not leave:
		doc.kurzarbeit_hours = 0
		return

	target = flt(getattr(doc, "target_hours", 0))
	if target <= 0:
		doc.kurzarbeit_hours = 0
		return

	raw_actual = flt(getattr(doc, "actual_working_hours", 0))
	if raw_actual < target:
		doc.kurzarbeit_hours = flt(target - raw_actual)
		doc.actual_working_hours = target
	else:
		doc.kurzarbeit_hours = 0

	if getattr(doc, "employee_checkins", None):
		doc.status = "Present"
	else:
		doc.status = "On Leave"


def resync_workdays_for_leave(doc):
	"""Create or resave a Workday for each day of a Kurzarbeit application."""
	from hr_addon.hr_addon.doctype.workday.workday import is_non_working_day_for_employee

	if not doc.employee or not doc.from_date or not doc.to_date:
		return
	if not is_kurzarbeit_leave_type(doc.leave_type):
		return

	company = frappe.db.get_value("Employee", doc.employee, "company")
	current = getdate(doc.from_date)
	end = getdate(doc.to_date)
	while current <= end:
		existing = frappe.db.exists(
			"Workday",
			{"employee": doc.employee, "log_date": current},
		)
		non_working = is_non_working_day_for_employee(
			doc.employee, current, leave_type=doc.leave_type
		)
		if existing:
			workday = frappe.get_doc("Workday", existing)
			workday.flags.ignore_permissions = True
			workday.save()
		elif not non_working:
			workday = frappe.new_doc("Workday")
			workday.employee = doc.employee
			workday.company = company
			workday.log_date = current
			workday.flags.ignore_permissions = True
			workday.save()
		current = add_days(current, 1)


def apply_kurzarbeit_on_leave_submit(doc, method=None):
	if getattr(doc, "status", None) == "Rejected":
		return
	resync_workdays_for_leave(doc)


def restore_workdays_on_kurzarbeit_cancel(doc, method=None):
	"""Resave workdays so hours return to the check-in values after cancel."""
	resync_workdays_for_leave(doc)
