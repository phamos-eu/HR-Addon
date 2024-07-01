import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

def execute():
    
    frappe.reload_doc("Assets", "doctype", "Location")
    frappe.reload_doc("HR", "doctype", "employee_checkin")


    create_custom_field("Location",
		dict(fieldname="qr_code_url", label="QR Code URL",
			fieldtype="Data", insert_after="location",read_only=1
		)
	)
	
    make_property_setter("Employee Checkin", "device_id", "depends_on",
			'eval:frappe.user.has_role("HR User") || frappe.user.has_role("HR Manager")',
			"Data")
