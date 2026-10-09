import frappe
from frappe.utils import cint, flt, getdate
from erpnext.buying.doctype.supplier_scorecard.supplier_scorecard import daterange
from hrms.hr.doctype.leave_application.leave_application import LeaveApplication
from hrms.hr.utils import get_holiday_dates_for_employee


def get_half_day_holiday_dates(from_date, to_date, employee=None, leave_type=None):
	"""Half Day Holidays in the leave range that are not already full holidays."""
	if not from_date or not to_date:
		return []

	rows = frappe.get_all(
		"Half Day Holidays",
		filters={
			"parent": "HR Addon Settings",
			"parenttype": "HR Addon Settings",
			"parentfield": "half_day_holidays",
			"holiday_date": ["between", [getdate(from_date), getdate(to_date)]],
		},
		pluck="holiday_date",
	)
	dates = [getdate(d) for d in rows if d]
	if employee and leave_type and not frappe.db.get_value("Leave Type", leave_type, "include_holiday"):
		full_holidays = {getdate(d) for d in get_holiday_dates_for_employee(employee, from_date, to_date)}
		dates = [d for d in dates if d not in full_holidays]
	return sorted(dates)


@frappe.whitelist()
def get_total_leave_days(employee, leave_type, from_date, to_date, half_day=None, half_day_date=None):
	"""HRMS leave days, then 0.5 for each other Half Day Holiday."""
	from hrms.hr.doctype.leave_application.leave_application import get_number_of_leave_days

	days = get_number_of_leave_days(employee, leave_type, from_date, to_date, half_day, half_day_date)
	return reduce_leave_days_for_half_day_holidays(
		days, employee, leave_type, from_date, to_date, half_day, half_day_date
	)


@frappe.whitelist()
def get_first_half_day_holiday(from_date, to_date, employee=None, leave_type=None):
	"""Earliest Half Day Holiday in the leave range, for the Half Day Date field."""
	dates = get_half_day_holiday_dates(from_date, to_date, employee, leave_type)
	return dates[0] if dates else None


@frappe.whitelist()
def get_half_day_holiday_in_leave(from_date, to_date, employee=None, leave_type=None):
	"""Same as get_first_half_day_holiday. Kept so an already open form can call it."""
	return get_first_half_day_holiday(from_date, to_date, employee, leave_type)


def reduce_leave_days_for_half_day_holidays(
	number_of_days, employee, leave_type, from_date, to_date, half_day=None, half_day_date=None
):
	"""Count each Half Day Holiday as 0.5. Skip a date HRMS already counted as a half day."""
	dates = get_half_day_holiday_dates(from_date, to_date, employee, leave_type)
	if cint(half_day) and from_date and to_date:
		if getdate(from_date) == getdate(to_date):
			already_half = getdate(from_date)
		elif half_day_date:
			already_half = getdate(half_day_date)
		else:
			already_half = None
		if already_half:
			dates = [d for d in dates if d != already_half]
	if not dates:
		return number_of_days

	adjusted = flt(number_of_days) - (0.5 * len(dates))
	if adjusted < 0:
		adjusted = 0
	if adjusted == int(adjusted):
		return int(adjusted)
	return adjusted


