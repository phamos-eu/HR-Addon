import frappe
from erpnext.buying.doctype.supplier_scorecard.supplier_scorecard import daterange
from frappe.utils import getdate
from hrms.hr.doctype.leave_application.leave_application import LeaveApplication
from hrms.hr.utils import get_holiday_dates_for_employee


class HrAddonLeaveApplication(LeaveApplication):
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
