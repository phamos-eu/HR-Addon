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
	]},
    {
        "dt": "DocType Link",
        "filters": [
            ["parenttype", "=", "DocType"],
            ["parent", "in", ["Employee", "Leave Application"]],
        ]
    },
]
doctype_js = {
	"HR Settings" : "public/js/hr_settings.js",
	"Employee": "public/js/employee.js",
	"Leave Application": "public/js/leave_application.js",
	"Attendance": "public/js/attendance.js",
}

required_apps = ["hrms"]

doc_events = {
	"Leave Application": {
		"validate": "hr_addon.events.leave_application.validate_leave_application",
		"on_change": "hr_addon.hr_addon.doctype.hr_addon_settings.hr_addon_settings.export_calendar",
		"on_cancel": [
			"hr_addon.hr_addon.doctype.hr_addon_settings.hr_addon_settings.export_calendar",
			"hr_addon.events.leave_application.restore_overtime_on_leave_cancel",
		],
		"on_submit": "hr_addon.events.leave_application.reduce_overtime_on_leave_submit",
	},
	"Attendance": {
		"on_submit": "hr_addon.events.attendance.create_overtime_ledger_entry_on_attendance_submit",
		"on_cancel": [
			"hr_addon.events.attendance.cancel_overtime_ledger_entry_on_attendance_cancel",
			"hr_addon.events.attendance.clear_workday_reference_on_attendance_trash",
		],
		"on_trash": "hr_addon.events.attendance.clear_workday_reference_on_attendance_trash",
	},
	"Overtime Ledger Entry": {
		"after_insert": "hr_addon.events.overtime_ledger.after_insert_overtime_ledger_entry",
	},
}

scheduler_events = {
	"yearly": [
		"hr_addon.hr_addon.doctype.weekly_working_hours.weekly_working_hours.set_from_to_dates",
	],
	"daily": [
		"hr_addon.hr_addon.doctype.hr_addon_settings.hr_addon_settings.send_work_anniversary_notification",
		"hr_addon.hr_addon.doctype.hr_addon_settings.hr_addon_settings.repost_all_overtime_ledger_entries",
	]
}

override_doctype_class = {
	"Leave Application": "hr_addon.hr_addon.overrides.custom_leave_application.HrAddonLeaveApplication",
}