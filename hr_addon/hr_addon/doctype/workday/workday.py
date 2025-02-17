# Copyright (c) 2022, Jide Olayinka and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, datetime, get_datetime, getdate, add_days, formatdate, flt
from frappe.utils.data import date_diff, time_diff_in_hours
from frappe.query_builder import DocType
from pypika import Order
from pypika.functions import Date
from hrms.hr.utils import get_holiday_dates_for_employee
import traceback

class Workday(Document):
	def validate(self):
		self.set_actual_employee_log()
		self.date_is_in_comp_off()
		# self.validate_duplicate_workday()
		self.set_status_for_leave_application()

	def set_actual_employee_log(self):
		new_workday_dict = get_actual_employee_log(self.employee, self.log_date)
		self.employee_checkins = []

		self.hours_worked = new_workday_dict.get("hours_worked")
		self.break_hours = new_workday_dict.get("break_hours")
		self.target_hours = new_workday_dict.get("target_hours")
		self.expected_break_hours = new_workday_dict.get("expected_break_hours")
		self.manual_workday = new_workday_dict.get("manual_workday")
		self.actual_working_hours = new_workday_dict.get("actual_working_hours")
		self.first_checkin = new_workday_dict.get("first_checkin")
		self.last_checkout = new_workday_dict.get("last_checkout")
		self.attendance = new_workday_dict.get("attendance")

		employee_checkins = new_workday_dict.get("employee_checkins") or []

		for employee_checkin in employee_checkins:
			self.append("employee_checkins", {
				"employee_checkin": employee_checkin.get("name"),
				"log_type": employee_checkin.get("log_type"),
				"log_time": employee_checkin.get("time"),
				"skip_auto_attendance": employee_checkin.get("skip_auto_attendance"),
			})

	def set_status_for_leave_application(self):
		leave_application = frappe.db.exists(
		"Leave Application", {
			"employee": self.employee,
			"from_date": ("<=", self.log_date),
			"to_date": (">=", self.log_date),
			"leave_type": ['not in',["Freizeitausgleich (Nicht buchen!)","Compensatory Off"]],
			'docstatus': 1
		}
		)
		#'Compensatory Off'
		if leave_application :
			self.target_hours = 0
			self.expected_break_hours= 0
			self.actual_working_hours= 0
			self.status = "On Leave"

		if (self.status == 'Half Day'):
			self.target_hours = self.target_hours / 2
		elif (self.status == 'On Leave'):
			self.target_hours = 0

	# def date_is_in_comp_off(self):
	# 	leave_application_freizeit = frappe.db.exists(
	# 	"Leave Application", {
	# 		"employee": self.employee,
	# 		"from_date": ("<=", self.log_date),
	# 		"to_date": (">=", self.log_date),
	# 		"leave_type": "Freizeitausgleich (Nicht buchen!)"
	# 	}
	# 	)
	# 	leave_application_comp_off = frappe.db.exists(
	# 	"Leave Application", {
	# 		"employee": self.employee,
	# 		"from_date": ("<=", self.log_date),
	# 		"to_date": (">=", self.log_date),
	# 		"leave_type": "Compensatory Off",
	# 		'docstatus': 1
	# 	}
	# 	)
	# 	if leave_application_comp_off or leave_application_freizeit:
	# 		self.hours_worked = 0.0
	# 		self.actual_working_hours = -self.target_hours
			self.break_hours = 0.0
		
	def validate_duplicate_workday(self):
		workday = frappe.db.exists("Workday", {
			'employee': self.employee,
			'log_date': self.log_date
		})
	
		if workday and self.is_new():
			frappe.throw(
			_("Workday already exists for employee: {0}, on the given date: {1}")
			.format(self.employee, formatdate(self.log_date))
			)
	

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
		# considering today date
		# if today.day <= date_time.day and today.month <= date_time.month and today.year <= date_time.year:
		# 	break
		if date_time not in marked_days:
			unmarked_days.append(date)

	return unmarked_days


def get_employee_checkin(employee,atime):
    employee = employee
    atime = atime

    EmployeeCheckin = frappe.qb.DocType('Employee Checkin')
    checkin_list = (
        frappe.qb.from_(EmployeeCheckin)
        .select(
            EmployeeCheckin.name,
            EmployeeCheckin.log_type,
            EmployeeCheckin.time,
            EmployeeCheckin.skip_auto_attendance,
            EmployeeCheckin.attendance
        )
        .where(EmployeeCheckin.employee == employee)
        .where(Date(EmployeeCheckin.time) == getdate(atime))
        .orderby(EmployeeCheckin.time, order=Order.asc)
    ).run(as_dict=1)

    return checkin_list or []

