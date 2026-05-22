import frappe
from frappe import _
from hr_addon.hr_addon.doctype.overtime_ledger_entry.overtime_ledger_entry import make_ole_entry
from frappe.utils import flt, get_time, getdate
from datetime import datetime, timedelta

def get_effective_ole_target_hours(target_hours, employee=None, log_date=None):
	"""
	Target hours for OLE / Attendance when the date is a half-day holiday (HR Addon Settings).

	If Workday/Attendance still has the full daily target, returns half of the normal day.
	If target is already halved (matches half of Weekly Working Hours), returns it unchanged.
	"""
	from hr_addon.hr_addon.doctype.workday.workday import (
		get_employee_default_work_hour,
		is_half_day_holiday,
	)

	target = flt(target_hours)
	if not log_date or not is_half_day_holiday(log_date):
		return target

	full_day_target = None
	if employee:
		edwh = get_employee_default_work_hour(
			employee, log_date, skip_workday_if_no_weekly_hours=True
		)
		if edwh:
			full_day_target = flt(edwh.hours)

	if full_day_target and full_day_target > 0:
		half_target = full_day_target / 2
		if abs(target - half_target) < 0.01:
			return target
		if abs(target - full_day_target) < 0.01 or target > half_target:
			return half_target

	return target / 2 if target > 0 else target


def get_ole_hour_variance_for_attendance(
	status=None,
	leave_type=None,
	employee=None,
	log_date=None,
	target_hours=None,
	actual_hours=None,
	custom_hour_variance=None,
):
	"""
	Hour variance for Overtime Ledger (Attendance voucher).

	Standard: actual_hours - effective_target_hours.
	On half-day holidays (HR Addon Settings), effective target is half of the normal day
	when the voucher still carries a full-day target.

	Half Day + Leave Type with «Is Deducted From Overtime Ledger»:
		Negate (target - attendance_variance), where attendance_variance is (actual - target)
		(custom_hour_variance). Same as actual - 2 * target, e.g. -2.5 when target 3.5 and variance +1.
	"""
	target = get_effective_ole_target_hours(target_hours, employee, log_date)
	actual = flt(actual_hours)
	standard = actual - target
	if status != "Half Day":
		return standard
	lt = leave_type
	if not lt and employee and log_date:
		la = frappe.db.exists(
			"Leave Application",
			{
				"employee": employee,
				"from_date": ("<=", log_date),
				"to_date": (">=", log_date),
				"docstatus": 1,
			},
		)
		if la:
			lt = frappe.db.get_value("Leave Application", la, "leave_type")
	if not lt or not frappe.db.get_value(
		"Leave Type", lt, "custom_is_deducted_from_overtime_ledger"
	):
		return standard
	hv = flt(custom_hour_variance) if custom_hour_variance is not None else standard
	return -(flt(target) - hv)


