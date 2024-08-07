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

def generate_workdays_scheduled_job():
	hr_addon_settings = frappe.get_doc("HR Addon Settings")
	if hr_addon_settings.enabled == 0:
		return
	day = hr_addon_settings.day
	time = hr_addon_settings.time
	number2name_dict= {
		0:"Monday",
		1:"Tuesday",
		2:"Wednesday",
		3:"Thursday",
		4:"Friday",
		5:"Saturday",
		6:"Sunday"
	}
	now = frappe.utils.datetime.datetime.now()
	today_weekday_number = now.weekday()
	weekday_name = number2name_dict[today_weekday_number]
	if weekday_name == day:
		if now.hour == int(time):
			generate_workdays_for_past_7_days_now()


@frappe.whitelist()
def generate_workdays_for_past_7_days_now():
	today = frappe.utils.datetime.datetime.now()
	a_week_ago = today - frappe.utils.datetime.timedelta(days=7)
	employees = frappe.db.get_list("Employee", filters={"status": "Active"})
	for employee in employees:
		employee_name = employee["name"]
		unmarked_days = get_unmarked_range(employee_name, a_week_ago.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d"))
		data = {
			"employee": employee_name,
			"unmarked_days": unmarked_days
		}
		bulk_process_workdays_background(data)
