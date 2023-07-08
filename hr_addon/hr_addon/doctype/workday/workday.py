# Copyright (c) 2022, Jide Olayinka and contributors
# For license information, please see license.txt

from datetime import timedelta
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import make_autoname
from frappe.utils import cint, cstr, formatdate, get_datetime, getdate, nowdate,add_days
from frappe.utils.data import date_diff
from datetime import date,datetime

from hr_addon.hr_addon.api.utils import view_actual_employee_log,get_actual_employee_log_bulk


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
		if not date_is_in_holiday_list(data.employee, get_datetime(date)):
			single = []
			#single = view_actual_employee_log(data.employee, get_datetime(date))
			single = get_actual_employee_log_bulk(data.employee, get_datetime(date))
			c_single = single[0]["items"]		
			doc_dict = {
				'doctype': 'Workday',
				'employee': data.employee,
				'log_date': get_datetime(date),
				'company': company,
				'attendance':single[0]["attendance"],
				'hours_worked':"{:.2f}".format(single[0]["ahour"]/(60*60)),
				'break_hours': "{:.2f}".format(single[0]["bhour"]/(60*60)),
				'expected_break_hours': "{:.2f}".format(single[0]["break_minutes"]/(60)),
				'total_work_seconds':single[0]["ahour"],
				'total_break_seconds':single[0]["bhour"],
				'actual_working_hours': "{:.2f}".format(single[0]["ahour"]/(60*60) - single[0]["break_minutes"]/60)
			}
			workday = frappe.get_doc(doc_dict).insert()
			target_hours = single[0]["thour"]
			if (workday.status == 'Half Day'):
				target_hours = (single[0]["thour"])/2
			if (workday.status == 'On Leave'):
				target_hours = 0
			workday.target_hours = target_hours
			workday.total_target_seconds = target_hours*(60*60)

			if workday.target_hours == 0:
				workday.expected_break_hours = 0
				workday.total_break_seconds = 0
				workday.actual_working_hours = 0
			elif workday.target_hours < 6:
				wwh = frappe.db.get_list(doctype="Weekly Working Hours", filters={"employee": workday.employee}, fields=["name", "no_break_hours"])
				no_break_hours = True if len(wwh) > 0 and wwh[0]["no_break_hours"] == 1 else False
				if no_break_hours:
					workday.expected_break_hours = 0
					workday.total_break_seconds = 0

			# lenght of single must be greater than zero
			if((not single[0]["items"] is None) and (len(single[0]["items"]) > 0)):
				workday.first_checkin = c_single[0].time
				workday.last_checkout = c_single[-1].time
				
				for i in range(len(c_single)):
					row = workday.append("employee_checkins", {
						'employee_checkin': c_single[i]["name"],
						'log_type': c_single[i]["log_type"],
						'log_time': c_single[i]["time"],
						'skip_auto_attendance': c_single[i]["skip_auto_attendance"],
						'parent':workday
					})			
		else:
			doc_dict = {
				'doctype': 'Workday',
				'employee': data.employee,
				'log_date': get_datetime(date),
				'company': company,
				'attendance':"",
				'hours_worked':0,
				'break_hours':0,
				'expected_break_hours':0,
				'total_work_seconds':0,
				'total_break_seconds':0,
				'actual_working_hours':0,
				'target_hours': 0,
				'total_target_seconds': 0,
				'employee_checkins': []
			}
			workday = frappe.get_doc(doc_dict).insert()
			
		#workday.submit() 
		workday.save()
	

@frappe.whitelist()
def date_is_in_holiday_list(employee, date):
	holiday_list = frappe.db.get_value("Employee", employee, "holiday_list")
	hl_doc = frappe.get_doc("Holiday List", holiday_list)
	for holiday in hl_doc.holidays:
		if holiday.holiday_date == frappe.utils.get_datetime(date).date():
			return True

	return False


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
	'''get_umarked_days(employee,month,excludee_holidays=0, year)'''
	import calendar
	month_map = get_month_map()	
	today = get_datetime() #get year from year
	

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
	
	marked_days = [] 
	if cint(exclude_holidays):
		if get_version() == 14:
			from hrms.hr.utils import get_holiday_dates_for_employee

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


@frappe.whitelist()
def get_unmarked_range(employee, from_day, to_day):
	'''get_umarked_days(employee,month,excludee_holidays=0, year)'''
	import calendar
	month_map = get_month_map()	
	today = get_datetime() #get year from year	

	joining_date, relieving_date = frappe.get_cached_value("Employee", employee, ["date_of_joining", "relieving_date"])
	
	start_day = from_day
	end_day = to_day #calendar.monthrange(today.year, month_map[month])[1] + 1	

	if joining_date and joining_date >= getdate(from_day):
		start_day = joining_date
	if relieving_date and relieving_date >= getdate(to_day):
		end_day = relieving_date

	delta = date_diff(end_day, start_day)	
	days_of_list = ['{}'.format(add_days(start_day,i)) for i in range(delta + 1)]	
	month_start, month_end = days_of_list[0], days_of_list[-1]	

	""" ["docstatus", "!=", 2]"""
	rcords = frappe.get_list("Workday", fields=['log_date','employee'], filters=[
		["log_date",">=",month_start],
		["log_date","<=",month_end],
		["employee","=",employee]
	])
	
	marked_days = [get_datetime(rcord.log_date) for rcord in rcords] #[]
	unmarked_days = []

	for date in days_of_list:
		date_time = get_datetime(date)
		if today.day <= date_time.day and today.month <= date_time.month and today.year <= date_time.year:
			break
		if date_time not in marked_days:
			unmarked_days.append(date)

	return unmarked_days


def get_version():
	branch_name = get_app_branch("erpnext")
	if "14" in branch_name:
		return 14
	else: 
		return 13

def get_app_branch(app):
    """Returns branch of an app"""
    import subprocess

    try:
        branch = subprocess.check_output(
            "cd ../apps/{0} && git rev-parse --abbrev-ref HEAD".format(app), shell=True
        )
        branch = branch.decode("utf-8")
        branch = branch.strip()
        return branch
    except Exception:
        return ""
