# Copyright (c) 2022, Jide Olayinka and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, get_datetime, getdate ,add_days,formatdate,flt
from frappe.utils.data import date_diff
import traceback
from hr_addon.hr_addon.api.utils import get_actual_employee_log_for_bulk_process


class Workday(Document):
    def validate(self):
        self.date_is_in_comp_off()
        self.validate_duplicate_workday()

    def date_is_in_comp_off(self):
    # Check if a comp off leave application exists for the given employee and date
        comp_off_leave_application = frappe.db.exists(
        "Leave Application", {
            "employee": self.employee,
            "from_date": ("<=", self.log_date),
            "to_date": (">=", self.log_date),
            "leave_type": "Freizeitausgleich (Nicht buchen!)"
        }
        )
    # Return True if a matching leave application exists, else False
        if comp_off_leave_application:
            self.hours_worked = 0.0
            self.actual_working_hours = -self.target_hours
            self.break_hours = 0.0
            self.total_break_seconds = 0.0
            self.total_work_seconds = flt(self.actual_working_hours * 60 * 60)
        elif self.hours_worked <= 0:
            self.actual_working_hours = 0.0
    

    def validate_duplicate_workday(self):
        workday = frappe.db.exists("Workday", {
            'employee': self.employee,
            'log_date': self.log_date
        })
    
        if workday:
            frappe.throw(
            _("Workday already exists for employee: {0}, on the given date: {1}")
            .format(self.employee, frappe.utils.formatdate(self.log_date))
            )


def bulk_process_workdays_background(data,flag):
    '''bulk workday processing'''
    frappe.logger("Creating Workday").error("bulk_process_workdays_background")
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
            single = get_actual_employee_log_for_bulk_process(data.employee, get_datetime(date))
            
            
            # Check if the workday already exists
            existing_workday = frappe.get_value('Workday', {
                'employee': data.employee,
                'log_date': get_datetime(date)
            })
            
            if existing_workday:
                continue  # Skip creating if it already exists

            doc_dict = {
                    "doctype": 'Workday',
                    "employee": data.employee,
                    "log_date": get_datetime(date),
                    "company": company,
                    "attendance": single.get("attendance"),
                    "hours_worked": single.get("hours_worked"),
                    "break_hours": single.get("break_hours"),
                    "target_hours": single.get("target_hours"),
                    "total_work_seconds": single.get("total_work_seconds"),
                    "expected_break_hours": single.get("expected_break_hours"),
                    "total_break_seconds": single.get("total_break_seconds"),
                    "total_target_seconds": single.get("total_target_seconds"),
                    "actual_working_hours": single.get("actual_working_hours")
                }

            workday = frappe.get_doc(doc_dict)

            if (workday.status == 'Half Day'):
                workday.target_hours = workday.target_hours / 2
            elif (workday.status == 'On Leave'):
                workday.target_hours = 0

            employee_checkins = single.get("employee_checkins")
            if employee_checkins:
                workday.first_checkin = employee_checkins[0].time
                workday.last_checkout = employee_checkins[-1].time

                for employee_checkin in employee_checkins:
                    workday.append("employee_checkins", {
                        "employee_checkin": employee_checkin.get("name"),   
                        "log_type": employee_checkin.get("log_type"),   
                        "log_time": employee_checkin.get("time"),   
                        "skip_auto_attendance": employee_checkin.get("skip_auto_attendance"),   
                    })
            
            if len(employee_checkins) % 2 != 0:
                formatted_date = frappe.utils.formatdate(workday.log_date)
                #frappe.msgprint("CheckIns must be in pairs for the given date: " + formatted_date)
            if flag == "Create workday":
                frappe.logger("Creating Workday").error(flag)
                workday.insert()
                frappe.logger("Creating Workday").error(workday)

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
        # considering today date
        # if today.day <= date_time.day and today.month <= date_time.month and today.year <= date_time.year:
        #   break
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
    
    # Format the dates
    formatted_workdays = []
    for workday in workday_list:
        # Convert to date object
        date_obj = frappe.utils.getdate(workday['log_date'])
        # Format the date to 'd.m.yy'
        formatted_date = formatdate(date_obj, 'dd.MM.yyyy')
        formatted_workdays.append({
            'log_date': formatted_date,
            'name':workday['name']
        })
    
    return formatted_workdays
