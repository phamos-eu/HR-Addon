from __future__ import unicode_literals
from time import time
import frappe
from frappe import _

from frappe.utils.data import date_diff, time_diff_in_seconds
from frappe.utils import cint, cstr, formatdate, get_datetime, getdate, nowdate

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
    wwh = frappe.db.get_list(doctype="Weekly Working Hours", filters={"employee": aemployee}, fields=["name", "no_break_hours"])
    no_break_hours = True if len(wwh) > 0 and wwh[0]["no_break_hours"] == 1 else False
    if no_break_hours:
        if hours_worked/60/60 < 6:
            break_minutes = 0
    new_workday = []
    new_workday.append({
        "thour": employee_default_work_hour.hours,
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

