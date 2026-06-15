frappe.ui.form.on("Leave Application", {
	employee(frm) {
		frm.trigger("update_overtime_leave_balance_indicator");
	},

	leave_type(frm) {
		if (frm.doc.leave_type) {
			frappe.call({
				method: "frappe.client.get_value",
				args: {
					doctype: "Leave Type",
					filters: { name: frm.doc.leave_type },
					fieldname: ["color", "custom_is_deducted_from_overtime_ledger"],
				},
				callback(r) {
					if (r.exc) {
						return;
					}
					frm.set_value("color", (r.message && r.message.color) || " ");
					frm.trigger("update_overtime_leave_balance_indicator");
				},
			});
		} else {
			frm.set_value("color", " ");
		}
	},

	from_date(frm) {
		frm.trigger("update_overtime_leave_balance_indicator");
	},

	to_date(frm) {
		frm.trigger("update_overtime_leave_balance_indicator");
	},

	half_day(frm) {
		frm.trigger("update_overtime_leave_balance_indicator");
	},

	half_day_date(frm) {
		frm.trigger("update_overtime_leave_balance_indicator");
	},

	refresh(frm) {
		frm.trigger("update_overtime_leave_balance_indicator");
	},

	update_overtime_leave_balance_indicator(frm) {
		if (frm.doc.docstatus !== 0 || !frm.doc.employee || !frm.doc.leave_type) {
			return;
		}

		frappe.db.get_value(
			"Leave Type",
			frm.doc.leave_type,
			"custom_is_deducted_from_overtime_ledger",
			(r) => {
				if (!r || !r.custom_is_deducted_from_overtime_ledger) {
					return;
				}

				frappe.call({
					method: "hr_addon.events.overtime_ledger.get_employee_overtime_balance",
					args: { employee: frm.doc.employee },
					callback(res) {
						if (!res.message) {
							return;
						}
						const balance =
							typeof res.message === "object" && "balance" in res.message
								? parseFloat(res.message.balance) || 0
								: parseFloat(res.message) || 0;

						frappe.show_alert(
							{
								message: __("Current overtime balance: {0} hours", [
									balance.toFixed(2),
								]),
								indicator: balance > 0 ? "blue" : "orange",
							},
							5
						);
					},
				});
			}
		);
	},
});
