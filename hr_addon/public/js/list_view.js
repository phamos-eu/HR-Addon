frappe.provide("hr_addon.frappe.views");
frappe.listview_settings["Weekly Working Hours"] = {
	onload: function (list_view) {
		
			list_view.page.add_button(__("Update Year"), function () {
				frappe.call({
					method: "hr_addon.custom_scripts.custom_python.weekly_working_hours.set_from_to_dates",
					args: {},
					callback(r) {}
				});
				window.location.reload();
			});
		
	},
};


