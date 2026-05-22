frappe.ui.form.on("Employee", {
	refresh(frm) {
		add_custom_links(
			"custom_weekly_working_hours",
			"Weekly Working Hours",
			frm.doc.custom_weekly_working_hours
		);
		add_custom_links(
			"custom_overtime_ledger_entry",
			"Overtime Ledger Entry",
			frm.doc.custom_overtime_ledger_entry
		);
		if (frm.fields_dict.custom_current_overtime_hours && !frm.is_new()) {
			add_overtime_balance_report_link(frm);
		}
	},
	onload(frm) {
		if (!frm.doc.name || frm.is_new()) {
			return;
		}

		frappe.call({
			method: "hr_addon.hr_addon.doctype.weekly_working_hours.weekly_working_hours.get_latest_submitted_weekly_working_hours_for_employee",
			args: { employee: frm.doc.name },
			callback: async (response) => {
				const data = response.message || {};
				const latestEntry = data.weekly_working_hours_entry || "";
				const latestHours = flt(data.total_work_hours || 0);

				const currentEntry = frm.doc.custom_weekly_working_hours || "";
				const currentHours = flt(frm.doc.custom_total_work_hours || 0);

				if (currentEntry === latestEntry && currentHours === latestHours) {
					return;
				}

				await frm.set_value({
					custom_weekly_working_hours: latestEntry || null,
					custom_total_work_hours: latestHours,
				});
				await frm.save();
			},
		});
	},
});

add_custom_links = (fieldname, doctype, docname) => {
	if (!docname || !cur_frm.fields_dict[fieldname]) {
		return;
	}
	const doctype_url = doctype.replace(/ /g, "-").toLowerCase();
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
};

function add_overtime_balance_report_link(frm) {
	const field = frm.fields_dict.custom_current_overtime_hours;
	if (!field) {
		return;
	}

	const hours = flt(frm.doc.custom_current_overtime_hours);
	const hours_label = Number.isFinite(hours) ? hours.toFixed(2) : "0.00";
	const report_url = `/app/query-report/Overtime%20Ledger?employee=${encodeURIComponent(frm.doc.name)}`;

	field.$wrapper.html(
		`<div class="form-group">
			<div class="clearfix">
				<label class="control-label" style="padding-right: 0px;">${__("Current Overtime Hours")}</label>
			</div>
			<div class="control-input-wrapper">
				<a class="control-value like-disabled-input" href="${report_url}">${hours_label} ${__("hours")}</a>
			</div>
		</div>`
	);
}
