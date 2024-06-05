from __future__ import unicode_literals
from time import time
import frappe
from frappe import _

from frappe.utils.data import date_diff, time_diff_in_seconds
from frappe.utils import get_datetime, getdate, today, comma_sep
from frappe.core.doctype.role.role import get_info_based_on_role


#@frappe.whitelist()
def get_employee_checkin(employee,atime):
    ''' select DATE('date time');'''
    employee = employee
    atime = atime
    
    checkin_list = []
    checkin_list = frappe.db.sql(
        """
        SELECT  name,log_type,time,skip_auto_attendance,attendance FROM `tabEmployee Checkin` 
        WHERE employee='%s' AND DATE(time)= DATE('%s') ORDER BY time ASC
        """%(employee,atime), as_dict=1
    )
    return checkin_list

def get_employee_default_work_hour(employee,adate):
    ''' weekly working hour'''
    employee = employee
    adate = adate    
    #validate current or active FY year WHERE --
    # AND YEAR(valid_from) = CAST(%(year)s as INT) AND YEAR(valid_to) = CAST(%(year)s as INT)
    # AND YEAR(w.valid_from) = CAST(('2022-01-01') as INT) AND YEAR(w.valid_to) = CAST(('2022-12-30') as INT);
    target_work_hours= frappe.db.sql(
        """ 
    SELECT w.name,w.employee,w.valid_from,w.valid_to,d.day,d.hours,d.break_minutes  FROM `tabWeekly Working Hours` w  
    LEFT JOIN `tabDaily Hours Detail` d ON w.name = d.parent 
    WHERE w.employee='%s' AND d.day = DAYNAME('%s')
    """%(employee,adate), as_dict=1
    )
    if (target_work_hours is None  or target_work_hours == []):
        msg = f'<div>Please create "Weekly Working Hours" for the selected Employee: {employee} first. </div>'    
        frappe.throw(_(msg))

    return target_work_hours


@frappe.whitelist()
def view_actual_employee_log(aemployee, adate):
    '''total actual log'''
    weekly_day_hour = []
    weekly_day_hour = get_employee_checkin(aemployee,adate)
    # check empty or none
    if(weekly_day_hour is None):
        return
    
    """ if(not len(weekly_day_hour)>0):
        return """
    
    hours_worked = 0.0
    break_hours = 0.0

    # not pair of IN/OUT either missing
    if len(weekly_day_hour)% 2 != 0:
        hours_worked = -36.0
        break_hours = -360.0

    if (len(weekly_day_hour) % 2 == 0):
        # seperate 'IN' from 'OUT'
        clockin_list = [get_datetime(kin.time) for x,kin in enumerate(weekly_day_hour) if x % 2 == 0]
        clockout_list = [get_datetime(kout.time) for x,kout in enumerate(weekly_day_hour) if x % 2 != 0]

        # get total worked hours
        for i in range(len(clockin_list)):
            wh = time_diff_in_seconds(clockout_list[i],clockin_list[i])
            hours_worked += float(str(wh))
        
        # get total break hours
        for i in range(len(clockout_list)):
            if ((i+1) < len(clockout_list)):
                wh = time_diff_in_seconds(clockin_list[i+1],clockout_list[i])
                break_hours += float(str(wh))
        
    # create list
    employee_default_work_hour = get_employee_default_work_hour(aemployee,adate)[0]
    break_minutes = employee_default_work_hour.break_minutes
    wwh = frappe.db.get_list(doctype="Weekly Working Hours", filters={"employee": aemployee}, fields=["name", "no_break_hours", "set_target_hours_to_zero_when_date_is_holiday"])
    no_break_hours = True if len(wwh) > 0 and wwh[0]["no_break_hours"] == 1 else False
    if no_break_hours:
        if hours_worked/60/60 < 6:
            break_minutes = 0

    target_hours = employee_default_work_hour.hours
    if len(wwh) > 0 and wwh[0]["set_target_hours_to_zero_when_date_is_holiday"] == 1:
        if date_is_in_holiday_list(aemployee,adate):
            target_hours = 0
    new_workday = []
    new_workday.append({
        "thour": target_hours,
        "break_minutes": break_minutes,
        "ahour": hours_worked,
        "nbreak": 0,
        "attendance": weekly_day_hour[0].attendance if len(weekly_day_hour) > 0 else "",        
        "bhour": break_hours,
        "items":weekly_day_hour, #get_employee_checkin(aemployee,adate),
    })

    return new_workday

