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
		self.validate_duplicate_workday()
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

	def date_is_in_comp_off(self):
		leave_application_freizeit = frappe.db.exists(
		"Leave Application", {
			"employee": self.employee,
			"from_date": ("<=", self.log_date),
			"to_date": (">=", self.log_date),
			"leave_type": "Freizeitausgleich (Nicht buchen!)"
		}
		)
		leave_application_comp_off = frappe.db.exists(
		"Leave Application", {
			"employee": self.employee,
			"from_date": ("<=", self.log_date),
			"to_date": (">=", self.log_date),
			"leave_type": "Compensatory Off",
			'docstatus': 1
		}
		)
		if leave_application_comp_off or leave_application_freizeit:
			self.hours_worked = 0.0
			self.actual_working_hours = -self.target_hours
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
	joining_date, relieving_date = frappe.get_cached_value("Employee", employee, ["date_of_joining", "relieving_date"])
	
	start_day = from_day
	end_day = to_day

	if joining_date and joining_date >= getdate(from_day):
		start_day = joining_date
	if relieving_date and relieving_date >= getdate(to_day):
		end_day = relieving_date

	delta = date_diff(end_day, start_day)	
	days_of_list = ['{}'.format(add_days(start_day,i)) for i in range(delta + 1)]	
	month_start, month_end = days_of_list[0], days_of_list[-1]	

	rcords = frappe.get_list("Workday", fields=['log_date','employee'], filters=[
		["log_date",">=",month_start],
		["log_date","<=",month_end],
		["employee","=",employee]
	])
	
	marked_days = [get_datetime(rcord.log_date) for rcord in rcords]
	unmarked_days = []

	for date in days_of_list:
		date_time = get_datetime(date)
		if date_time not in marked_days:
			unmarked_days.append(date)

	return unmarked_days


@frappe.whitelist()
def get_created_workdays(employee, date_from, date_to):
	workday_list = frappe.get_list(
		"Workday",
		filters={
			"employee": employee,
			"log_date": ["between", [date_from, date_to]],
		},
		fields=["log_date","name"],
		order_by="log_date asc" 
	)
	
	formatted_workdays = []
	for workday in workday_list:
		date_obj = getdate(workday['log_date'])
		formatted_date = formatdate(date_obj, 'dd.MM.yyyy')
		formatted_workdays.append({
			'log_date': formatted_date,
			'name':workday['name']
		})
	
	return formatted_workdays


def get_employee_checkin(employee,atime):
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


def get_employee_default_work_hour(employee,adate):
    adate = getdate(adate)
    dayname = adate.strftime('%A')

    WeeklyWorkingHours = DocType("Weekly Working Hours")
    DailyHoursDetail = DocType("Daily Hours Detail")

    query = (
        frappe.qb.from_(WeeklyWorkingHours)
        .left_join(DailyHoursDetail)
        .on(WeeklyWorkingHours.name == DailyHoursDetail.parent)
        .select(
            WeeklyWorkingHours.name,
            WeeklyWorkingHours.employee,
            WeeklyWorkingHours.valid_from,
            WeeklyWorkingHours.valid_to,
			WeeklyWorkingHours.no_break_hours,
			WeeklyWorkingHours.set_target_hours_to_zero_when_date_is_holiday,
            DailyHoursDetail.day,
            DailyHoursDetail.hours,
            DailyHoursDetail.break_minutes
        )
        .where(
            (WeeklyWorkingHours.employee == employee)
            & (DailyHoursDetail.day == dayname)
            & (WeeklyWorkingHours.valid_from <= adate)
            & (WeeklyWorkingHours.valid_to >= adate)
            & (WeeklyWorkingHours.docstatus == 1)
        )
    )

    target_work_hours = query.run(as_dict=True)

    if not target_work_hours:
        frappe.throw(_('Please create Weekly Working Hours for the selected Employee:{0} first for date : {1}.').format(employee,adate))

    if len(target_work_hours) > 1:
        target_work_hours= "<br> ".join([frappe.get_desk_link("Weekly Working Hours", w.name) for w in target_work_hours])
        frappe.throw(_('There exist multiple Weekly Working Hours exist for the Date <b>{0}</b>: <br>{1} <br>').format(adate, target_work_hours))

    return target_work_hours[0]


