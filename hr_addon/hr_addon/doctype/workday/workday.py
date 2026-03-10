# Copyright (c) 2022, phamos.eu and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, get_datetime, getdate, add_days, formatdate, flt
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

	def after_insert(self):
		"""Show a concise message after creating a Workday, indicating its status."""
		if self.status == "Missing Checkin":
			frappe.msgprint(
				_("Workday created for Employee {0} on {1} with status: {2}").format(
					self.employee,
					formatdate(self.log_date),
					self.status or _("Not Set"),
				),
				alert=True,
			)

	def set_actual_employee_log(self):
		new_workday_dict = get_actual_employee_log(self.employee, self.log_date)
		if new_workday_dict is None:
			frappe.throw(_("Cannot create workday for employee {0} on date {1}. Weekly Working Hours not configured. Please configure Weekly Working Hours.").format(
            self.employee, 
            frappe.format(self.log_date, {"fieldtype": "Date"})
        ))
			
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
		self.status = new_workday_dict.get("status")

		employee_checkins = new_workday_dict.get("employee_checkins") or []

		for employee_checkin in employee_checkins:
			self.append("employee_checkins", {
				"employee_checkin": employee_checkin.get("name"),
				"log_type": employee_checkin.get("log_type"),
				"log_time": employee_checkin.get("time"),
				"skip_auto_attendance": employee_checkin.get("skip_auto_attendance"),
			})

	def set_status_for_leave_application(self):
		filters = {
			"employee": self.employee,
			"from_date": ("<=", self.log_date),
			"to_date": (">=", self.log_date),
			"docstatus": 1
		}
		leave_types = frappe.get_all("Leave Type", filters={"is_compensatory": 1}, pluck="name")
		if leave_types:
			filters["leave_type"] = ['not in', leave_types]

		leave_application = frappe.db.exists("Leave Application", filters)
		if leave_application:
			half_day, half_day_date = frappe.db.get_value("Leave Application", leave_application, ["half_day", "half_day_date"])
			
			# Apply half-day logic only if this specific date is the half day
			# For single-day leaves, half_day_date is None
			is_half_day_for_this_date = half_day and (not half_day_date or getdate(half_day_date) == getdate(self.log_date))
			
			if is_half_day_for_this_date:
				self.target_hours = self.target_hours / 2
				self.expected_break_hours = self.expected_break_hours / 2
				if self.hours_worked == 0:
					self.actual_working_hours = -self.target_hours
				self.status = "Half Day"
			else:
				self.target_hours = 0
				self.expected_break_hours = 0
				self.actual_working_hours = 0
				self.status = "On Leave"

	def date_is_in_comp_off(self):
		leave_types = frappe.get_all("Leave Type", filters={"is_compensatory": 1}, pluck="name")
		if not leave_types:
			return

		leave_application = frappe.db.exists(
			"Leave Application", {
				"employee": self.employee,
				"from_date": ("<=", self.log_date),
				"to_date": (">=", self.log_date),
				"leave_type": ["in", leave_types],
				"docstatus": 1
			}
		)

		if leave_application:
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
			_("{0} already exists for employee: {1}, on the given date: {2}")
			.format(frappe.get_desk_link("Workday", workday),self.employee, formatdate(self.log_date))
			)
	
	def on_trash(self):
		logs = frappe.db.get_list("Workday Creation Log", filters={"workday": self.name}, pluck="name")
		if logs:
			log_list = "<br>".join(logs)
			for log in logs:
				frappe.delete_doc("Workday Creation Log", log, force=1)

			frappe.msgprint(_("{0} Workday Creation Log(s) deleted successfully : <br><br>{1}").format(len(logs),log_list),
				   alert=True,
				   indicator="green",
				   title=_("Logs Deleted")
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


def _cap_date_range_by_employee_dates(joining_date, relieving_date, from_day, to_day):
	"""
	Cap the date range by employee's joining and relieving dates.
	
	Args:
		joining_date: Employee's date of joining (or None)
		relieving_date: Employee's relieving date (or None)
		from_day: Start date of the range
		to_day: End date of the range
		
	Returns:
		tuple: (start_day, end_day) - the capped date range
	"""
	start_day = from_day
	end_day = to_day
	
	if joining_date and joining_date >= getdate(from_day):
		start_day = joining_date
	# If employee has a relieving date earlier than the selected "to" date,
	# cap the range at the relieving date; otherwise do not extend beyond "to_day".
	if relieving_date and relieving_date <= getdate(to_day):
		end_day = relieving_date
	
	return start_day, end_day


@frappe.whitelist()
def get_unmarked_range(employee, from_day, to_day):
	import json
	
	# Handle both single employee (string) and multiple employees (list/JSON string)
	if isinstance(employee, str):
		try:
			employee_list = json.loads(employee)
		except (json.JSONDecodeError, ValueError):
			# If it's not valid JSON, treat it as a single employee
			employee_list = [employee]
	else:
		employee_list = employee if isinstance(employee, list) else [employee]
	# If only one employee, use the old logic for backward compatibility
	if len(employee_list) == 1:
		single_employee = employee_list[0]
		# weekly hours check
		work_hours = get_employee_default_work_hour(
			single_employee,
			from_day,
			skip_workday_if_no_weekly_hours=1
			)
		if work_hours is None:
			return []
		joining_date, relieving_date = frappe.get_cached_value("Employee", single_employee, ["date_of_joining", "relieving_date"])
		
		start_day, end_day = _cap_date_range_by_employee_dates(joining_date, relieving_date, from_day, to_day)

		delta = date_diff(end_day, start_day)	
		days_of_list = ['{}'.format(add_days(start_day,i)) for i in range(delta + 1)]	
		month_start, month_end = days_of_list[0], days_of_list[-1]	

		rcords = frappe.get_list("Workday", fields=['log_date','employee'], filters=[
			["log_date",">=",month_start],
			["log_date","<=",month_end],
			["employee","=",single_employee]
		])
		
		marked_days = [get_datetime(rcord.log_date) for rcord in rcords]
		unmarked_days = []

		for date in days_of_list:
			date_time = get_datetime(date)
			if date_time not in marked_days:
				unmarked_days.append(date)

		return unmarked_days
	
	# For multiple employees, aggregate unmarked days
	all_unmarked_days = set()
	
	for emp in employee_list:
		joining_date, relieving_date = frappe.get_cached_value("Employee", emp, ["date_of_joining", "relieving_date"])

		work_hours = get_employee_default_work_hour(
			emp,
			from_day,
			skip_workday_if_no_weekly_hours=1
		)
		if work_hours is None:
			continue
		
		start_day, end_day = _cap_date_range_by_employee_dates(joining_date, relieving_date, from_day, to_day)

		delta = date_diff(end_day, start_day)	
		days_of_list = ['{}'.format(add_days(start_day,i)) for i in range(delta + 1)]	
		month_start, month_end = days_of_list[0], days_of_list[-1]	

		rcords = frappe.get_list("Workday", fields=['log_date','employee'], filters=[
			["log_date",">=",month_start],
			["log_date","<=",month_end],
			["employee","=",emp]
		])
		
		marked_days = [get_datetime(rcord.log_date) for rcord in rcords]

		for date in days_of_list:
			date_time = get_datetime(date)
			if date_time not in marked_days:
				all_unmarked_days.add(date)
	
	return sorted(list(all_unmarked_days))



@frappe.whitelist()
def get_created_workdays(employees, date_from, date_to):
	import json
	
	# Handle both single employee (string) and multiple employees (list/JSON string)
	if isinstance(employees, str):
		try:
			employee_list = json.loads(employees)
		except (json.JSONDecodeError, ValueError):
			# If it's not valid JSON, treat it as a single employee
			employee_list = [employees]
	else:
		employee_list = employees if isinstance(employees, list) else [employees]
	
	# Build filters for multiple employees
	workday_list = frappe.get_list(
		"Workday",
		filters={
			"employee": ["in", employee_list],
			"log_date": ["between", [date_from, date_to]],
		},
		fields=["log_date", "name", "employee"],
		order_by="log_date asc" 
	)
	
	formatted_workdays = []
	for workday in workday_list:
		date_obj = getdate(workday['log_date'])
		formatted_date = formatdate(date_obj, 'dd.MM.yyyy')
		formatted_workdays.append({
			'log_date': formatted_date,
			'name': workday['name'],
			'employee': workday['employee']
		})
	
	return formatted_workdays


def get_employee_checkin(employee,atime):
    EmployeeCheckin = frappe.qb.DocType('Employee Checkin')
    
    # Convert atime to date for consistent comparison
    target_date = getdate(atime)
    
    # Log for debugging
    frappe.logger().debug(f"get_employee_checkin: employee={employee}, target_date={target_date}")
    
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
        .where(Date(EmployeeCheckin.time) == target_date)
        .orderby(EmployeeCheckin.time, order=Order.asc)
    ).run(as_dict=1)
    
    # Log results for debugging
    frappe.logger().debug(f"get_employee_checkin: found {len(checkin_list)} checkins for {employee} on {target_date}")
    if checkin_list:
        frappe.logger().debug(f"get_employee_checkin: checkins={[c.get('name') for c in checkin_list]}")

    return checkin_list or []


