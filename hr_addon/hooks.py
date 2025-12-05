from . import __version__ as app_version

app_name = "hr_addon"
app_title = "HR Addon"
app_publisher = "phamos.eu"
app_description = "Addon for Erpnext attendance and employee checkins"
app_icon = "octicon octicon-file-directory"
app_color = "grey"
app_email = "support@phamos.eu"
app_license = "MIT"

after_install = "hr_addon.hr_addon.doctype.workday.workday.create_background_job_for_workday_generation_after_install"
after_migrate = "hr_addon.hr_addon.doctype.workday.workday.create_background_job_for_workday_generation_after_install"

fixtures = [
	{"dt": "Custom Field", "filters": [
		["module", "=", "HR Addon"]
	]}
]
doctype_js = {
	"HR Settings" : "public/js/hr_settings.js"
}

required_apps = ["hrms"]

doc_events = {
	"Leave Application": {
		"on_change": "hr_addon.hr_addon.doctype.hr_addon_settings.hr_addon_settings.export_calendar",
		"on_cancel": "hr_addon.hr_addon.doctype.hr_addon_settings.hr_addon_settings.export_calendar"
	}
}

scheduler_events = {
	"yearly": [
		"hr_addon.hr_addon.doctype.weekly_working_hours.weekly_working_hours.set_from_to_dates",
	],
	"daily": [
		"hr_addon.hr_addon.doctype.hr_addon_settings.hr_addon_settings.send_work_anniversary_notification"
	]
}