@frappe.whitelist()
def get_actual_employee_log(aemployee, adate):
    employee_checkins = get_employee_checkin(aemployee,adate)
    employee_default_work_hour = get_employee_default_work_hour(aemployee,adate)
    is_date_in_holiday_list = date_is_in_holiday_list(aemployee,adate)
    no_break_hours = employee_default_work_hour.no_break_hours
    is_target_hours_zero_on_holiday = employee_default_work_hour.set_target_hours_to_zero_when_date_is_holiday
    is_holiday_with_zero_target_hours = is_target_hours_zero_on_holiday and is_date_in_holiday_list

    if employee_checkins and not is_holiday_with_zero_target_hours:
        new_workday = get_workday(employee_checkins, employee_default_work_hour, no_break_hours, is_target_hours_zero_on_holiday, is_date_in_holiday_list)
        return new_workday
    else:
        view_employee_attendance = get_employee_attendance(aemployee, adate)
        
        break_minutes = employee_default_work_hour.break_minutes
        expected_break_hours = flt(break_minutes / 60)
        
        if is_holiday_with_zero_target_hours:
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

    return new_workday


def get_workday(employee_checkins, employee_default_work_hour, no_break_hours, is_target_hours_zero_on_holiday, is_date_in_holiday_list=False):
    new_workday = {}

    hours_worked = 0.0
    break_hours = 0.0
    first_checkin = ""
    last_checkout = ""

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

        if clockin_list and clockout_list:
            first_checkin = clockin_list[0]
            last_checkout = clockout_list[-1] 

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
        "first_checkin": first_checkin,
        "last_checkout": last_checkout,
        "employee_checkins":employee_checkins,
    })

    return new_workday


def get_employee_attendance(employee,atime):
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
		try:
			employee_name = employee["name"]
			unmarked_days = get_unmarked_range(employee_name, a_week_ago.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d"))
			data = {
				"employee": employee_name,
				"unmarked_days": unmarked_days
			}
			flag = "Create workday"

			bulk_process_workdays_background(data, flag)
		except Exception as e:
			frappe.log_error(
				"Creating Workday, Got Error: {} while fetching unmarked days for: {}".format(str(e), employee_name),
				"Error during fetching unmarked days"
			)


def bulk_process_workdays_background(data,flag):
	'''bulk workday processing'''
	frappe.msgprint(_("Bulk operation is enqueued in background."), alert=True)
	frappe.enqueue(
		'hr_addon.hr_addon.doctype.workday.workday.bulk_process_workdays',
		queue='long',
		data=data,
		flag=flag
	)


@frappe.whitelist()
def bulk_process_workdays(data,flag):
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

	missing_dates = []

	for date in data.unmarked_days:
		try:
			if not frappe.db.exists('Workday', {'employee': data.employee,'log_date': get_datetime(date)}):
				workday = frappe.new_doc("Workday")
				workday.employee = data.employee
				workday.company = company
				workday.log_date = get_datetime(date)
				if flag == "Create workday":
					workday.save()

			missing_dates.append(get_datetime(date))

		except Exception:
			message = _("Something went wrong in Workday Creation: {0}".format(traceback.format_exc()))
			frappe.msgprint(message)
			frappe.log_error("bulk_process_workdays() error", message)

	formatted_missing_dates = []
	for missing_date in missing_dates:
		formatted_m_date = formatdate(missing_date,'dd.MM.yyyy')
		formatted_missing_dates.append(formatted_m_date)

	return {
		"message": 1,
		"missing_dates": formatted_missing_dates,
		"flag":flag
	}
