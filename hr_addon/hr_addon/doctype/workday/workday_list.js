frappe.listview_settings['Workday'] = {
    //add_fields: ["status", "attendance_date"],
	add_fields: ["status"],
	get_indicator: function (doc) {
		if (["Present", "Work From Home"].includes(doc.status)) {
			return [__(doc.status), "green", "status,=," + doc.status];
		} else if (["Absent", "On Leave"].includes(doc.status)) {
			return [__(doc.status), "red", "status,=," + doc.status];
		} else if (doc.status == "Half Day") {
			return [__(doc.status), "orange", "status,=," + doc.status];
		}
	},

	onload: function(list_view) {
		let me = this;
		const months = moment.months();
		list_view.page.add_inner_button(__("Process Workdays"), function() {
			let dialog = new frappe.ui.Dialog({
				title: __("Process Workdays"),
				fields: [{
					fieldname: 'employee',
					label: __('For Employee'),
					fieldtype: 'Link',
					options: 'Employee',
					get_query: () => {
						return {query: "erpnext.controllers.queries.employee_query"};
					},
					reqd: 1,
					onchange: function() {
						dialog.set_df_property("unmarked_days", "hidden", 1);
						//dialog.set_df_property("status", "hidden", 1);
						dialog.set_df_property("exclude_holidays", "hidden", 1);
						//dialog.set_df_property("month", "value", '');
						dialog.set_df_property("date_from", "value", '');
						dialog.set_df_property("date_to", "value", '');
						dialog.set_df_property("unmarked_days", "options", []);
						dialog.no_unmarked_days_left = false;
					}
				},
				{
					fieldname: 'date_from',
					label: __('Start Date'),
					fieldtype: 'Date',
					reqd: 1,
				},
				{
					fieldname: 'date_to',
					label: __('End Date'),
					fieldtype: 'Date',
					reqd: 1,
					onchange: function() {
						if (dialog.fields_dict.employee.value && dialog.fields_dict.date_from.value) {
							dialog.set_df_property("unmarked_days", "options", []);
							dialog.no_unmarked_days_left = false;
							me.get_day_range_options(
								dialog.fields_dict.employee.value,
								dialog.fields_dict.date_from.value,
								dialog.fields_dict.date_to.value,
							).then(options => {
								if (options.length > 0) {
									//dialog.set_df_property("unmarked_days", "hidden", 0);
									dialog.set_df_property("unmarked_days", "hidden", 1);
									dialog.set_df_property("unmarked_days", "options", options);
								} else {
									dialog.no_unmarked_days_left = true;
								}
							});
						}
					}
				},				
				{
					label: __("Toggle Days to process"),
					fieldtype: "Check",
					fieldname: "toggle_days",
					hidden: 0,
					onchange: function() {						
						if (dialog.fields_dict.employee.value && dialog.fields_dict.date_to.value) {
							dialog.set_df_property("unmarked_days", "hidden", !dialog.fields_dict.toggle_days.get_value());
							dialog.set_df_property("exclude_holidays", "hidden", !dialog.fields_dict.toggle_days.get_value());
						}
					}
				},
				{
					label: __("Exclude Holidays"),
					fieldtype: "Check",
					fieldname: "exclude_holidays",
					hidden: 1,
					read_only: 1,
					onchange: function() {
						if (dialog.fields_dict.employee.value && dialog.fields_dict.month.value) {
							//dialog.set_df_property("status", "hidden", 0);
							dialog.set_df_property("unmarked_days", "options", []);
							dialog.no_unmarked_days_left = false;
							me.get_multi_select_options(
								dialog.fields_dict.employee.value,
								dialog.fields_dict.month.value,
								dialog.fields_dict.exclude_holidays.get_value()
							).then(options => {
								if (options.length > 0) {
									//dialog.set_df_property("unmarked_days", "hidden", 0);
									dialog.set_df_property("unmarked_days", "hidden", 1);
									dialog.set_df_property("unmarked_days", "options", options);									
								} else {
									dialog.no_unmarked_days_left = true;
								}
							});
						}
					}
				},
				{
					label: __("Unprocessed Workdays for days"),
					fieldname: "unmarked_days",
					fieldtype: "MultiCheck",
					options: [],
					columns: 2,
					hidden: 1,
				}],
				primary_action(data) {
					if (cur_dialog.no_unmarked_days_left) {
						frappe.msgprint(__("Workday for the period: {0} - {1} , has already been processed for the Employee {2}",
							[dialog.fields_dict.date_to.value,dialog.fields_dict.date_from.value, dialog.fields_dict.employee.value]));
					} else {
						frappe.confirm(__('Process workday for {0} for the period of {1} to {2}?', [data.employee, data.date_from,data.date_to]), () => {
							frappe.call({
								method: "hr_addon.hr_addon.doctype.workday.workday.process_bulk_workday",
								args: {
									data: data
								},
								callback: function (r) {
									if (r.message === 1) {
										frappe.show_alert({
											message: __("Workdays Processed"),
											indicator: 'blue'
										});
										cur_dialog.hide();
									}
								}
							});
						});
					}
					dialog.hide();
					list_view.refresh();
				},
				primary_action_label: __('Process Workdays')

			});
			//dialog.$wrapper.find('.btn-modal-primary').css("color","red");
			dialog.$wrapper.find('.btn-modal-primary').removeClass('btn-primary').addClass('btn-dark');
			dialog.show();
		});
		list_view.page.change_inner_button_type('Process Workdays',null, 'dark');
	},
	get_day_range_options: function(employee, from_day, to_day) {
		return new Promise(resolve => {
			frappe.call({				
				method: 'hr_addon.hr_addon.doctype.workday.workday.get_unmarked_range',
				async: false,
				args: {
					employee: employee,
					from_day: from_day,
					to_day: to_day
				}
			}).then(r => {
				var options = [];
				for (var d in r.message) {
					var momentObj = moment(r.message[d], 'YYYY-MM-DD');
					var date = momentObj.format('DD-MM-YYYY');
					options.push({
						"label": date,
						"value": r.message[d],
						"checked": 1
					});
				}
				resolve(options);
			});
		});
	},
};
