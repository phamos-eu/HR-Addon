import frappe
from frappe import _
from datetime import datetime, timedelta

from frappe.utils import add_days, flt, get_time, getdate

from hr_addon.events.overtime_ledger import get_employee_overtime_balance
from hr_addon.hr_addon.doctype.overtime_ledger_entry.overtime_ledger_entry import make_ole_entry
from hr_addon.hr_addon.doctype.workday.workday import get_employee_default_work_hour


def validate_leave_application(doc, method=None):
	"""
	Validate Leave Application before submission.
	Check if employee has sufficient overtime balance for leave types that deduct from overtime.
	"""
	if frappe.flags.get("skip_overtime_leave_validation"):
		return

	if not doc.leave_type:
		return

	is_deducted = frappe.db.get_value(
		"Leave Type", doc.leave_type, "custom_is_deducted_from_overtime_ledger"
	)
	if not is_deducted:
		return

	balance_info = get_employee_overtime_balance(doc.employee)
	current_balance = flt(balance_info.get("balance"))

	employee_default_work_hour = get_employee_default_work_hour(
		doc.employee, doc.from_date, skip_workday_if_no_weekly_hours=True
	)
	if employee_default_work_hour is None:
		return None

	total_leave_days = flt(doc.total_leave_days)

	if doc.half_day and doc.half_day_date:
		full_days = total_leave_days - 0.5
		leave_application_hours = (full_days * employee_default_work_hour.hours) + (
			employee_default_work_hour.hours / 2
		)
	else:
		leave_application_hours = total_leave_days * employee_default_work_hour.hours

	is_half_day_only = doc.half_day and total_leave_days == 0.5

	if not is_half_day_only:
		if current_balance < employee_default_work_hour.hours:
			frappe.throw(
				_(
					"Minimum overtime balance of {0} hours (one full day) required for Leave Type '{1}'. Current balance: {2} hours"
				).format(
					employee_default_work_hour.hours,
					doc.leave_type,
					current_balance,
				)
			)

	if current_balance < leave_application_hours:
		if is_half_day_only:
			leave_desc = "half day ({0} hours)".format(leave_application_hours)
		elif doc.half_day:
			leave_desc = "{0} day(s) including half day ({1} hours)".format(
				total_leave_days, leave_application_hours
			)
		else:
			leave_desc = "{0} day(s) ({1} hours)".format(total_leave_days, leave_application_hours)

		frappe.throw(
			_(
				"Insufficient overtime balance for {0} of Leave Type '{1}'. Required: {2} hours, Available: {3} hours"
			).format(leave_desc, doc.leave_type, leave_application_hours, current_balance)
		)

	if is_half_day_only:
		leave_desc = "half day"
	elif doc.half_day:
		leave_desc = "{0} day(s) including half day".format(total_leave_days)
	else:
		leave_desc = "{0} day(s)".format(total_leave_days)

	frappe.msgprint(
		_(
			"This {0} leave will deduct {1} hours from overtime balance. Current balance: {2} hours, Balance after leave: {3} hours"
		).format(
			leave_desc,
			leave_application_hours,
			current_balance,
			current_balance - leave_application_hours,
		),
		indicator="blue",
		alert=True,
	)


def reduce_overtime_on_leave_submit(doc, method=None):
	"""
	OT deduction for OT-deducting leave types is done via Workday → Attendance →
	Attendance.on_submit, not here, to avoid double-counting with per-day Attendance OLEs.
	"""
	pass


def _cancel_attendance_for_ot_leave_period(doc):
	"""Cancel submitted Attendance for each Workday in the leave period (reverses OLE on Attendance)."""
	d = getdate(doc.from_date)
	end = getdate(doc.to_date)
	cancelled_count = 0
	while d <= end:
		wn = frappe.db.get_value(
			"Workday",
			{"employee": doc.employee, "log_date": d},
			"name",
		)
		if wn:
			att_name = frappe.db.get_value("Workday", wn, "attendance")
			if att_name and frappe.db.get_value("Attendance", att_name, "docstatus") == 1:
				try:
					frappe.get_doc("Attendance", att_name).cancel()
					cancelled_count += 1
				except Exception as e:
					frappe.log_error(
						title="Leave cancel: Attendance cancel failed",
						message=f"Leave Application {doc.name}, Attendance {att_name}: {e}",
					)
		d = add_days(d, 1)
	if cancelled_count:
		frappe.msgprint(
			_(
				"Cancelled {0} attendance record(s); overtime deductions linked to those days were reversed."
			).format(cancelled_count),
			alert=True,
			indicator="blue",
		)