@frappe.whitelist()
def get_actual_employee_log_bulk(aemployee, adate):
    '''total actual log'''
    
    # create list
    new_workday = []
    
    view_employee_attendance = get_employee_attendance(aemployee,adate)
    weekly_day_hour = get_employee_checkin(aemployee,adate)

    for vea in view_employee_attendance:
        
        clk_ls =[]
        #clk_ls = [klt for klt in weekly_day_hour if klt.attendance == vea.name]
        clk_ls = [klt for klt in weekly_day_hour if getdate(klt.time) == getdate(vea.attendance_date)]

        if (not vea is None):
            vea.employee_checkins=clk_ls

        
    # check empty or none
    if((weekly_day_hour is None) or (weekly_day_hour == [])):
        employee_default_work_hour = get_employee_default_work_hour(aemployee,adate)[0]
        new_workday.append({
            "thour": employee_default_work_hour.hours,
            "break_minutes": employee_default_work_hour.break_minutes,
            "ahour": 0,
            "nbreak": 0,
            "attendance": view_employee_attendance[0].name if len(view_employee_attendance) > 0 else "",
            "bhour": 0,
            "items":[],
        })

    
    if(not weekly_day_hour is None):
        #
        hours_worked = 0.0
        break_hours = 0.0

        # not pair of IN/OUT either missing
        if len(weekly_day_hour)% 2 != 0:
            hours_worked = -36.0
            break_hours = -360.0

        if (len(weekly_day_hour) % 2 == 0):
            # seperate 'IN' from 'OUT'
            clockin_list = [get_datetime(kin.time) for x,kin in enumerate(weekly_day_hour) if x % 2 == 0]
            clockout_list = [get_datetime(kout.time) for x,kout in enumerate(weekly_day_hour) if x % 2 != 0]

            # get total worked hours
            for i in range(len(clockin_list)):
                wh = time_diff_in_seconds(clockout_list[i],clockin_list[i])
                hours_worked += float(str(wh))

            # get total break hours
            for i in range(len(clockout_list)):
                if ((i+1) < len(clockout_list)):
                    wh = time_diff_in_seconds(clockin_list[i+1],clockout_list[i])
                    break_hours += float(str(wh))

        employee_default_work_hour = get_employee_default_work_hour(aemployee,adate)[0]
        new_workday.append({
            "thour": employee_default_work_hour.hours,
            "break_minutes": employee_default_work_hour.break_minutes,
            "ahour": hours_worked,
            "nbreak": 0,
            "attendance": weekly_day_hour[0].attendance if len(weekly_day_hour) > 0 else "",
            "bhour": break_hours,
            "items":weekly_day_hour, 
        })

    return new_workday


def get_employee_attendance(employee,atime):
    ''' select DATE('date time');'''
    employee = employee
    atime = atime
    
    #checkin_list = []
    attendance_list = frappe.db.sql(
        """
        SELECT  name,employee,status,attendance_date,shift FROM `tabAttendance` 
        WHERE employee='%s' AND DATE(attendance_date)= DATE('%s') ORDER BY attendance_date ASC
        """%(employee,atime), as_dict=1
    )
    #print(f'\n\n\n\n inside valid : {checkin_list} \n\n\n\n')
    return attendance_list


@frappe.whitelist()
def date_is_in_holiday_list(employee, date):
	holiday_list = frappe.db.get_value("Employee", employee, "holiday_list")
	hl_doc = frappe.get_doc("Holiday List", holiday_list)
	for holiday in hl_doc.holidays:
		if holiday.holiday_date == frappe.utils.get_datetime(date).date():
			return True

	return False

# ----------------------------------------------------------------------
# WORK ANNIVERSARY REMINDERS SEND TO EMPLOYEES LIST IN HR-ADDON-SETTINGS
# ----------------------------------------------------------------------
def send_work_anniversary_notification():
    """Send Employee Work Anniversary Reminders if 'Send Work Anniversary Reminders' is checked"""
    if not int(frappe.db.get_single_value("HR Addon Settings", "enable_work_anniversary_notifications")):
        return
    
    ############## Sending email to specified employees in HR Addon Settings field anniversary_notification_email_list
    emp_email_list = frappe.db.get_all("Employee Item", {"parent": "HR Addon Settings", "parentfield": "anniversary_notification_email_list"}, "employee")
    recipients = []
    for employee in emp_email_list:
        employee_doc = frappe.get_doc("Employee", employee)
        employee_email = employee_doc.get("user_id") or employee_doc.get("personal_email") or employee_doc.get("company_email")
        if employee_email:
            recipients.append({"employee_email": employee_email, "company": employee_doc.company})
        else:
            frappe.throw(_("Email not set for {0}".format(employee)))

    if not recipients:
        frappe.throw(_("Recipient Employees not set in field 'Anniversary Notification Email List'"))

    joining_date = today()
    employees_joined_today = get_employees_having_an_event_on_given_date("work_anniversary", joining_date)
    send_emails(employees_joined_today, recipients, joining_date)

    ############## Sending email to specified employees with Role in HR Addon Settings field anniversary_notification_email_recipient_role
    email_recipient_role = frappe.db.get_single_value("HR Addon Settings", "anniversary_notification_email_recipient_role")
    joining_date = frappe.utils.add_days(today(), 7)
    employees_joined_seven_days_later = get_employees_having_an_event_on_given_date("work_anniversary", joining_date)
    if email_recipient_role:
        role_email_recipients = []
        users_with_role = get_info_based_on_role(email_recipient_role, field="email")
        for user in users_with_role:
            emp_data = frappe.get_cached_value("Employee", {"user_id": user}, ["company", "user_id"], as_dict=True)
            if emp_data:
                role_email_recipients.extend([{"employee_email": emp_data.get("user_id"), "company": emp_data.get("company")}])
            else:
                # leave approver not set
                pass
                # frappe.msgprint(cstr(anniversary_person))

        if role_email_recipients:
            send_emails(employees_joined_seven_days_later, role_email_recipients, joining_date)

    ############## Sending email to specified employee leave approvers if HR Addon Settings field enable_work_anniversaries_for_leave_approver is checked
    if int(frappe.db.get_single_value("HR Addon Settings", "enable_work_anniversaries_for_leave_approver")):
        for company, anniversary_persons in employees_joined_seven_days_later.items():
            for anniversary_person in anniversary_persons:
                if anniversary_person.get("leave_approver"):
                    leave_approver_recipients = [anniversary_person.get("leave_approver")]
                    
                    reminder_text, message = get_work_anniversary_reminder_text_and_message(anniversary_persons, joining_date)
                    send_work_anniversary_reminder(leave_approver_recipients, reminder_text, anniversary_persons, message)

                else:
                    # leave approver not set
                    pass
                    # frappe.msgprint(cstr(anniversary_person))


