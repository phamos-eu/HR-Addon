frappe.ui.form.on("Employee", {
    refresh(frm) {
        add_custom_links("custom_weekly_working_hours", "Weekly Working Hours", cur_frm.doc.custom_weekly_working_hours);
    },
	onload(frm) {
		if (!frm.doc.name || frm.is_new()) {
			return;
		}

		frappe.call({
			method: "hr_addon.hr_addon.doctype.weekly_working_hours.weekly_working_hours.get_latest_submitted_weekly_working_hours_for_employee",
			args: { employee: frm.doc.name },
			callback: (response) => {
				const data = response.message || {};
				const latestEntry = data.weekly_working_hours_entry || "";
				const latestHours = flt(data.total_work_hours || 0);

				const currentEntry = frm.doc.custom_weekly_working_hours || "";
				const currentHours = flt(frm.doc.custom_total_work_hours || 0);

				if (currentEntry === latestEntry && currentHours === latestHours) {
					return;
				}

				frappe.db.set_value("Employee", frm.doc.name, {
					custom_weekly_working_hours: latestEntry || null,
					custom_total_work_hours: latestHours,
				});
			},
		});
	},
});

add_custom_links = (fieldname, doctype, docname) => {
  doctype_url = doctype.replace(/ /g, "-").toLowerCase();
  cur_frm.fields_dict[fieldname].$wrapper.html(
    `<div class="form-group">
      <div class="clearfix">
        <label class="control-label" style="padding-right: 0px;">${doctype}</label>
      </div>
      <div class="control-input-wrapper">
        <a class="control-value like-disabled-input" href="/app/${doctype_url}/${docname}">${docname}</a>
      </div>
    </div>`
  );
}