def get_employee_default_work_hour(aemployee,adate):
    ''' weekly working hour'''
    employee = aemployee
    adate = adate    
    #validate current or active FY year WHERE --
    # AND YEAR(valid_from) = CAST(%(year)s as INT) AND YEAR(valid_to) = CAST(%(year)s as INT)
    # AND YEAR(w.valid_from) = CAST(('2022-01-01') as INT) AND YEAR(w.valid_to) = CAST(('2022-12-30') as INT);
    # Convert date to datetime object and get the day name
    adate = getdate(adate)
    dayname = adate.strftime('%A')  # Get the day name (e.g., 'Monday', 'Tuesday')

    # Define the doctypes
    WeeklyWorkingHours = DocType("Weekly Working Hours")
    DailyHoursDetail = DocType("Daily Hours Detail")

    # Build the query using Frappe's query builder
    query = (
        frappe.qb.from_(WeeklyWorkingHours)
        .left_join(DailyHoursDetail)
        .on(WeeklyWorkingHours.name == DailyHoursDetail.parent)
        .select(
            WeeklyWorkingHours.name,
            WeeklyWorkingHours.employee,
            WeeklyWorkingHours.valid_from,
            WeeklyWorkingHours.valid_to,
            DailyHoursDetail.day,
            DailyHoursDetail.hours,
            DailyHoursDetail.break_minutes
        )
        .where(
            (WeeklyWorkingHours.employee == aemployee)
            & (DailyHoursDetail.day == dayname)
            & (WeeklyWorkingHours.valid_from <= adate)
            & (WeeklyWorkingHours.valid_to >= adate)
            & (WeeklyWorkingHours.docstatus == 1)
        )
    )

    # Execute the query
    target_work_hours = query.run(as_dict=True)

    if not target_work_hours:
        frappe.throw(_('Please create Weekly Working Hours for the selected Employee:{0} first.').format(employee))

    if len(target_work_hours) > 1:
        target_work_hours= "<br> ".join([frappe.get_desk_link("Weekly Working Hours", w.name) for w in target_work_hours])
        frappe.throw(_('There exist multiple Weekly Working Hours exist for the Date <b>{0}</b>: <br>{1} <br>').format(adate, target_work_hours))

    return target_work_hours[0]


@frappe.whitelist()
def get_missing_workdays(employee, date_from, date_to):
    """
    Get the list of missing workdays for an employee between two dates using Frappe's query builder.
    """
    # Validate the date range
    date_from = getdate(date_from)
    date_to = getdate(date_to)

    # Calculate the number of days in the range
    total_days = date_diff(date_to, date_from) + 1

    missing_workdays = []

    # Define the doctypes
    WeeklyWorkingHours = DocType("Weekly Working Hours")
    DailyHoursDetail = DocType("Daily Hours Detail")

    # Loop through each day in the date range
    for i in range(total_days):
        current_date = add_days(date_from, i)

        # Build the query using Frappe query builder
        query = (
            frappe.qb.from_(WeeklyWorkingHours)
            .left_join(DailyHoursDetail)
            .on(WeeklyWorkingHours.name == DailyHoursDetail.parent)
            .select(
                WeeklyWorkingHours.name,
                WeeklyWorkingHours.employee,
                WeeklyWorkingHours.valid_from,
                WeeklyWorkingHours.valid_to,
                DailyHoursDetail.day,
                DailyHoursDetail.hours,
                DailyHoursDetail.break_minutes
            )
            .where(
                (WeeklyWorkingHours.employee == employee) &
                (WeeklyWorkingHours.valid_from <= current_date) &
                (WeeklyWorkingHours.valid_to >= current_date) &
                (WeeklyWorkingHours.docstatus == 1)
            )
        )

        # Execute the query
        target_work_hours = query.run(as_dict=True)

        # If no working hours are found for this date, add the date to missing workdays
        if not target_work_hours:
            missing_workdays.append(current_date)

    # Log missing workdays if any, and return the result
    if missing_workdays:
        missing_workdays_str = ', '.join([date.strftime('%Y-%m-%d') for date in missing_workdays])
        frappe.log_error(
            title="Missing Workdays During Bulk Workday Creation",
            message=f"Missing workdays for employee {employee}: {missing_workdays_str}"
        )
        return missing_workdays
    else:
        return 0



