import frappe

@frappe.whitelist()
def get_employee_checkin(attendance):
    """"""
    attendance = attendance
    checkin_list = []
    checkin_list = frappe.db.sql(
        """
        SELECT  name,log_type,time,skip_auto_attendance FROM `tabEmployee Checkin` WHERE attendance='%s'
        """%attendance, as_dict=1
    )
    return checkin_list