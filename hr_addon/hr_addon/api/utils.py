from time import time
import frappe

from frappe.utils.data import date_diff, time_diff_in_seconds

#@frappe.whitelist()
def get_employee_checkin(employee,atime):
    ''' select DATE('date time');'''
    employee = employee
    atime = atime
    
    checkin_list = []
    checkin_list = frappe.db.sql(
        """
        SELECT  name,log_type,time,skip_auto_attendance FROM `tabEmployee Checkin` 
        WHERE employee='%s' AND DATE(time)= DATE('%s') ORDER BY time ASC
        """%(employee,atime), as_dict=1
    )
    #print(f'\n\n\n\n inside valid : {checkin_list} \n\n\n\n')
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
    SELECT w.name,w.employee,w.valid_from,w.valid_to,d.day,d.hours  FROM `tabWeekly Working Hours` w  
    LEFT JOIN `tabDaily Hours Detail` d ON w.name = d.parent 
    WHERE w.employee='%s' AND d.day = DAYNAME('%s')
    """%(employee,adate), as_dict=1
    )
    return target_work_hours


@frappe.whitelist()
def view_actual_employee_log(aemployee, adate):
    '''total actual log'''
    weekly_day_hour = []
    weekly_day_hour = get_employee_checkin(aemployee,adate)
    # check empty or none
    if(weekly_day_hour is None):
        return

    # not pair of IN/OUT either missing
    if len(weekly_day_hour)% 2 != 0: return

    # seperate 'IN' from 'OUT'
    # solo_list[start:stop:step]
    clockin_list = [kin.time for x,kin in enumerate(weekly_day_hour) if x % 2 == 0]
    clockout_list = [kout.time for x,kout in enumerate(weekly_day_hour) if x % 2 != 0]

    # get total worked hours
    hours_worked = 0.0
    for i in range(len(clockin_list)):
        wh = time_diff_in_seconds(clockout_list[i],clockin_list[i])
        hours_worked += float(str(wh))
    
    # get total break hours
    break_hours = 0.0
    for i in range(len(clockout_list)):
        if ((i+1) < len(clockout_list)):
            wh = time_diff_in_seconds(clockin_list[i+1],clockout_list[i])
            break_hours += float(str(wh))
    
    # create list
    new_workday = []
    new_workday.append({
        "thour": get_employee_default_work_hour(aemployee,adate)[0].hours,
        "ahour": hours_worked,
        "nbreak": 0,
        "bhour": break_hours,
        "items":get_employee_checkin(aemployee,adate),
    })

    return new_workday




    


    