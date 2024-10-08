# Copyright (c) 2022, Jide Olayinka and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def execute(filters=None):
	columns, data = [], []
	condition_date,condition_employee = "",""
	if filters.date_from_filter and filters.date_to_filter :
		if filters.date_from_filter == None:
			filters.date_from_filter = frappe.datetime.get_today()
		if filters.date_to_filter == None:
			filters.date_to_filter = frappe.datetime.get_today()
		condition_date = "AND log_date BETWEEN '"+ filters.date_from_filter + \
        "' AND '" + filters.date_to_filter + "'"

	if filters.get("employee_id"):
		empid = filters.get("employee_id")
		condition_employee += f" AND employee = '{empid}'"
	# #{'fieldname':'employee','label':'Employee','width':160},
	# {'fieldname':'target_hours','label':'Target Hours','width':80},
	columns = [		
		{'fieldname':'log_date','label':'Date','width':110},		
		{'fieldname':'name','label':'Work Day',  "fieldtype": "Link", "options": "Workday", 'width':200,},		
		{'fieldname':'status','label':'Status', "width": 80},
		{'fieldname':'total_work_seconds','label':_('Work Hours'), "width": 110, },
		# {'fieldname':'total_break_seconds','label':_('Break Hours'), "width": 110, },
		{'fieldname':'expected_break_hours','label':'Expected Break Hours','width':80},
		{'fieldname':'actual_working_seconds','label':_('Actual Working Hours'), "width": 110, },
		{'fieldname':'total_target_seconds','label':'Target Seconds','width':80},
		# {'fieldname':'diff_log','label':'Diff (Work Hours - Target Seconds)','width':90},
		{'fieldname':'actual_diff_log','label':'Diff (Actual Working Hours - Target Seconds)','width':90},
		{'fieldname':'first_in','label':'First Checkin','width':100},
		{'fieldname':'last_out','label':'Last Checkout','width':100},
		{'fieldname':'attendance','label':'Attendance','width': 160},
		
	]
	work_data = frappe.db.sql(
    """
    SELECT 
        name,
        hours_worked,
        log_date,
        employee,
        attendance,
        status,
        CASE 
            WHEN total_work_seconds < 0 and total_work_seconds != -129600
            THEN 0
            ELSE total_work_seconds
        END AS total_work_seconds,
        total_break_seconds,
        actual_working_hours * 60 * 60 AS actual_working_seconds,
        expected_break_hours * 60 * 60 AS expected_break_hours,
        target_hours,
        total_target_seconds,
        (CASE 
            WHEN total_work_seconds < 0 
            THEN 0
            ELSE total_work_seconds
        END - total_target_seconds) AS diff_log,
		(CASE 
            WHEN actual_working_hours < 0 
            THEN (0 - total_target_seconds)
            ELSE (actual_working_hours * 60 * 60 - total_target_seconds)
        END) AS actual_diff_log,
        TIME(first_checkin) AS first_in,
        TIME(last_checkout) AS last_out 
    FROM `tabWorkday` 
    WHERE docstatus < 2 %s %s 
    ORDER BY log_date ASC
    """ % (condition_date, condition_employee),
    as_dict=1,
)

	
	data = work_data

	return columns, data
#(actual_working_hours * 60 * 60 - total_target_seconds) AS actual_diff_log,64to68