def create_overtime_ledger_entry_on_attendance_submit(doc, method=None):
	"""
	Create Overtime Ledger Entry from Attendance on submit
	Creates OLE automatically when hour_variance is non-zero

	Usually hour_variance = actual - target. Half Day + OT-deduct leave type uses
	-(target - (actual - target)) via get_ole_hour_variance_for_attendance.

	Balance calculation happens automatically in OvertimeLedgerEntry.validate()
	"""
	from hr_addon.events.overtime_ledger import is_overtime_ledger_enabled

	if not is_overtime_ledger_enabled():
		return

	# Check if overtime ledger entry already exists
	if hasattr(doc, 'custom_overtime_ledger_entry') and doc.custom_overtime_ledger_entry:
		frappe.msgprint(
			_("Overtime Ledger Entry already exists for this Attendance: {0}").format(doc.custom_overtime_ledger_entry),
			alert=True,
			indicator="orange"
		)
		return
	
	if doc.custom_actual_working_hours is not None and doc.custom_target_hours is not None:
		hour_variance = get_ole_hour_variance_for_attendance(
			status=getattr(doc, "status", None),
			leave_type=getattr(doc, "leave_type", None),
			employee=getattr(doc, "employee", None),
			log_date=getattr(doc, "attendance_date", None),
			target_hours=doc.custom_target_hours,
			actual_hours=doc.custom_actual_working_hours,
			custom_hour_variance=getattr(doc, "custom_hour_variance", None),
		)

		# Create OLE for both positive (overtime) and negative (undertime) variances
		if hour_variance != 0:
			# Get posting time - use out_time or end of day
			# Ensure it's a clean time string (HH:MM:SS format only)
			if doc.out_time:
				from frappe.utils import get_time
				# If out_time is a datetime, extract just the time part
				time_obj = get_time(doc.out_time)
				posting_time = str(time_obj)
			else:
				posting_time = "23:59:59"
			
		# Create overtime ledger entry
		# hour_variance can be positive (overtime) or negative (undertime)
			overtime_ledger_entry = frappe.get_doc({
			"doctype": "Overtime Ledger Entry",
			"employee": doc.employee,
			"voucher_type": "Attendance",
			"voucher_no": doc.name,
			"hour_variance": hour_variance,
			"target_hours": doc.custom_target_hours,
			"actual_hours": doc.custom_actual_working_hours,
			"posting_date": doc.attendance_date,
			"posting_time": posting_time,
			"docstatus": 0
			})
			
			# Insert - balance calculation happens in validate hook
			overtime_ledger_entry.insert(ignore_permissions=True)
			
			# Set checkbox AFTER successful OLE creation
			frappe.db.set_value("Attendance", doc.name, "custom_create_overtime_ledger_entry", 
								1, update_modified=False)
			
			# Link overtime ledger entry back to attendance (bidirectional link)
			# Use frappe.db.set_value since doc is already submitted
			frappe.db.set_value("Attendance", doc.name, "custom_overtime_ledger_entry", 
								overtime_ledger_entry.name, update_modified=False)
			
			frappe.db.commit()
			
			# Show appropriate message based on positive or negative variance
			if hour_variance > 0:
				message = _("Overtime Ledger Entry {0} created: +{1} hours (Balance: {2} hours)").format(
					overtime_ledger_entry.name, hour_variance, overtime_ledger_entry.balance_after)
				indicator = "green"
			else:
				message = _("Overtime Ledger Entry {0} created: {1} hours (Balance: {2} hours)").format(
					overtime_ledger_entry.name, hour_variance, overtime_ledger_entry.balance_after)
				indicator = "orange"
			
			frappe.msgprint(message, alert=True, indicator=indicator)
		else:
			frappe.msgprint(
				_("No hour variance to record. Actual hours ({0}) equals target hours ({1})").format(
					doc.custom_actual_working_hours, doc.custom_target_hours
				),
				alert=True,
				indicator="blue"
			) 

def _resolve_attendance_ole_name(doc):
	"""Linked field on Attendance, or lookup by voucher (handles missing back-links)."""
	ole_name = getattr(doc, "custom_overtime_ledger_entry", None)
	if ole_name and frappe.db.exists("Overtime Ledger Entry", ole_name):
		return ole_name
	return frappe.db.get_value(
		"Overtime Ledger Entry",
		{
			"voucher_type": "Attendance",
			"voucher_no": doc.name,
			"is_cancelled": 0,
		},
		"name",
	)