def get_employee_default_work_hour(employee, adate, skip_workday_if_no_weekly_hours=None):
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

	# If parameter not passed, fetch from settings (for scheduler)
    if skip_workday_if_no_weekly_hours is None:
       skip_workday_if_no_weekly_hours = frappe.db.get_single_value(
            'HR Addon Settings', 
            'skip_workday_if_no_weekly_hours'
       ) or 0

    if not target_work_hours:
        if skip_workday_if_no_weekly_hours:
           return None  # Skip enabled - return None gracefully
        else:
            frappe.throw(_('Please create Weekly Working Hours for the selected Employee:{0} first for date : {1}.').format(employee,adate))

    if len(target_work_hours) > 1:
        target_work_hours= "<br> ".join([frappe.get_desk_link("Weekly Working Hours", w.name) for w in target_work_hours])
        frappe.throw(_('There exist multiple Weekly Working Hours exist for the Date <b>{0}</b>: <br>{1} <br>').format(adate, target_work_hours))

    return target_work_hours[0]


@frappe.whitelist()
def get_actual_employee_log(aemployee, adate, skip_workday_if_no_weekly_hours=None):
    employee_checkins = get_employee_checkin(aemployee,adate)
    employee_default_work_hour = get_employee_default_work_hour(aemployee,adate,skip_workday_if_no_weekly_hours)
    # If None, employee has no weekly hours and skip is enabled
    if employee_default_work_hour is None:
       return None
    is_date_in_holiday_list = date_is_in_holiday_list(aemployee,adate)
    no_break_hours = employee_default_work_hour.no_break_hours
    is_target_hours_zero_on_holiday = employee_default_work_hour.set_target_hours_to_zero_when_date_is_holiday
    is_holiday_with_zero_target_hours = is_target_hours_zero_on_holiday and is_date_in_holiday_list

    if employee_checkins and not is_holiday_with_zero_target_hours:
        new_workday = get_workday(employee_checkins, employee_default_work_hour, no_break_hours)
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
				"status": view_employee_attendance[0].status if len(view_employee_attendance) > 0 else "",
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
                "actual_working_hours": 0,
                "manual_workday": 1,
                "hours_worked": 0,
                "nbreak": 0,
                "attendance": view_employee_attendance[0].name if len(view_employee_attendance) > 0 else "",
				"status": view_employee_attendance[0].status if len(view_employee_attendance) > 0 else "",
                "break_hours": 0,
                "employee_checkins": [],
                "first_checkin": "",
                "last_checkout": "",
                "expected_break_hours": expected_break_hours,
            }

    return new_workday


