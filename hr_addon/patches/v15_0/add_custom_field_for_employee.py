import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

def execute():
    
    frappe.reload_doc("Setup", "doctype", "employee")

    create_custom_field("Employee",
        dict(fieldname="permanent", label="Permanent",
            fieldtype="Check", insert_after="employment_type",
        )
    )
    