class HrAddonLeaveApplication(LeaveApplication):
	def validate(self):
		self.set_first_half_day_holiday()
		super().validate()
		self.total_leave_days = reduce_leave_days_for_half_day_holidays(
			self.total_leave_days,
			self.employee,
			self.leave_type,
			self.from_date,
			self.to_date,
			self.half_day,
			self.half_day_date,
		)

	def set_first_half_day_holiday(self):
		"""Store the first Half Day Holiday in Half Day Date. Other half days stay in the day count."""
		first = get_first_half_day_holiday(
			self.from_date, self.to_date, self.employee, self.leave_type
		)
		if not first:
			return
		self.half_day = 1
		self.half_day_date = first

	def _leave_type_deducts_from_ot_ledger(self):
		lt = getattr(self, "leave_type", None)
		if not lt:
			return False
		return bool(
			frappe.db.get_value("Leave Type", lt, "custom_is_deducted_from_overtime_ledger")
		)

	def _reconcile_ot_leave_attendance_name(self, date, attendance_name):
		"""Amend/cancel flow cancels Attendance (docstatus 2); core update_attendance only
		looks for docstatus != 2, so submit of amended LA inserts a duplicate row.

		For OT-deduct leave: prefer reviving the cancelled row and cancelling any stray
		submitted duplicate for the same day, then update that single Attendance.
		"""
		if not self._leave_type_deducts_from_ot_ledger():
			return attendance_name

		cancelled_rows = frappe.db.sql(
			"""
			select name from `tabAttendance`
			where employee = %(employee)s and attendance_date = %(d)s and docstatus = 2
				and status in ('On Leave', 'Half Day')
			order by modified desc
			limit 1
			""",
			{"employee": self.employee, "d": date},
		)
		cancelled_name = cancelled_rows[0][0] if cancelled_rows else None

		if cancelled_name and attendance_name and attendance_name != cancelled_name:
			frappe.db.set_value(
				"Attendance",
				cancelled_name,
				"docstatus",
				1,
				update_modified=True,
			)
			try:
				dup = frappe.get_doc("Attendance", attendance_name)
				dup.flags.ignore_permissions = True
				if dup.docstatus == 1:
					dup.cancel()
			except Exception as e:
				frappe.log_error(
					title="Leave amend: cancel duplicate attendance",
					message=f"{attendance_name}: {e}",
				)
			return cancelled_name

		if cancelled_name and not attendance_name:
			frappe.db.set_value(
				"Attendance",
				cancelled_name,
				"docstatus",
				1,
				update_modified=True,
			)
			return cancelled_name

		return attendance_name

	def update_attendance(self):
		if self.status != "Approved":
			return

		holiday_dates = []
		if not frappe.db.get_value("Leave Type", self.leave_type, "include_holiday"):
			holiday_dates = get_holiday_dates_for_employee(self.employee, self.from_date, self.to_date)

		for dt in daterange(getdate(self.from_date), getdate(self.to_date)):
			date = dt.strftime("%Y-%m-%d")
			attendance_name = frappe.db.exists(
				"Attendance",
				dict(
					employee=self.employee,
					attendance_date=date,
					docstatus=("!=", 2),
				),
			)
			if self._leave_type_deducts_from_ot_ledger():
				attendance_name = self._reconcile_ot_leave_attendance_name(date, attendance_name)

			if date in holiday_dates:
				if attendance_name:
					attendance = frappe.get_doc("Attendance", attendance_name)
					attendance.flags.ignore_permissions = True
					if attendance.docstatus == 1:
						attendance.cancel()
					frappe.delete_doc("Attendance", attendance_name, force=1)
				continue

			self.create_or_update_attendance(attendance_name, date)

	def cancel_attendance(self):
		"""
		Cancel leave-linked Attendance via Document.cancel() so server hooks run
		(e.g. Overtime Ledger reversal on Attendance on_cancel).

		HRMS core uses frappe.db.set_value(..., docstatus, 2), which bypasses
		Attendance.cancel() and leaves OLE rows active.
		"""
		if self.docstatus != 2:
			return

		attendance_rows = frappe.db.sql(
			"""
			select name from `tabAttendance`
			where employee = %(employee)s
				and attendance_date between %(from_date)s and %(to_date)s
				and docstatus < 2
				and status in ('On Leave', 'Half Day')
			""",
			{
				"employee": self.employee,
				"from_date": self.from_date,
				"to_date": self.to_date,
			},
			as_dict=True,
		)

		for row in attendance_rows:
			doc = frappe.get_doc("Attendance", row.name)
			doc.flags.ignore_permissions = True
			doc.cancel()
