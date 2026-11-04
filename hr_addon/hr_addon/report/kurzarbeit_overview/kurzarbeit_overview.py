# Copyright (c) 2026, phamos.eu and contributors
# For license information, please see license.txt

"""Export of Kurzarbeit days: date, employee, and hours added up to the contractual target."""

import frappe
from frappe import _
from frappe.query_builder import DocType
from frappe.query_builder.functions import Coalesce
from frappe.utils import flt, getdate

from hr_addon.hr_addon.kurzarbeit import get_kurzarbeit_leave_type


def execute(filters=None):
	if isinstance(filters, str):
		filters = frappe.parse_json(filters)
	filters = filters or {}
	columns = get_columns()
	leave_type = get_kurzarbeit_leave_type()
	if not leave_type:
		frappe.msgprint(_("Select a Kurzarbeit Leave Type in HR Addon Settings."))
		return columns, []
	return columns, get_data(filters, leave_type)


def get_columns():
	return [
		{"fieldname": "log_date", "label": _("Date"), "fieldtype": "Date", "width": 120},
		{
			"fieldname": "employee",
			"label": _("Employee"),
			"fieldtype": "Link",
			"options": "Employee",
			"width": 140,
		},
		{"fieldname": "employee_name", "label": _("Employee Name"), "fieldtype": "Data", "width": 180},
		{
			"fieldname": "contractual_hours",
			"label": _("Contractual Hours"),
			"fieldtype": "Float",
			"precision": 2,
			"width": 140,
		},
		{
			"fieldname": "raw_actual_hours",
			"label": _("Raw Actual Hours"),
			"fieldtype": "Float",
			"precision": 2,
			"width": 140,
		},
		{
			"fieldname": "kurzarbeit_hours",
			"label": _("Kurzarbeit Hours Added"),
			"fieldtype": "Float",
			"precision": 2,
			"width": 170,
		},
		{
			"fieldname": "leave_application",
			"label": _("Leave Application"),
			"fieldtype": "Link",
			"options": "Leave Application",
			"width": 180,
		},
	]


def get_data(filters, leave_type):
	workday = DocType("Workday")
	leave = DocType("Leave Application")

	added = Coalesce(workday.kurzarbeit_hours, 0)
	query = (
		frappe.qb.from_(workday)
		.join(leave)
		.on(
			(leave.employee == workday.employee)
			& (leave.leave_type == leave_type)
			& (leave.docstatus == 1)
			& (leave.status == "Approved")
			& (leave.from_date <= workday.log_date)
			& (leave.to_date >= workday.log_date)
		)
		.select(
			workday.log_date,
			workday.employee,
			workday.employee_name,
			workday.target_hours.as_("contractual_hours"),
			(workday.actual_working_hours - added).as_("raw_actual_hours"),
			added.as_("kurzarbeit_hours"),
			leave.name.as_("leave_application"),
		)
		.orderby(workday.log_date)
		.orderby(workday.employee)
	)

	from_date = filters.get("from_date")
	to_date = filters.get("to_date")
	if from_date:
		query = query.where(workday.log_date >= getdate(from_date))
	if to_date:
		query = query.where(workday.log_date <= getdate(to_date))
	if filters.get("employee"):
		query = query.where(workday.employee == filters.get("employee"))

	rows = query.run(as_dict=True)
	for row in rows:
		row.contractual_hours = flt(row.contractual_hours, 2)
		row.raw_actual_hours = flt(row.raw_actual_hours, 2)
		row.kurzarbeit_hours = flt(row.kurzarbeit_hours, 2)
	return rows
