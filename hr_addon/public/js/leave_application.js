function set_unfiltered_leave_type_query(frm) {
	frm.set_query("leave_type", () => {
		const filters = {};
		if (frappe.meta.has_field("Leave Type", "enabled")) {
			filters.enabled = 1;
		}
		return { filters };
	});
}

frappe.ui.form.on("Leave Application", {
	refresh(frm) {
		set_unfiltered_leave_type_query(frm);
		frm.trigger("set_first_half_day_holiday");
		frm.trigger("update_overtime_leave_balance_indicator");
	},

	employee(frm) {
		set_unfiltered_leave_type_query(frm);
		frm.trigger("update_overtime_leave_balance_indicator");
	},

	from_date(frm) {
		set_unfiltered_leave_type_query(frm);
		frm.trigger("set_first_half_day_holiday");
		frm.trigger("update_overtime_leave_balance_indicator");
	},

	to_date(frm) {
		set_unfiltered_leave_type_query(frm);
		frm.trigger("set_first_half_day_holiday");
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

	half_day(frm) {
		frm.trigger("update_overtime_leave_balance_indicator");
	},

	half_day_date(frm) {
		frm.trigger("update_overtime_leave_balance_indicator");
	},

	set_first_half_day_holiday(frm) {
		if (frm.doc.docstatus !== 0 || !frm.doc.from_date || !frm.doc.to_date) {
			return;
		}

		const from_date = frm.doc.from_date;
		const to_date = frm.doc.to_date;

		frappe.call({
			method: "hr_addon.overrides.custom_leave_application.get_first_half_day_holiday",
			args: {
				from_date,
				to_date,
				employee: frm.doc.employee,
				leave_type: frm.doc.leave_type,
			},
			callback(r) {
				if (!r.message || frm.doc.from_date !== from_date || frm.doc.to_date !== to_date) {
					return;
				}
				const holiday_date = r.message;
				const set_half_day_date = () => {
					const done = () => frm.trigger("set_total_leave_days");
					if (frm.doc.half_day_date === holiday_date) {
						done();
						return;
					}
					frm.set_value("half_day_date", holiday_date).then(done);
				};
				if (frm.doc.half_day) {
					set_half_day_date();
					return;
				}
				frm.set_value("half_day", 1).then(set_half_day_date);
			},
		});
	},

	set_total_leave_days(frm) {
		if (
			frm.doc.docstatus !== 0 ||
			!frm.doc.employee ||
			!frm.doc.leave_type ||
			!frm.doc.from_date ||
			!frm.doc.to_date
		) {
			return;
		}

		frappe.call({
			method: "hr_addon.overrides.custom_leave_application.get_total_leave_days",
			args: {
				employee: frm.doc.employee,
				leave_type: frm.doc.leave_type,
				from_date: frm.doc.from_date,
				to_date: frm.doc.to_date,
				half_day: frm.doc.half_day,
				half_day_date: frm.doc.half_day_date,
			},
			callback(r) {
				if (r.message === undefined || r.message === null) {
					return;
				}
				frm.set_value("total_leave_days", r.message);
			},
		});
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