def send_emails(employees_joined_today, recipients, joining_date):

    for company, anniversary_persons in employees_joined_today.items():
        reminder_text, message = get_work_anniversary_reminder_text_and_message(anniversary_persons, joining_date)
        recipients_by_company = [d.get('employee_email') for d in recipients if d.get('company') == company ]
        if recipients_by_company:
            send_work_anniversary_reminder(recipients_by_company, reminder_text, anniversary_persons, message)


def get_employees_having_an_event_on_given_date(event_type, date):
    """Get all employee who have `event_type` on specific_date
    & group them based on their company. `event_type`
    can be `birthday` or `work_anniversary`"""

    from collections import defaultdict

    # Set column based on event type
    if event_type == "birthday":
        condition_column = "date_of_birth"
    elif event_type == "work_anniversary":
        condition_column = "date_of_joining"
    else:
        return

    employees_born_on_given_date = frappe.db.sql("""
            SELECT `personal_email`, `company`, `company_email`, `user_id`, `employee_name` AS 'name', `leave_approver`, `image`, `date_of_joining`
            FROM `tabEmployee`
            WHERE
                DAY({0}) = DAY(%(date)s)
            AND
                MONTH({0}) = MONTH(%(date)s)
            AND
                YEAR({0}) < YEAR(%(date)s)
            AND
                `status` = 'Active'
        """.format(condition_column), {"date": date}, as_dict=1
    )
    grouped_employees = defaultdict(lambda: [])

    for employee_doc in employees_born_on_given_date:
        grouped_employees[employee_doc.get("company")].append(employee_doc)

    return grouped_employees


def get_work_anniversary_reminder_text_and_message(anniversary_persons, joining_date):
    today_date = today()
    if joining_date == today_date:
        days_alias = "Today"
        completed = "completed"

    elif joining_date > today_date:
        days_alias = "{0} days later".format(date_diff(joining_date, today_date))
        completed = "will complete"

    if len(anniversary_persons) == 1:
        anniversary_person = anniversary_persons[0]["name"]
        persons_name = anniversary_person
        # Number of years completed at the company
        completed_years = getdate().year - anniversary_persons[0]["date_of_joining"].year
        anniversary_person += f" {completed} {get_pluralized_years(completed_years)}"
    else:
        person_names_with_years = []
        names = []
        for person in anniversary_persons:
            person_text = person["name"]
            names.append(person_text)
            # Number of years completed at the company
            completed_years = getdate().year - person["date_of_joining"].year
            person_text += f" {completed} {get_pluralized_years(completed_years)}"
            person_names_with_years.append(person_text)

        # converts ["Jim", "Rim", "Dim"] to Jim, Rim & Dim
        anniversary_person = comma_sep(person_names_with_years, frappe._("{0} & {1}"), False)
        persons_name = comma_sep(names, frappe._("{0} & {1}"), False)

    reminder_text = _("{0} {1} at our Company! 🎉").format(days_alias, anniversary_person)
    message = _("A friendly reminder of an important date for our team.")
    message += "<br>"
    message += _("Everyone, let’s congratulate {0} on their work anniversary!").format(persons_name)

    return reminder_text, message


def send_work_anniversary_reminder(recipients, reminder_text, anniversary_persons, message):
    frappe.sendmail(
        recipients=recipients,
        subject=_("Work Anniversary Reminder"),
        template="anniversary_reminder",
        args=dict(
            reminder_text=reminder_text,
            anniversary_persons=anniversary_persons,
            message=message,
        ),
        header=_("Work Anniversary Reminder"),
    )


def get_pluralized_years(years):
    if years == 1:
        return "1 year"
    return f"{years} years"
