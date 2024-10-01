# Copyright (c) 2022, Jide Olayinka and contributors
# For license information, please see license.txt

import frappe, os
from frappe.model.document import Document

from hr_addon.hr_addon.doctype.workday.workday import get_unmarked_range, bulk_process_workdays_background

class HRAddonSettings(Document):
	def before_save(self):
		# remove the old ics file
		old_doc = self.get_doc_before_save()
		if old_doc:
			old_file_name = old_doc.name_of_calendar_export_ics_file
			if old_file_name != self.name_of_calendar_export_ics_file:
				os.remove("{}/public/files/{}.ics".format(frappe.utils.get_site_path(), old_file_name))

		# remove also the Urlaubskalender.ics, if exist
		if os.path.exists("{}/public/files/Urlaubskalender.ics".format(frappe.utils.get_site_path())):
			os.remove("{}/public/files/Urlaubskalender.ics".format(frappe.utils.get_site_path()))


@frappe.whitelist()
def download_ics_file():
	settings = frappe.get_doc("HR Addon Settings")

	file_name = ""
	if settings.ics_folder_path:
		file_name = os.path.join(settings.ics_folder_path, settings.name_of_calendar_export_ics_file + ".ics")
	else:
		file_name = "{}/public/files/{}.ics".format(frappe.utils.get_site_path(), settings.name_of_calendar_export_ics_file)
	
	if os.path.exists(file_name):
		with open(file_name, 'r') as file:
			file_content = file.read()
		return file_content
	else:
		frappe.throw(f"File '{file_name}' not found.")

import frappe

@frappe.whitelist()
def generate_workdays_scheduled_job():
	hr_addon_settings = frappe.get_doc("HR Addon Settings")
	if hr_addon_settings.enabled == 0:
		return
	frappe.logger("Creating Workday").error(hr_addon_settings.enabled)
	
	# Mapping weekday numbers to names
	number2name_dict = {
		0: "Monday",
		1: "Tuesday",
		2: "Wednesday",
		3: "Thursday",
		4: "Friday",
		5: "Saturday",
		6: "Sunday"
	}
	
	# Get the current date and time
	now = frappe.utils.datetime.datetime.now()
	today_weekday_number = now.weekday()
	weekday_name = number2name_dict[today_weekday_number]
	frappe.logger("Creating Workday").error(weekday_name)
	# Check if the current day and hour match the settings
	if weekday_name == hr_addon_settings.day:
		if now.hour == int(hr_addon_settings.time):
			# Trigger workdays generation
			generate_workdays_for_past_7_days_now()

@frappe.whitelist()
def generate_workdays_for_past_7_days_now():
    today = frappe.utils.datetime.datetime.now()
    a_week_ago = today - frappe.utils.datetime.timedelta(days=7)
    frappe.logger("Creating Workday").error(a_week_ago)
    # Get all active employees
    employees = frappe.db.get_list("Employee", filters={"status": "Active"})
    
    # Log the list of employees for debugging
    frappe.logger("Creating Workday").error(employees)
    
    # Process each employee
    for employee in employees:
        employee_name = employee["name"]
        
        # Log each employee name for debugging
        frappe.logger("Creating Workday").error(employee_name)
        
        # Get unmarked workdays for the past 7 days
        unmarked_days = get_unmarked_range(employee_name, a_week_ago.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d"))
        frappe.logger("Creating Workday").error(unmarked_days)
        # Prepare data and trigger bulk processing
        data = {
            "employee": employee_name,
            "unmarked_days": unmarked_days
        }
        flag = "Create workday"
        bulk_process_workdays_background(data, flag)