# @frappe.whitelist()
# def get_actual_employee_log(aemployee, adate):
#     '''total actual log'''
#     employee_checkins = get_employee_checkin(aemployee,adate)

#     # check empty or none
#     if not employee_checkins:
#         frappe.msgprint("No Checkin found for {0} on date {1}".format(frappe.get_desk_link("Employee", aemployee) ,adate))
#         return

#     employee_default_work_hour = get_employee_default_work_hour(aemployee,adate)
#     is_date_in_holiday_list = date_is_in_holiday_list(aemployee,adate)
#     fields=["name", "no_break_hours", "set_target_hours_to_zero_when_date_is_holiday"]
#     weekly_working_hours = frappe.db.get_list(doctype="Weekly Working Hours", filters={"employee": aemployee}, fields=fields)
#     no_break_hours = True if len(weekly_working_hours) > 0 and weekly_working_hours[0]["no_break_hours"] == 1 else False
#     is_target_hours_zero_on_holiday = len(weekly_working_hours) > 0 and weekly_working_hours[0]["set_target_hours_to_zero_when_date_is_holiday"] == 1
    
#     new_workday = get_workday(employee_checkins, employee_default_work_hour, no_break_hours, is_target_hours_zero_on_holiday, is_date_in_holiday_list)

#     return new_workday



@frappe.whitelist()
def get_actual_employee_log(aemployee, adate):
    employee_checkins = get_employee_checkin(aemployee,adate)

    # check empty or none
    if not employee_checkins:
        frappe.msgprint("No Checkin found for {0} on date {1}".format(frappe.get_desk_link("Employee", aemployee) ,adate))
	

    employee_default_work_hour = get_employee_default_work_hour(aemployee,adate)
    is_date_in_holiday_list = date_is_in_holiday_list(aemployee,adate)
    fields=["name", "no_break_hours", "set_target_hours_to_zero_when_date_is_holiday"]
    weekly_working_hours = frappe.db.get_list(doctype="Weekly Working Hours", filters={"employee": aemployee}, fields=fields)
    no_break_hours = True if len(weekly_working_hours) > 0 and weekly_working_hours[0]["no_break_hours"] == 1 else False
    is_target_hours_zero_on_holiday = len(weekly_working_hours) > 0 and weekly_working_hours[0]["set_target_hours_to_zero_when_date_is_holiday"] == 1

    if employee_checkins:
        no_break_hours = True if len(weekly_working_hours) > 0 and weekly_working_hours[0]["no_break_hours"] == 1 else False
        new_workday = get_workday(employee_checkins, employee_default_work_hour, no_break_hours, is_target_hours_zero_on_holiday, is_date_in_holiday_list)
        return new_workday
    else :
        view_employee_attendance = get_employee_attendance(aemployee, adate)
        
        break_minutes = employee_default_work_hour.break_minutes
        expected_break_hours = flt(break_minutes / 60)
        
        if is_target_hours_zero_on_holiday and is_date_in_holiday_list:
            new_workday = {
                "target_hours": 0,
                "break_minutes": employee_default_work_hour.break_minutes,
                "actual_working_hours": 0,
                "hours_worked": 0,
                "nbreak": 0,
                "attendance": view_employee_attendance[0].name if len(view_employee_attendance) > 0 else "",
                "break_hours": 0,
                "employee_checkins": [],
                "first_checkin": "",
                "last_checkout": "",
                "expected_break_hours": 0,
            }
        else:
            new_workday = {
                "target_hours": employee_default_work_hour.hours,
                "break_minutes": employee_default_work_hour.break_minutes,
                "actual_working_hours": -employee_default_work_hour.hours,
                "manual_workday": 1,
                "hours_worked": 0,
                "nbreak": 0,
                "attendance": view_employee_attendance[0].name if len(view_employee_attendance) > 0 else "",
                "break_hours": 0,
                "employee_checkins": [],
                "first_checkin": "",
                "last_checkout": "",
                "expected_break_hours": expected_break_hours,
            }