@frappe.whitelist()
def set_attendance_in_employee_checkins(employee_checkins, attendance):
	if isinstance(employee_checkins, str):
		import json
		employee_checkins = json.loads(employee_checkins)
	if not employee_checkins:
		return

	checkin_updated = False
	for checkin in employee_checkins:
		checkin
		if checkin.get("employee_checkin") is None:
			continue
		checkin_doc = frappe.get_doc("Employee Checkin", checkin.get("employee_checkin"))
		if checkin_doc.attendance == attendance:
			continue
		checkin_doc.attendance = attendance
		checkin_doc.save()
		checkin_updated = True

	return checkin_updated

@frappe.whitelist()
def calculate_actual_working_hours(hours_worked, break_hours, default_break_hours, mechanism=None, total_duration=None, is_swapped=None, no_break_hours=False, hours_worked_threshold=6):
	"""
	Calculate actual_working_hours based on HR Addon Settings mechanism.
	Can be called directly from web forms or other whitelisted contexts.
	
	Args:
		hours_worked: Sum of work periods (excluding breaks)
		break_hours: Calculated break hours
		default_break_hours: Default break hours from Weekly Working Hours
		mechanism: Break calculation mechanism from HR Addon Settings (optional, will fetch if not provided)
		total_duration: Total time from first checkin to last checkout (optional, for Workday)
		is_swapped: Whether hours_worked and total_duration are swapped (optional, will fetch if not provided)
		no_break_hours: Whether no break hours setting is enabled
		hours_worked_threshold: Threshold for no_break_hours check (default 6)
	
	Returns:
		actual_working_hours: Calculated actual working hours
	"""
	hours_worked = flt(hours_worked)
	break_hours = flt(break_hours)
	default_break_hours = flt(default_break_hours)
	
	# Fetch HR Addon Settings if mechanism or is_swapped not provided
	if mechanism is None or is_swapped is None:
		hr_addon_settings = frappe.get_cached_doc("HR Addon Settings")
		if mechanism is None:
			mechanism = hr_addon_settings.workday_break_calculation_mechanism
		if is_swapped is None:
			is_swapped = mechanism == "Break Hours from Employee Checkins" and hr_addon_settings.swap_hours_worked_and_actual_working_hours
	
	# Special case: no break hours when hours worked is less than threshold
	if no_break_hours and hours_worked < hours_worked_threshold and not is_swapped:
		return hours_worked
	
	# Calculate based on mechanism
	if mechanism == "Break Hours from Weekly Working Hours if Shorter breaks":
		# For this mechanism: use total_duration (total presence on site) minus break_hours
		if total_duration is not None and total_duration > 0:
			return flt(total_duration - break_hours)
		else:
			# Fallback: use hours_worked - break_hours if total_duration not available
			return flt(hours_worked - break_hours)
	
	elif is_swapped:
		# When swap is enabled: hours_worked contains total_duration
		if total_duration is not None and total_duration > 0:
			return flt(total_duration - break_hours)
		elif hours_worked > 0:
			return flt(hours_worked - break_hours)
		else:
			return flt(total_duration - default_break_hours) if total_duration is not None else flt(hours_worked - default_break_hours)
	
	else:
		# Default: hours_worked contains sum of work periods (excluding breaks)
		if total_duration is not None and total_duration > 0:
			return flt(hours_worked - break_hours)
		else:
			return flt(hours_worked - default_break_hours)

