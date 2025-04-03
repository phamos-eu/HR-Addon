# Copyright (c) 2022, phamos.eu and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.query_builder import Case, Order

def execute(filters=None):
	columns = get_columns()
	data = get_data(filters)

	return columns, data


def get_data(filters):
	workday = frappe.qb.DocType("Workday")
	query = (
		frappe.qb.from_(workday)
		.select(
			workday.name,
			workday.log_date,
			workday.employee,
			workday.attendance,
			workday.status,
			(workday.hours_worked * 3600).as_("total_work_seconds"),
			(workday.break_hours * 3600).as_("total_break_seconds"),
			(workday.actual_working_hours * 3600).as_("actual_working_seconds"),
			(workday.expected_break_hours * 3600).as_("expected_break_hours"),
			(workday.target_hours * 3600).as_("total_target_seconds"),
			(Case()
				.when(workday.hours_worked * 3600 < 0, 0)
				.else_(workday.hours_worked * 3600) - (workday.target_hours * 3600)
			).as_("diff_log"),
			(Case()
				.when(workday.actual_working_hours < 0, workday.actual_working_hours * 3600)
				.else_(workday.actual_working_hours * 3600 - (workday.target_hours * 3600))
			).as_("actual_diff_log"),
			(workday.first_checkin).as_("first_in"),
			(workday.last_checkout).as_("last_out"),
		)
		.where(workday.docstatus < 2)
		.orderby(workday.log_date, order=Order.asc)
	)

	if filters.get("date_from_filter") and filters.get("date_to_filter"):
		query = query.where(
			(workday.log_date >= filters.get("date_from_filter")) & (workday.log_date <= filters.get("date_to_filter"))
		)

	if filters.get("employee_id"):
		query = query.where(workday.employee == filters.get("employee_id"))

	data = query.run(as_dict=True)

	for d in data:
		if d.get("first_in"):
			d["first_in"] = frappe.utils.get_timedelta(d.get("first_in"))
		if d.get("last_out"):
			d["last_out"] = frappe.utils.get_timedelta(d.get("last_out"))
	return data


def get_columns():
	return [		
		{'fieldname':'log_date','label':'Date','width':110},		
		{'fieldname':'name','label':'Work Day',  "fieldtype": "Link", "options": "Workday", 'width':200,},		
		{'fieldname':'status','label':'Status', "width": 80},
		{'fieldname':'total_work_seconds','label':_('Work Hours'), "width": 110, },
		# {'fieldname':'total_break_seconds','label':_('Break Hours'), "width": 110, },
		{'fieldname':'expected_break_hours','label':'Expected Break Hours','width':80},
		{'fieldname':'actual_working_seconds','label':_('Actual Working Hours'), "width": 110, },
		{'fieldname':'total_target_seconds','label':'Target Hours','width':130},
		# {'fieldname':'diff_log','label':'Diff (Work Hours - Target Seconds)','width':90},
		{'fieldname':'actual_diff_log','label':'Diff (Actual Working Hours - Target Seconds)','width':110},
		{'fieldname':'first_in','label':'First Checkin','width':100},
		{'fieldname':'last_out','label':'Last Checkout','width':100},
		{'fieldname':'attendance','label':'Attendance','width': 160},
	]