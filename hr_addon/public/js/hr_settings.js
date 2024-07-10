frappe.ui.form.on("HR Settings", {
	refresh: (frm) => {
		if(!frm.is_new()) {
			frm.dashboard.set_headline_alert(`
				<span class="hidden-xs">There's some additional configuration for 'Work Anniversaries' which you'll find in <a style="text-decoration: underline;" onclick="frappe.set_route('Form', 'HR Addon Settings', 'HR Addon Settings');">HR Addon Settings</a></span>
			`);
		}

		frm.set_df_property("send_work_anniversary_reminders", "description", "There's some additional configuration for this notification in 'HR Addon Settings' please check.");
	}
})