def reverse_attendance_overtime_ledger_entry(attendance_name, silent=False):
	"""
	Reverse active Overtime Ledger Entry for an Attendance (voucher_type Attendance).
	Used on Attendance.cancel() and to repair rows where docstatus was set without cancel().
	"""
	if not frappe.db.exists("Attendance", attendance_name):
		return False

	doc = frappe.get_doc("Attendance", attendance_name)
	ole_name = _resolve_attendance_ole_name(doc)
	if not ole_name:
		return False

	original_ole = frappe.get_doc("Overtime Ledger Entry", ole_name)
	if original_ole.is_cancelled:
		if not silent:
			frappe.msgprint(
				_("Overtime Ledger Entry {0} is already cancelled").format(ole_name),
				alert=True,
				indicator="orange",
			)
		return False

	time_obj = get_time(original_ole.posting_time)
	dt = datetime.combine(getdate(original_ole.posting_date), time_obj) + timedelta(seconds=1)
	reversal_posting_time = dt.time().strftime("%H:%M:%S")

	reversal_ole = make_ole_entry({
		"employee": original_ole.employee,
		"voucher_type": "Attendance",
		"voucher_no": doc.name,
		"hour_variance": -1 * original_ole.hour_variance,
		"target_hours": original_ole.target_hours,
		"actual_hours": original_ole.actual_hours,
		"posting_date": original_ole.posting_date,
		"posting_time": reversal_posting_time,
		"remarks": f"Reversal of {ole_name} on cancellation of {doc.name}",
		"balance_before": original_ole.balance_after,
		"balance_after": original_ole.balance_before,
	}, allow_when_disabled=True)

	if not reversal_ole:
		frappe.db.set_value("Overtime Ledger Entry", original_ole.name, "is_cancelled", 1, update_modified=True)
		frappe.db.commit()
		return True

	frappe.db.set_value("Overtime Ledger Entry", original_ole.name, "is_cancelled", 1, update_modified=True)
	frappe.db.commit()

	if not silent:
		frappe.msgprint(
			_("Reversal Overtime Ledger Entry {0} created (reversed {1} hours)").format(
				reversal_ole.name,
				original_ole.hour_variance,
			),
			alert=True,
			indicator="red",
		)

	return True


def cancel_overtime_ledger_entry_on_attendance_cancel(doc, method=None):
	"""
	Create reversal Overtime Ledger Entry when Attendance is cancelled
	Following Stock Ledger Entry pattern
	"""
	# Ignore Overtime Ledger Entry links to allow cancellation
	if not hasattr(doc, 'ignore_linked_doctypes'):
		doc.ignore_linked_doctypes = ("Overtime Ledger Entry",)

	reverse_attendance_overtime_ledger_entry(doc.name, silent=False)


def clear_workday_reference_on_attendance_trash(doc, method=None):
	"""Clear the attendance reference on Workday when Attendance is cancelled or trashed."""
	if not getattr(doc, "custom_workday", None):
		return

	try:
		if not frappe.db.exists("Workday", doc.custom_workday):
			return

		workday_attendance = frappe.db.get_value("Workday", doc.custom_workday, "attendance")
		if workday_attendance == doc.name:
			frappe.db.set_value(
				"Workday", doc.custom_workday, "attendance", None, update_modified=False
			)
			frappe.msgprint(
				_("Cleared attendance reference in Workday {0}").format(doc.custom_workday),
				alert=True,
				indicator="blue",
			)
	except Exception:
		pass


@frappe.whitelist()
def delete_workday_and_workday_creation_log_on_attendance_cancel(doc, method=None):
	"""Delete linked Workday and Workday Creation Log when Attendance is cancelled."""
	import json

	if isinstance(doc, str):
		doc = json.loads(doc)

	workday_name = doc.get("custom_workday") if isinstance(doc, dict) else getattr(doc, "custom_workday", None)
	attendance_name = doc.get("name") if isinstance(doc, dict) else doc.name

	if not workday_name:
		return {"error": "No workday found"}

	try:
		if frappe.db.exists("Workday", workday_name):
			frappe.db.set_value("Workday", workday_name, "attendance", None, update_modified=False)

		logs = frappe.get_all(
			"Workday Creation Log",
			filters={"workday": workday_name},
			fields=["name"],
		)
		for log in logs:
			frappe.delete_doc("Workday Creation Log", log.name, force=True)

		if frappe.db.exists("Workday", workday_name):
			frappe.delete_doc("Workday", workday_name, force=True)
			frappe.db.set_value(
				"Attendance", attendance_name, "custom_workday", None, update_modified=False
			)

		frappe.db.commit()
		return "success"
	except Exception as e:
		frappe.log_error(f"Error deleting workday: {str(e)}", "Workday Deletion Error")
		return {"error": str(e)}

