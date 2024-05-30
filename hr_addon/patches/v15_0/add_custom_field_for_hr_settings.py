import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

def execute():
    
    frappe.reload_doc("HR", "doctype", "HR Settings")

    create_custom_field("HR Settings",
		dict(fieldname="danger_zone_section", label="\u26a0\ufe0f Danger Zone \u26a0\ufe0f",
			fieldtype="Section Break", insert_after="allow_employee_checkin_from_mobile_app",
		)
	)
   
    create_custom_field("HR Settings",
        dict(fieldname="update_year", label="Update Year",
            fieldtype="Button", insert_after="danger_zone_section",description="Clicking this button will retrieve the current fiscal year and update the 'From' and 'To' year fields for Weekly Working Hours records created this year."
        )
    )

     