def get_workday(employee_checkins, employee_default_work_hour, no_break_hours, is_target_hours_zero_on_holiday, is_date_in_holiday_list=False):
    new_workday = {}

    hours_worked = 0.0
    break_hours = 0.0

    # not pair of IN/OUT either missing
    if len(employee_checkins)% 2 != 0:
        employee_checkin_message = ""
        for d in employee_checkins:
            employee_checkin_message += "<li>CheckIn Type:{0} for {1}</li>".format(d.log_type, frappe.get_desk_link("Employee Checkin", d.name))

        frappe.msgprint("CheckIns must be in pair for the given date:<ul>{}</ul>".format(employee_checkin_message))
        return new_workday

    if (len(employee_checkins) % 2 == 0):
        # seperate 'IN' from 'OUT'
        clockin_list = [get_datetime(kin.time) for x,kin in enumerate(employee_checkins) if x % 2 == 0]
        clockout_list = [get_datetime(kout.time) for x,kout in enumerate(employee_checkins) if x % 2 != 0]

        # get total worked hours
        for i in range(len(clockin_list)):
            wh = time_diff_in_hours(clockout_list[i],clockin_list[i])
            hours_worked += float(str(wh))
        
        # get total break hours
        for i in range(len(clockout_list)):
            if ((i+1) < len(clockout_list)):
                wh = time_diff_in_hours(clockin_list[i+1],clockout_list[i])
                break_hours += float(str(wh))

    break_minutes = employee_default_work_hour.break_minutes
    target_hours = employee_default_work_hour.hours

    expected_break_hours = flt(break_minutes / 60)
    break_hours = flt(break_hours)
    hours_worked = flt(hours_worked)
    actual_working_hours = hours_worked - expected_break_hours
    attendance = employee_checkins[0].attendance if len(employee_checkins) > 0 else ""

    if no_break_hours and hours_worked < 6: # TODO: set 6 as constant
        break_minutes = 0
        expected_break_hours = 0
        actual_working_hours = hours_worked

    if is_target_hours_zero_on_holiday and is_date_in_holiday_list:
        target_hours = 0

    hr_addon_settings = frappe.get_doc("HR Addon Settings")
    if hr_addon_settings.enable_default_break_hour_for_shorter_breaks:
        default_break_hours = flt(employee_default_work_hour.break_minutes/60)
        if break_hours <= default_break_hours:
            break_hours = flt(default_break_hours)

    # if target_hours == 0:
    #     expected_break_hours = 0

    new_workday.update({
        "target_hours": target_hours,
        "break_minutes": break_minutes,
        "hours_worked": hours_worked,
        "expected_break_hours": expected_break_hours,
        "actual_working_hours": actual_working_hours,
        "nbreak": 0,
        "attendance": attendance,        
        "break_hours": break_hours,
        "employee_checkins":employee_checkins,
    })

    return new_workday


@frappe.whitelist()
def get_actual_employee_log_for_bulk_process(aemployee, adate):

    employee_checkins = get_employee_checkin(aemployee, adate)
    #employee_default_work_hour = get_employee_default_work_hour(aemployee, adate)

    # Convert date to datetime object and get the day name
    adate = getdate(adate)
    dayname = adate.strftime('%A')  # Get the day name (e.g., 'Monday', 'Tuesday')

    # Define the doctypes
    WeeklyWorkingHours = DocType("Weekly Working Hours")
    DailyHoursDetail = DocType("Daily Hours Detail")

    # Build the query using Frappe's query builder
    query = (
        frappe.qb.from_(WeeklyWorkingHours)
        .left_join(DailyHoursDetail)
        .on(WeeklyWorkingHours.name == DailyHoursDetail.parent)
        .select(
            WeeklyWorkingHours.name,
            WeeklyWorkingHours.employee,
            WeeklyWorkingHours.valid_from,
            WeeklyWorkingHours.valid_to,
            DailyHoursDetail.day,
            DailyHoursDetail.hours,
            DailyHoursDetail.break_minutes
        )
        .where(
            (WeeklyWorkingHours.employee == aemployee)
            & (DailyHoursDetail.day == dayname)
            & (WeeklyWorkingHours.valid_from <= adate)
            & (WeeklyWorkingHours.valid_to >= adate)
            & (WeeklyWorkingHours.docstatus == 1)
        )
    )

    # Execute the query
    target_work_hours = query.run(as_dict=True)

    if len(target_work_hours) == 1:
        employee_default_work_hour = target_work_hours[0]

        if employee_checkins:
            is_date_in_holiday_list = date_is_in_holiday_list(aemployee, adate)
            fields=["name", "no_break_hours", "set_target_hours_to_zero_when_date_is_holiday"]
            weekly_working_hours = frappe.db.get_list(doctype="Weekly Working Hours", filters={"employee": aemployee}, fields=fields)
            no_break_hours = True if len(weekly_working_hours) > 0 and weekly_working_hours[0]["no_break_hours"] == 1 else False
            is_target_hours_zero_on_holiday = len(weekly_working_hours) > 0 and weekly_working_hours[0]["set_target_hours_to_zero_when_date_is_holiday"] == 1
            new_workday = get_workday(employee_checkins, employee_default_work_hour, no_break_hours, is_target_hours_zero_on_holiday, is_date_in_holiday_list)
        else:
            view_employee_attendance = get_employee_attendance(aemployee, adate)

            new_workday = {
            "target_hours": employee_default_work_hour.hours,
            "break_minutes": employee_default_work_hour.break_minutes,
            "hours_worked": 0,
            "nbreak": 0,
            "attendance": view_employee_attendance[0].name if len(view_employee_attendance) > 0 else "",
            "break_hours": 0,
            "employee_checkins":[],
            }

        return new_workday