def get_workday(employee_checkins, employee_default_work_hour, no_break_hours):
    hr_addon_settings = frappe.get_cached_doc("HR Addon Settings")
    is_break_from_checkins_with_swapped_hours = hr_addon_settings.workday_break_calculation_mechanism == "Break Hours from Employee Checkins" and hr_addon_settings.swap_hours_worked_and_actual_working_hours
    new_workday = {}

    hours_worked = 0.0
    total_duration = 0
    first_checkin = ""
    last_checkout = ""

    default_break_minutes = employee_default_work_hour.break_minutes
    default_break_hours = flt(default_break_minutes / 60)
    target_hours = employee_default_work_hour.hours

    if len(employee_checkins) % 2 == 0:
        # Even number of checkins – normal calculation flow
        # seperate 'IN' from 'OUT'
        clockin_list = [get_datetime(kin.time) for x, kin in enumerate(employee_checkins) if x % 2 == 0]
        clockout_list = [get_datetime(kout.time) for x, kout in enumerate(employee_checkins) if x % 2 != 0]

        # get total worked hours
        for i in range(len(clockin_list)):
            wh = time_diff_in_hours(clockout_list[i], clockin_list[i])
            hours_worked += float(str(wh))

        # Calculate difference between first check-in and last checkout
        if clockin_list and clockout_list:
            first_checkin = clockin_list[0]
            last_checkout = clockout_list[-1]  # Last element of clockout_list
            total_duration = time_diff_in_hours(last_checkout, first_checkin)

        if is_break_from_checkins_with_swapped_hours:
            total_duration, hours_worked = hours_worked, total_duration

        break_from_checkins = 0.0
        for i in range(len(clockout_list) - 1):
            wh = time_diff_in_hours(clockin_list[i + 1], clockout_list[i])
            break_from_checkins += float(wh)

        if hr_addon_settings.workday_break_calculation_mechanism == "Break Hours from Employee Checkins":
            break_hours = break_from_checkins

        elif hr_addon_settings.workday_break_calculation_mechanism == "Break Hours from Weekly Working Hours":
            break_hours = default_break_hours

        elif hr_addon_settings.workday_break_calculation_mechanism == "Break Hours from Weekly Working Hours if Shorter breaks":
            if break_from_checkins <= default_break_hours:
                break_hours = default_break_hours
            else:
                break_hours = break_from_checkins
        else:
            break_hours = 0.0

    else:
        # Odd number of checkins – create Workday with status "Missing Checkin"
        attendance = employee_checkins[0].attendance if len(employee_checkins) > 0 else ""

        if employee_checkins:
            first_checkin = get_datetime(employee_checkins[0].time)
            last_checkout = get_datetime(employee_checkins[-1].time)

        hours_worked = 0.0
        break_hours = 0.0
        actual_working_hours = 0.0

        new_workday.update({
            "target_hours": target_hours,
            "break_minutes": default_break_minutes,
            "hours_worked": hours_worked,
            "expected_break_hours": default_break_hours,
            "actual_working_hours": actual_working_hours,
            "nbreak": 0,
            "attendance": attendance,
            "status": "Missing Checkin",
            "break_hours": break_hours,
            "first_checkin": first_checkin,
            "last_checkout": last_checkout,
            "employee_checkins": employee_checkins,
        })

        return new_workday

    hours_worked = flt(hours_worked)

    # Calculate actual_working_hours using shared function
    actual_working_hours = calculate_actual_working_hours(
        hours_worked=hours_worked,
        break_hours=break_hours,
        default_break_hours=default_break_hours,
        mechanism=hr_addon_settings.workday_break_calculation_mechanism,
        total_duration=total_duration,
        is_swapped=is_break_from_checkins_with_swapped_hours,
        no_break_hours=no_break_hours,
        hours_worked_threshold=6
    )
    
    attendance = employee_checkins[0].attendance if len(employee_checkins) > 0 else ""
    status = frappe.db.get_value("Attendance", attendance, "status") if attendance else ""

    new_workday.update({
        "target_hours": target_hours,
        "break_minutes": default_break_minutes,
        "hours_worked": hours_worked,
        "expected_break_hours": default_break_hours,
        "actual_working_hours": actual_working_hours,
        "nbreak": 0,
        "attendance": attendance,
        "status": status,
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
    allow_workdays_on_holidays = frappe.db.get_single_value("HR Addon Settings", "allow_workdays_on_holidays")
    if allow_workdays_on_holidays:
        checkins = get_employee_checkin(employee, date)
        if not checkins:
            return False  # Do not create workday if no check-in data
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


def create_background_job_for_workday_generation(hr_addon_settings):
	from frappe.core.doctype.scheduled_job_type.scheduled_job_type import insert_single_event	
	if hr_addon_settings.enabled == 0:
		return

	time = hr_addon_settings.time
	background_job_frequency = hr_addon_settings.background_job_frequency
	
	name2number_dict = {
		"Sunday": 0,
		"Monday": 1,
		"Tuesday": 2,
		"Wednesday": 3,
		"Thursday": 4,
		"Friday": 5,
		"Saturday": 6
	}
	
	if background_job_frequency == "Daily":
		cron_string = "0 {0} * * *".format(time)
		frequency = "Cron"
	elif background_job_frequency == "Weekly":
		day_number = name2number_dict.get(hr_addon_settings.day)
		cron_string = "0 {0} * * {1}".format(time, day_number)
		frequency = "Cron"
	else:
		cron_string = "0 {0} * * *".format(time)
		frequency = "Cron"
	
	# This is creating Schedule Job Type which is already a cronjob
	insert_single_event(
		frequency=frequency,
		event="hr_addon.hr_addon.doctype.workday.workday.generate_workdays_scheduled_job",
		cron_format=cron_string
	)


def create_background_job_for_workday_generation_after_install():
	"""Called once after app installation to create the scheduled job"""
	hr_addon_settings = frappe.get_doc("HR Addon Settings")
	create_background_job_for_workday_generation(hr_addon_settings)

def generate_workdays_scheduled_job():
	hr_addon_settings = frappe.get_doc("HR Addon Settings")
	if hr_addon_settings.enabled == 0:
		return
	generate_workdays_for_past_7_days_now()


@frappe.whitelist()
def generate_workdays_for_past_7_days_now():
	import time
	start_time = time.time()
	# Fetch setting value
	hr_addon_settings = frappe.get_doc("HR Addon Settings")
	skip_if_no_weekly_hours = getattr(hr_addon_settings, 'skip_workday_if_no_weekly_hours', 0) or 0
	
	# Create log document
	log_doc = frappe.get_doc({
		"doctype": "Workday Generation Log",
		"execution_time": frappe.utils.now_datetime(),
		"execution_type": "Scheduled Job" if frappe.flags.in_scheduler else "Manual Button",
		"status": "Running"
	})
	log_doc.insert(ignore_permissions=True)
	frappe.db.commit()
	
	try:
		today = frappe.utils.datetime.datetime.now()
		a_week_ago = today - frappe.utils.datetime.timedelta(days=7)
		
		# Uncomment below line to test error handling in Workday Generation Log
		# raise Exception("Test error: Simulating critical failure in workday generation")
		
		employees = frappe.db.get_list("Employee", filters={"status": "Active"})
		
		total_employees = 0
		total_workdays_created = 0
		total_workdays_failed = 0
		total_dates = 0
		errors = []
		
		for employee in employees:
			try:
				employee_name = employee["name"]
				
				# Uncomment below line to test per-employee error handling
				# if employee_name == "HR-EMP-00001": raise Exception("Test error: Simulating employee-specific failure")
				
				unmarked_days = get_unmarked_range(employee_name, a_week_ago.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d"))
				
				if not unmarked_days: 
					continue  # No unmarked days, skip to next employee 

				if skip_if_no_weekly_hours:
					# Filter unmarked days to only those with valid weekly working hours 
					valid_unmarked_days = []
					for date in unmarked_days:
						if has_valid_weekly_working_hours(employee_name, date):
							valid_unmarked_days.append(date)
				
					if not valid_unmarked_days:
						continue  # No valid dates, skip
				else:
					valid_unmarked_days = unmarked_days 	

				total_employees += 1
				total_dates += len(valid_unmarked_days)
				
				# Count checkins and categorize absence reasons for this employee
				checkins_found = 0
				dates_with_no_checkins = 0
				dates_with_incomplete_checkins = 0
				dates_on_leave = 0
				dates_on_holiday = 0
				
				for date in valid_unmarked_days:
					checkins = get_employee_checkin(employee_name, date)
					checkin_count = len(checkins)
					checkins_found += checkin_count
					
					# Categorize absence reason
					if checkin_count == 0:
						# Check if on leave
						leave_filters = {
							"employee": employee_name,
							"from_date": ("<=", date),
							"to_date": (">=", date),
							"docstatus": 1
						}
						leave_types = frappe.get_all("Leave Type", filters={"is_compensatory": 1}, pluck="name")
						if leave_types:
							leave_filters["leave_type"] = ['not in', leave_types]
						
						if frappe.db.exists("Leave Application", leave_filters):
							dates_on_leave += 1
						# Check if holiday
						elif date_is_in_holiday_list(employee_name, date):
							dates_on_holiday += 1
						else:
							dates_with_no_checkins += 1
					elif checkin_count % 2 != 0:
						# Odd number of checkins = incomplete
						dates_with_incomplete_checkins += 1
				
				# Add employee log detail
				log_doc.append("employee_logs", {
					"employee": employee_name,
					"status": "Success",
					"unmarked_days": len(valid_unmarked_days),
					"checkins_found": checkins_found,
					"dates_with_no_checkins": dates_with_no_checkins,
					"dates_with_incomplete_checkins": dates_with_incomplete_checkins,
					"dates_on_leave": dates_on_leave,
					"dates_on_holiday": dates_on_holiday,
					"workdays_created": 0,  # Will be updated later
					"workdays_failed": 0
				})

				data = {
					"employee": employee_name,
					"unmarked_days": valid_unmarked_days,
					"log_name": log_doc.name,  # Pass log name to background job
					"skip_workday_if_no_weekly_hours": skip_if_no_weekly_hours
				}
				flag = "Create workday"

				bulk_process_workdays_background(data, flag)
				total_workdays_created += len(valid_unmarked_days)
				
			except Exception as e:
				total_workdays_failed += 1
				error_msg = "Creating Workday, Got Error: {} while fetching unmarked days for: {}".format(str(e), employee_name)
				errors.append(error_msg)
				frappe.log_error(error_msg, "Error during fetching unmarked days")
				
				# Add failed employee log
				log_doc.append("employee_logs", {
					"employee": employee_name,
					"status": "Failed",
					"error_message": str(e)
				})
		
		# Update log document with final results
		end_time = time.time()
		duration = end_time - start_time
		
		log_doc.total_employees = total_employees
		log_doc.total_dates_processed = total_dates
		log_doc.workdays_created = total_workdays_created
		log_doc.workdays_failed = total_workdays_failed
		log_doc.duration = duration
		log_doc.status = "Failed" if total_workdays_failed == total_employees else ("Partially Failed" if total_workdays_failed > 0 else "Completed")
		
		if errors:
			log_doc.error_log = "\n\n".join(errors)
		
		log_doc.save(ignore_permissions=True)
		frappe.db.commit()
		
		frappe.logger().info(f"Workday generation completed. Log: {log_doc.name}, Duration: {duration:.2f}s")
		
	except Exception as e:
		# Catch any unexpected errors in the main function
		end_time = time.time()
		duration = end_time - start_time
		
		error_msg = "Critical Error in generate_workdays_for_past_7_days_now: {}".format(str(e))
		frappe.log_error(traceback.format_exc(), "Critical Error in Workday Generation")
		
		log_doc.status = "Failed"
		log_doc.duration = duration
		log_doc.error_log = "{}\n\n{}".format(error_msg, traceback.format_exc())
		log_doc.save(ignore_permissions=True)
		frappe.db.commit()
		
		frappe.logger().error(f"Workday generation failed critically. Log: {log_doc.name}, Error: {error_msg}")

def has_valid_weekly_working_hours(employee, date):
	date = frappe.utils.getdate(date)
	dayname = date.strftime('%A')

	weekly_hours = frappe.db.get_all(
		"Weekly Working Hours",
		filters={
			"employee": employee,
			"docstatus": 1,
			"valid_from": ["<=", date],
			"valid_to": [">=", date],
		},
		fields=["name"]
	)

	if not weekly_hours:
		return False

	parent_names = [wh.name for wh in weekly_hours]

	daily_hours = frappe.db.exists(
		"Daily Hours Detail",
		{
			"parent": ["in", parent_names],
			"day": dayname
		}
	)

	return True if daily_hours else False 			


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

	# Handle both single employee and multiple employees
	if isinstance(data.employee, str):
		try:
			employee_list = json.loads(data.employee)
		except (json.JSONDecodeError, ValueError):
			# If it's not valid JSON, treat it as a single employee
			employee_list = [data.employee]
	else:
		employee_list = data.employee if isinstance(data.employee, list) else [data.employee]
	
	# Validate all employees are active
	for emp in employee_list:
		if frappe.get_value('Employee', emp, 'status') != "Active":
			frappe.throw(_("{0} is not active").format(frappe.get_desk_link('Employee', emp)))

	# If unmarked_days is not provided, generate it from date range
	if not data.unmarked_days:
		if not data.get('date_from') or not data.get('date_to'):
			frappe.throw(_("Please select a date range"))
			return
		
		# Generate unmarked days for the selected employees and date range
		all_unmarked_days = set()
		for emp in employee_list:
			unmarked_for_emp = get_unmarked_range(emp, data.date_from, data.date_to)
			all_unmarked_days.update(unmarked_for_emp)
		
		data.unmarked_days = sorted(list(all_unmarked_days))
		
		if not data.unmarked_days:
			frappe.throw(_("No unmarked days found for the selected date range"))
			return

	all_missing_dates = set()
	skipped_by_employee = {}
	created_by_employee = {}
	existing_workdays = {}

	# Process workdays for each employee
	for emp in employee_list:
		company = frappe.get_value('Employee', emp, 'company')
		
		for date in data.unmarked_days:
			creation_log = None
			try:
				# Create creation log for this workday
				creation_log = frappe.get_doc({
					"doctype": "Workday Creation Log",
					"employee": emp,
					"log_date": get_datetime(date),
					"creation_time": frappe.utils.now_datetime(),
					"status": "Success"
				})
				
				# Get checkins for logging
				employee_checkins = get_employee_checkin(emp, date)
				creation_log.checkins_found = len(employee_checkins)
				
				# Uncomment below line to test error handling in Workday Creation Log
				# raise Exception("Test error: Simulating workday creation failure")
				
				# Capture first and last checkin times based on log type
				if employee_checkins:
					# Find first IN checkin
					first_in = next((c for c in employee_checkins if c.get("log_type") == "IN"), None)
					if first_in:
						creation_log.first_checkin = first_in.get("time")
					elif employee_checkins:
						# Fallback: if no IN found, use the first checkin of any type
						creation_log.first_checkin = employee_checkins[0].get("time")
					
					# Find last OUT checkin
					last_out = next((c for c in reversed(employee_checkins) if c.get("log_type") == "OUT"), None)
					if last_out:
						creation_log.last_checkout = last_out.get("time")
				
				# Log each checkin
				for checkin in employee_checkins:
					creation_log.append("checkin_details", {
						"employee_checkin": checkin.get("name"),
						"log_type": checkin.get("log_type"),
						"log_time": checkin.get("time"),
						"skip_auto_attendance": checkin.get("skip_auto_attendance"),
						"attendance": checkin.get("attendance"),
						"processed": 1 if len(employee_checkins) % 2 == 0 else 0
					})
				
				# Get actual employee log data to capture all calculated values
				workday_data = get_actual_employee_log(emp, date, data.get('skip_workday_if_no_weekly_hours'))

				if workday_data is None: 
					if emp not in skipped_by_employee:
						emp_name = frappe.get_value('Employee', emp, 'employee_name') 
						skipped_by_employee[emp] = {
							"employee_name": emp_name or emp,
							"reason": "No Weekly Working Hours",
							"dates": []
						}
					skipped_by_employee[emp]["dates"].append(date)
					creation_log.status = "Skipped"
					creation_log.error_message = ("No Weekly Working Hours found and skipping is enabled.")
					creation_log.insert(ignore_permissions=True)
					frappe.db.commit()
					continue  # Skip to next date 

				# Populate calculated values
				creation_log.hours_worked = workday_data.get("hours_worked", 0)
				creation_log.break_hours = workday_data.get("break_hours", 0)
				creation_log.expected_break_hours = workday_data.get("expected_break_hours", 0)
				creation_log.actual_working_hours = workday_data.get("actual_working_hours", 0)
				creation_log.target_hours = workday_data.get("target_hours", 0)
				creation_log.manual_workday = workday_data.get("manual_workday", 0)
				creation_log.workday_status = workday_data.get("status", "")
				creation_log.attendance = workday_data.get("attendance", "")
				creation_log.checkins_processed = len(employee_checkins) if len(employee_checkins) % 2 == 0 else 0
				
				# Check if holiday or leave
				creation_log.is_holiday = date_is_in_holiday_list(emp, date)
				
				leave_filters = {
					"employee": emp,
					"from_date": ("<=", date),
					"to_date": (">=", date),
					"docstatus": 1
				}
				leave_types = frappe.get_all("Leave Type", filters={"is_compensatory": 1}, pluck="name")
				if leave_types:
					leave_filters["leave_type"] = ['not in', leave_types]
				creation_log.is_on_leave = 1 if frappe.db.exists("Leave Application", leave_filters) else 0
				
				# Create workday if it doesn't exist
				if not frappe.db.exists('Workday', {'employee': emp,'log_date': get_datetime(date)}):
					workday = frappe.new_doc("Workday")
					workday.employee = emp
					workday.company = company
					workday.log_date = get_datetime(date)
					if flag == "Create workday":
						workday.save()
						creation_log.workday = workday.name
						if emp not in created_by_employee:
							emp_name = frappe.get_value('Employee', emp, 'employee_name') 
							created_by_employee[emp]={
								"employee_name": emp_name or emp,
								"workdays": [] 
							}
						created_by_employee[emp]["workdays"].append(workday.name)
				else:
					creation_log.status = "Skipped"
					existing_workday = frappe.db.get_value('Workday', 
						{'employee': emp,'log_date': get_datetime(date)}, 'name')
					creation_log.workday = existing_workday
					if existing_workday:
						if emp not in existing_workdays:
							emp_name = frappe.get_value('Employee', emp, 'employee_name') 
							existing_workdays[emp] = {
								"employee_name": emp_name or emp,
								"reason": "Already Exists",
								"dates": []
							}
						existing_workdays[emp]["dates"].append(date)

				all_missing_dates.add(get_datetime(date))
			
				# Save creation log
				creation_log.insert(ignore_permissions=True)
				frappe.db.commit()

			except Exception as e:
				error_trace = traceback.format_exc()
				message = _("Something went wrong in Workday Creation: {0}".format(str(e)))
				frappe.log_error(message, "Error in bulk_process_workdays")
				
				# Update creation log with error details
				if creation_log:
					creation_log.status = "Failed"
					creation_log.error_message = str(e)
					creation_log.traceback = error_trace
					creation_log.insert(ignore_permissions=True)
					frappe.db.commit()
				else:
					# Create a minimal error log if we couldn't create the initial log
					frappe.get_doc({
						"doctype": "Workday Creation Log",
						"employee": emp,
						"log_date": get_datetime(date),
						"creation_time": frappe.utils.now_datetime(),
						"status": "Failed",
						"error_message": str(e),
						"traceback": error_trace
					}).insert(ignore_permissions=True)
					frappe.db.commit()

	formatted_missing_dates = []
	for missing_date in sorted(all_missing_dates):
		formatted_m_date = formatdate(missing_date,'dd.MM.yyyy')
		formatted_missing_dates.append(formatted_m_date)

	return {
		"message": 1,
		"missing_dates": formatted_missing_dates,
		"flag":flag,
		"created_summary": created_by_employee,
		"skipped_summary": skipped_by_employee,
		"existing_summary": existing_workdays 
	}