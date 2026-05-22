/**
 * HR Addon client script for Attendance — Workday cancel/delete and OLE link.
 */

frappe.ui.form.on("Attendance", {
	refresh(frm) {
		if (frm.doc.custom_workday) {
			add_custom_links("custom_workday", "Workday", frm.doc.custom_workday);
		}
		if (frm.doc.custom_overtime_ledger_entry) {
			add_custom_links(
				"custom_overtime_ledger_entry",
				"Overtime Ledger Entry",
				frm.doc.custom_overtime_ledger_entry
			);
		}
	},

	before_cancel(frm) {
		if (!frm.doc.custom_workday) {
			return;
		}

		frappe.validated = false;

		frappe.confirm(
			__(
				"Do you want to delete the workday {0} and it's linked Workday Creation Log?",
				[frm.doc.custom_workday]
			),
			function () {
				frappe.call({
					method:
						"hr_addon.events.attendance.delete_workday_and_workday_creation_log_on_attendance_cancel",
					args: { doc: frm.doc },
					callback(res) {
						if (res.message === "success") {
							frappe.show_alert({
								message: __(
									"Workday and Workday Creation Log deleted successfully. Cancelling attendance..."
								),
								indicator: "green",
							});

							frappe.call({
								method: "frappe.client.cancel",
								args: { doctype: "Attendance", name: frm.doc.name },
								callback() {
									frappe.show_alert({
										message: __("Attendance cancelled successfully"),
										indicator: "green",
									});
									frm.reload_doc();
								},
							});
						} else {
							frappe.msgprint({
								title: __("Error"),
								message: __("Failed to delete workday: {0}", [
									res.message.error || "Unknown error",
								]),
								indicator: "red",
							});
						}
					},
					error(err) {
						frappe.msgprint({
							title: __("Error"),
							message: __("Error deleting workday: {0}", [
								err.message || JSON.stringify(err),
							]),
							indicator: "red",
						});
					},
				});
			},
			function () {
				if (frm.doc.custom_workday) {
					frappe.call({
						method: "frappe.client.set_value",
						args: {
							doctype: "Workday",
							name: frm.doc.custom_workday,
							fieldname: "attendance",
							value: null,
						},
						callback() {
							frappe.call({
								method: "frappe.client.cancel",
								args: { doctype: "Attendance", name: frm.doc.name },
								callback() {
									frappe.show_alert({
										message: __(
											"Attendance cancelled. Workday was not deleted."
										),
										indicator: "orange",
									});
									frm.reload_doc();
								},
							});
						},
					});
				} else {
					frappe.call({
						method: "frappe.client.cancel",
						args: { doctype: "Attendance", name: frm.doc.name },
						callback() {
							frappe.show_alert({
								message: __("Attendance cancelled."),
								indicator: "orange",
							});
							frm.reload_doc();
						},
					});
				}
			}
		);
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