def get_employee_attendance(employee,atime):
    ''' select DATE('date time');'''
    employee = employee
    atime = atime
    
    Attendance = frappe.qb.DocType('Attendance')
    attendance_list = (
        frappe.qb.from_(Attendance)
        .select(
            Attendance.name,
            Attendance.employee,
            Attendance.status,
            Attendance.attendance_date,
            Attendance.shift
        )
        .where(Attendance.employee == employee)
        .where(Date(Attendance.attendance_date) == getdate(atime))
        .where(Attendance.docstatus == 1)
        .orderby(Attendance.attendance_date, order=Order.asc)
    ).run(as_dict=True)

    return attendance_list


@frappe.whitelist()
def date_is_in_holiday_list(employee, date):
    holiday_list = frappe.get_cached_value("Employee", employee, "holiday_list")
    if not holiday_list:
        frappe.msgprint(_("Holiday list not set in {0}").format(employee))
        return False

    Holiday = frappe.qb.DocType('Holiday')
    holidays = (
        frappe.qb.from_(Holiday)
        .select(Holiday.holiday_date)
        .where(Holiday.parent == holiday_list)
        .where(Holiday.holiday_date == getdate(date))
    ).run()

    return len(holidays) > 0


def generate_workdays_scheduled_job():
	hr_addon_settings = frappe.get_doc("HR Addon Settings")
	if hr_addon_settings.enabled == 0:
		return
	day = hr_addon_settings.day
	time = hr_addon_settings.time
	number2name_dict= {
		0:"Monday",
		1:"Tuesday",
		2:"Wednesday",
		3:"Thursday",
		4:"Friday",
		5:"Saturday",
		6:"Sunday"
	}
	now = frappe.utils.datetime.datetime.now()
	today_weekday_number = now.weekday()
	weekday_name = number2name_dict[today_weekday_number]
	if weekday_name == day:
		if now.hour == int(time):
			generate_workdays_for_past_7_days_now()


@frappe.whitelist()
def generate_workdays_for_past_7_days_now():
	today = frappe.utils.datetime.datetime.now()
	a_week_ago = today - frappe.utils.datetime.timedelta(days=7)
	employees = frappe.db.get_list("Employee", filters={"status": "Active"})
	for employee in employees:
		employee_name = employee["name"]
		unmarked_days = get_unmarked_range(employee_name, a_week_ago.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d"))
		data = {
			"employee": employee_name,
			"unmarked_days": unmarked_days
		}
		bulk_process_workdays_background(data)


def bulk_process_workdays_background(data):
	'''bulk workday processing'''
	frappe.msgprint(_("Bulk operation is enqueued in background."), alert=True)
	frappe.enqueue(
		'hr_addon.hr_addon.doctype.workday.workday.bulk_process_workdays',
		queue='long',
		data=data
	)


@frappe.whitelist()
def bulk_process_workdays(data):
	import json
	if isinstance(data, str):
		data = json.loads(data)
	data = frappe._dict(data)

	if data.employee and frappe.get_value('Employee', data.employee, 'status') != "Active":
		frappe.throw(_("{0} is not active").format(frappe.get_desk_link('Employee', data.employee)))

	company = frappe.get_value('Employee', data.employee, 'company')
	if not data.unmarked_days:
		frappe.throw(_("Please select a date"))
		return

	for date in data.unmarked_days:
		try:
			if not frappe.db.exists('Workday', {'employee': data.employee,'log_date': get_datetime(date)}):
				workday = frappe.new_doc("Workday")
				workday.employee = data.employee
				workday.company = company
				workday.log_date = get_datetime(date)
				workday.save()

		except Exception:
			message = _("Something went wrong in Workday Creation: {0}".format(traceback.format_exc()))
			frappe.msgprint(message)
			frappe.log_error("bulk_process_workdays() error", message)