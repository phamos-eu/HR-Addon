import frappe
from frappe import _
from frappe.utils import now_datetime, getdate
from datetime import datetime

@frappe.whitelist(allow_guest=True)
def handle_rfid_scan(**kwargs):
    """Handle incoming Datafox RFID scan requests"""
    
    # Validate mandatory parameters
    if not all(k in kwargs for k in ['df_col_Ausweis_NR', 'df_col_Datum']):
        frappe.throw(_("Missing required parameters: df_col_Ausweis_NR and df_col_Datum"))

    badge_id = kwargs.get('df_col_Ausweis_NR')
    scan_time = kwargs.get('df_col_Datum')
    device_id = kwargs.get('df_col_df_serial', 'Unknown Device')
    log_direction = kwargs.get('df_col_Kennung')  # "K" or "G"
    try:
        # Parse datetime
        scan_datetime = datetime.strptime(scan_time, "%Y-%m-%dT%H:%M:%S")

        # Get employee by badge ID
        employee = frappe.get_value("Employee", 
            {"attendance_device_id": badge_id}, 
            ["name", "employee_name"], 
            as_dict=True)

        if not employee:
            frappe.log_error(f"Datafox RFID Error: Employee {badge_id} not Found in ERP")
            frappe.local.response.update({
                "df_api": 1,
                "df_msg": "Employee not found",
                "http_status_code": 400
            })
            return

        # Convert Kennung to log_type
        log_type = "IN" if log_direction.upper() == "K" else "OUT"

        # Check for existing checkin with same time and log_type
        existing = frappe.db.exists("Employee Checkin", {
            "employee": employee.name,
            "time": scan_datetime,
            "log_type": log_type
        })

        if existing:
            frappe.log_error(f"Datafox RFID Error: {log_type} already recorded at {scan_datetime}")
            frappe.local.response.update({
                "df_api": 1,
                "df_msg": f"{log_type} already recorded at {scan_datetime}",
                "http_status_code": 400
            })
            return 
        
        # Save new Employee Checkin
        doc = frappe.get_doc({
            "doctype": "Employee Checkin",
            "employee": employee.name,
            "employee_name": employee.employee_name,
            "log_type": log_type,
            "time": scan_datetime,
            "device_id": device_id
        })
        doc.insert()
        frappe.db.commit()

        frappe.local.response.update({
            "df_api": 1,
            "df_time": now_datetime().strftime("%Y-%m-%dT%H:%M:%S"),
            "df_beep": 1 if log_type == "IN" else 2,
            "df_msg": f"{'Checked in' if log_type == 'IN' else 'Checked out'}: {employee.employee_name}",
            "http_status_code": 200
        })
        return 
         

    except Exception as e:
        frappe.log_error(f"Datafox RFID Error: {str(e)}")
        frappe.local.response.update({
            "df_api": 1,
            "df_msg": "System error. Please report.",
            "http_status_code": 400
        })
        return 

def calculate_working_hours(check_in, check_out):
    """Calculate working hours between two time objects"""
    if not all([check_in, check_out]):
        return 0
        
    delta = datetime.combine(getdate(), check_out) - datetime.combine(getdate(), check_in)
    return delta.seconds / 3600  # Convert to hours