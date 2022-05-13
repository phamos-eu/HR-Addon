# Copyright (c) 2022, Jide Olayinka and contributors
# For license information, please see license.txt

from pydoc import doc
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, cstr, formatdate, get_datetime, getdate, nowdate

from hr_addon.hr_addon.api.utils import view_actual_employee_log
from erpnext.hr.utils import get_holiday_dates_for_employee, validate_active_employee

class Workday(Document):
	pass

#mark_bulk_attendance
@frappe.whitelist()
def process_bulk_workday(data):
	'''bulk workday processing'''
	import json
	if isinstance(data, str):
		data = json.loads(data)
	data = frappe._dict(data)
	company = frappe.get_value('Employee', data.employee, 'company')
	if not data.unmarked_days:
		frappe.throw(_("Please select a date"))
		return
	
	for date in data.unmarked_days:
		single = []
		single = view_actual_employee_log(data.employee, get_datetime(date))
		c_single = single[0]["items"]
		
		if((not single[0]["items"] is None) and (len(single[0]["items"]) > 0)):
			""" e_checkins = {
			'employee_checkin': c_single[0]["name"],
			'log_type': c_single[0]["log_type"],
			'log_time': c_single[0]["time"],
			'skip_auto_attendance': c_single[0]["skip_auto_attendance"]
			} """
				
			doc_dict = {
			'doctype': 'Workday',
			'employee': data.employee,
			'log_date': get_datetime(date),
			'company': company,
			'attendance':single[0]["attendance"],
			'target_hours':single[0]["thour"],
			'hours_worked':"{:.2f}".format(single[0]["ahour"]/3600),
			'break_hours': "{:.2f}".format(single[0]["bhour"]/3600),
			}	
			workday = frappe.get_doc(doc_dict).insert()
			
			for i in range(len(c_single)):
				row = workday.append("employee_checkins", {
					'employee_checkin': c_single[i]["name"],
					'log_type': c_single[i]["log_type"],
					'log_time': c_single[i]["time"],
					'skip_auto_attendance': c_single[i]["skip_auto_attendance"],
					'parent':workday
				})
			
			
			workday.save()
			
			#workday.submit() 
	

def get_month_map():
	return frappe._dict({
		"January": 1,
		"February": 2,
		"March": 3,
		"April": 4,
		"May": 5,
		"June": 6,
		"July": 7,
		"August": 8,
		"September": 9,
		"October": 10,
		"November": 11,
		"December": 12
		})
	
@frappe.whitelist()
def get_unmarked_days(employee, month, exclude_holidays=0):
	import calendar
	month_map = get_month_map()
	today = get_datetime()
	

	joining_date, relieving_date = frappe.get_cached_value("Employee", employee, ["date_of_joining", "relieving_date"])
	start_day = 1
	end_day = calendar.monthrange(today.year, month_map[month])[1] + 1

	if joining_date and joining_date.month == month_map[month]:
		start_day = joining_date.day

	if relieving_date and relieving_date.month == month_map[month]:
		end_day = relieving_date.day + 1

	dates_of_month = ['{}-{}-{}'.format(today.year, month_map[month], r) for r in range(start_day, end_day)]
	month_start, month_end = dates_of_month[0], dates_of_month[-1]

	""" ["docstatus", "!=", 2]"""
	rcords = frappe.get_list("Workday", fields=['log_date','employee'], filters=[
		["log_date",">=",month_start],
		["log_date","<=",month_end],
		["employee","=",employee]
	])

	marked_days = [get_datetime(rcord.log_date) for rcord in rcords]
	if cint(exclude_holidays):
		holiday_dates = get_holiday_dates_for_employee(employee, month_start, month_end)
		holidays = [get_datetime(rcord) for rcord in holiday_dates]
		marked_days.extend(holidays)

	unmarked_days = []

	for date in dates_of_month:
		date_time = get_datetime(date)
		if today.day <= date_time.day and today.month <= date_time.month:
			break
		if date_time not in marked_days:
			unmarked_days.append(date)

	return unmarked_days
