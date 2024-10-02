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


@frappe.whitelist()
def generate_workdays_scheduled_job():
    try:
        hr_addon_settings = frappe.get_doc("HR Addon Settings")
        frappe.logger("Creating Workday").error(f"HR Addon Enabled: {hr_addon_settings.enabled}")
        
        # Check if the HR Addon is enabled
        if hr_addon_settings.enabled == 0:
            frappe.logger("Creating Workday").error("HR Addon is disabled. Exiting...")
            return
        
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
        now = frappe.utils.get_datetime()
        today_weekday_number = now.weekday()
        weekday_name = number2name_dict[today_weekday_number]
        
        # Log the current day and hour
        frappe.logger("Creating Workday").error(f"Today is {weekday_name}, current hour is {now.hour}")
        frappe.logger("Creating Workday").error(f"HR Addon Settings day is {hr_addon_settings.day}, time is {hr_addon_settings.time}")
        
        # Check if the current day and hour match the settings
        if weekday_name == hr_addon_settings.day:
            frappe.logger("Creating Workday").error("Day matched.")
            if now.hour == int(hr_addon_settings.time):
                frappe.logger("Creating Workday").error("Time matched. Generating workdays...")
                # Trigger workdays generation
                generate_workdays_for_past_7_days_now()
            else:
                frappe.logger("Creating Workday").error(f"Time mismatch. Current hour: {now.hour}, Expected hour: {hr_addon_settings.time}")
        else:
            frappe.logger("Creating Workday").error(f"Day mismatch. Today: {weekday_name}, Expected: {hr_addon_settings.day}")
    except Exception as e:
        frappe.log_error("Error in generate_workdays_scheduled_job: {}".format(str(e)), "Scheduled Job Error")

			

@frappe.whitelist()
def generate_workdays_for_past_7_days_now():
    try:
        today = frappe.utils.get_datetime()
        a_week_ago = today - frappe.utils.datetime.timedelta(days=7)
        frappe.logger("Creating Workday").error(f"Processing from {a_week_ago} to {today}")
        
        # Get all active employees
        employees = frappe.db.get_list("Employee", filters={"status": "Active"})
        
        # Log the list of employees for debugging
        frappe.logger("Creating Workday").error(f"Active employees: {employees}")
        
        # Process each employee
        for employee in employees:
            employee_name = employee["name"]
            
            # Log each employee name for debugging
            frappe.logger("Creating Workday").error(f"Processing employee: {employee_name}")
            
            try:
                # Get unmarked workdays for the past 7 days
                unmarked_days = get_unmarked_range(employee_name, a_week_ago.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d"))
                frappe.logger("Creating Workday").error(f"Unmarked days for {employee_name}: {unmarked_days}")
                
                # Prepare data and trigger bulk processing
                data = {
                    "employee": employee_name,
                    "unmarked_days": unmarked_days
                }
                flag = "Create workday"
                
                # Add a try-catch block for the bulk processing
                try:
                    bulk_process_workdays_background(data, flag)
                    frappe.logger("Creating Workday").error(f"Workdays successfully processed for {employee_name}")
                except Exception as e:
                    frappe.log_error(
                        "employee_name: {}, error: {} \n{}".format(employee_name, str(e), frappe.get_traceback()),
                        "Error during bulk processing for employee"
                    )
            except Exception as e:
                frappe.log_error(
                    "Creating Workday, Got Error: {} while fetching unmarked days for: {}".format(str(e), employee_name),
                    "Error during fetching unmarked days"
                )
    except Exception as e:
        frappe.log_error(
            "Creating Workday: Error in generate_workdays_for_past_7_days_now: {}".format(str(e)),
            "Error during generate_workdays_for_past_7_days_now"
        )