def reverse_workday_leave_ole(workday_name, silent=True):
	"""
	Reverse active Overtime Ledger Entry for a Workday (legacy leave deduction voucher Workday).
	"""
	if not workday_name:
		return False

	ole_name = frappe.db.get_value(
		"Overtime Ledger Entry",
		{
			"voucher_type": "Workday",
			"voucher_no": workday_name,
			"is_cancelled": 0,
		},
		"name",
	)
	if not ole_name:
		return False

	original_ole = frappe.get_doc("Overtime Ledger Entry", ole_name)

	time_obj = get_time(original_ole.posting_time)
	dt = datetime.combine(getdate(original_ole.posting_date), time_obj) + timedelta(seconds=1)
	new_posting_time = dt.time().strftime("%H:%M:%S")

	make_ole_entry({
		"employee": original_ole.employee,
		"voucher_type": "Workday",
		"voucher_no": workday_name,
		"hour_variance": -1 * original_ole.hour_variance,
		"posting_date": original_ole.posting_date,
		"posting_time": new_posting_time,
		"remarks": f"Reversal of {ole_name} for Workday {workday_name}",
		"balance_before": original_ole.balance_after,
		"balance_after": original_ole.balance_before,
	})

	frappe.db.set_value("Overtime Ledger Entry", original_ole.name, "is_cancelled", 1, update_modified=True)

	if frappe.db.exists("Workday", workday_name) and frappe.db.has_column(
		"Workday", "custom_overtime_ledger_entry"
	):
		frappe.db.set_value(
			"Workday", workday_name, "custom_overtime_ledger_entry", None, update_modified=False
		)

	frappe.db.commit()

	if not silent:
		frappe.msgprint(
			_("Reversal Overtime Ledger Entry created (restored {0} hours) for Workday {1}").format(
				abs(original_ole.hour_variance),
				workday_name,
			),
			alert=True,
			indicator="red",
		)

	return True


def restore_overtime_on_leave_cancel(doc, method=None):
	"""
	Restore overtime when leave is cancelled:
	1) Cancel submitted Attendance linked from Workdays in the leave period.
	2) Legacy: reverse a single OLE voucher Leave Application if present.
	3) Legacy: reverse any remaining Workday-voucher OLEs for workdays in the leave period.
	"""
	if not doc.leave_type:
		return

	is_deducted = frappe.db.get_value(
		"Leave Type", doc.leave_type, "custom_is_deducted_from_overtime_ledger"
	)
	if not is_deducted:
		return

	_cancel_attendance_for_ot_leave_period(doc)

	ole_name = frappe.db.get_value(
		"Overtime Ledger Entry",
		{
			"voucher_type": "Leave Application",
			"voucher_no": doc.name,
			"is_cancelled": 0,
		},
		"name",
	)
	if ole_name:
		original_ole = frappe.get_doc("Overtime Ledger Entry", ole_name)

		time_obj = get_time(original_ole.posting_time)
		dt = datetime.combine(getdate(original_ole.posting_date), time_obj) + timedelta(seconds=1)
		new_posting_time = dt.time().strftime("%H:%M:%S")

		make_ole_entry({
			"employee": original_ole.employee,
			"voucher_type": "Leave Application",
			"voucher_no": doc.name,
			"hour_variance": -1 * original_ole.hour_variance,
			"posting_date": original_ole.posting_date,
			"posting_time": new_posting_time,
			"remarks": f"Reversal of {ole_name} on cancellation of {doc.name}",
			"balance_before": original_ole.balance_after,
			"balance_after": original_ole.balance_before,
		})

		frappe.db.set_value("Overtime Ledger Entry", original_ole.name, "is_cancelled", 1, update_modified=True)
		frappe.db.commit()

		frappe.msgprint(
			_("Reversal Overtime Ledger Entry created (restored {0} hours)").format(
				abs(original_ole.hour_variance)
			),
			alert=True,
			indicator="red",
		)

	workdays = frappe.get_all(
		"Workday",
		filters={
			"employee": doc.employee,
			"log_date": ["between", [doc.from_date, doc.to_date]],
		},
		pluck="name",
	)

	for wd in workdays:
		reverse_workday_leave_ole(wd, silent=True)
