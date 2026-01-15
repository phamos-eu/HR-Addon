frappe.listview_settings['Workday'] = {
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
				fields: [		
					{
					fieldname: 'skip_workday_if_no_weekly_hours',
					label: __('Skip Workday if No Weekly Working Hours'),
					fieldtype: 'Check',
					default: 0
				},
					{
					fieldname: 'employee',
					label: __('For Employee(s) - Leave empty for all active'),
					fieldtype: 'MultiSelectList',
					get_data: function(txt) {
						return frappe.db.get_link_options('Employee', txt, {status: 'Active'});
					},
					onchange: function() {
						dialog.set_df_property("unmarked_days", "hidden", 1);
						dialog.set_df_property("exclude_holidays", "hidden", 1);
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
						let employees = dialog.fields_dict.employee.value;
						if (employees && employees.length > 0 && dialog.fields_dict.date_from.value) {
							dialog.set_df_property("unmarked_days", "options", []);
							dialog.no_unmarked_days_left = false;
							me.get_day_range_options(
								employees,
								dialog.fields_dict.date_from.value,
								dialog.fields_dict.date_to.value,
							).then(options => {
								if (options.length > 0) {
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
						let employees = dialog.fields_dict.employee.value;
						if (employees && employees.length > 0 && dialog.fields_dict.date_to.value) {
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
							dialog.set_df_property("unmarked_days", "options", []);
							dialog.no_unmarked_days_left = false;
							me.get_multi_select_options(
								dialog.fields_dict.employee.value,
								dialog.fields_dict.month.value,
								dialog.fields_dict.exclude_holidays.get_value()
							).then(options => {
								if (options.length > 0) {
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
					// Check if no employees are selected
					if (!data.employee || data.employee.length === 0) {
						frappe.confirm(
							__('No employee selected. Do you want to process workdays for all active employees?'),
							function() {
								// User confirmed - get all active employees
								frappe.call({
									method: 'frappe.client.get_list',
									args: {
										doctype: 'Employee',
										filters: {
											status: 'Active'
										},
										fields: ['name']
									},
									callback: function(r) {
										if (r.message && r.message.length > 0) {
											let all_employees = r.message.map(emp => emp.name);
											data.employee = all_employees;
											processWorkdays(data);
										} else {
											frappe.msgprint(__('No active employees found'));
										}
									}
								});
							},
							function() {
								// User cancelled
								frappe.msgprint(__('Please select at least one employee'));
							}
						);
						return;
					}
					
					// Process workdays for selected employees
					processWorkdays(data);
					
					// Helper function to process workdays
					function processWorkdays(data) {
						if (dialog.no_unmarked_days_left) {
							frappe.call({
								method: "hr_addon.hr_addon.doctype.workday.workday.get_created_workdays",
								args: {
									employees: data.employee,
									date_from: data.date_from,
									date_to: data.date_to
								},
								callback: function(response) {
									if (response.message) {
										let workdays = response.message;
							
										let workday_dates = workdays.map(workday => workday.log_date);
							
										let workday_dates_string = workday_dates.map(date => `• ${date.trim()}`).join('<br>'); 
										frappe.msgprint(
										__("Workday for the period: {0} - {1}, has already been processed for the selected Employee(s). <br><br>For following dates workdays are available:<br>{2}",
										[
										  frappe.datetime.str_to_user(data.date_from),
										  frappe.datetime.str_to_user(data.date_to),
										  workday_dates_string
										]));
									}
								}
							});
						} else {
							frappe.call({
								method: "hr_addon.hr_addon.doctype.workday.workday.bulk_process_workdays",
								args: {
									data: data,
									flag: "Do not create workday"
								},
								callback: function(response) {
									if (response.message) {
										let missingDates = response.message.missing_dates;
										let missing_dates_string = missingDates.length > 0 ? missingDates.join(", ") : "None";
										let employee_list = Array.isArray(data.employee) ? data.employee : [data.employee];
										let employee_count = employee_list.length;
										
										// Fetch employee names
										frappe.call({
											method: 'frappe.client.get_list',
											args: {
												doctype: 'Employee',
												filters: {
													name: ['in', employee_list]
												},
												fields: ['name', 'employee_name']
											},
											callback: function(emp_response) {
												let employee_names = '';
												if (emp_response.message && emp_response.message.length > 0) {
													employee_names = emp_response.message.map(emp => 
														`• ${emp.employee_name} (${emp.name})`
													).join('<br>');
												} else {
													employee_names = employee_list.map(emp => `• ${emp}`).join('<br>');
												}
												if(missing_dates_string != "None") {
													frappe.confirm(
													__("Are you sure you want to process workdays for the following {0} employee(s) from {1} to {2}?<br><br><b>Employees:</b><br>{3}<br><br><b>Dates to process:</b><br>{4}", [
														employee_count,
														frappe.datetime.str_to_user(data.date_from),
														frappe.datetime.str_to_user(data.date_to),
														employee_names,
														missing_dates_string.split(',').map(date => `• ${date.trim()}`).join('<br>')
													]),
													function() {
														frappe.call({
															method: "hr_addon.hr_addon.doctype.workday.workday.bulk_process_workdays",
															args: {
																data: data,
																flag: "Create workday"
															},
															callback: function(r) {
																if (r.message && r.message.message === 1) {
																	const summary = r.message.created_summary || {}; 
																	const skipped_summary = r.message.skipped_summary || {}; 
																	const existing_summary = r.message.existing_summary || {}; 
																	let lines = [];
																	
																	Object.keys(summary).forEach(empId => { 
																		const emp = summary[empId];
																		if(emp.workdays.length){
																			lines.push(`<b>${emp.employee_name} (${empId})</b>: ${emp.workdays.join(", ")}`
																		); }
																		})
																	Object.keys(skipped_summary).forEach(empId => { 
																		const emp = skipped_summary[empId];
																		if(emp.dates.length){
																			lines.push(`<b>${emp.employee_name} (${empId})</b>: ${emp.reason} (${emp.dates.join(", ")})`
																		); }
																		})
																	Object.keys(existing_summary).forEach(empId => { 
																		const emp = existing_summary[empId];
																		if(emp.dates.length){
																			lines.push(`<b>${emp.employee_name} (${empId})</b>: ${emp.reason} (${emp.dates.join(", ")})`
																		); }
																		})
																	if(lines.length){
																		frappe.msgprint(
																			{
																				title: __('Workdays Created'), 
																				message: lines.join("<br>"), 
																			}
																		)
																	}
																	else{
																		frappe.msgprint(__("No workdays were created.") ); 
																	}
																		
																	frappe.show_alert({
																		message: __("Workdays Processed"),
																		indicator: "blue",
																	});
																	dialog.hide();
																	list_view.refresh();
																}
															},
														});
													},
													function() {
														// User cancelled
													}
													);}
												else{
													frappe.msgprint(__("No new workdays to process for the selected employee(s) in the given date range.") ); 
												}	
											}
										});
									}
								}
							});
						}
					}
				},
				primary_action_label: __('Process Workdays')

			});
		dialog.$wrapper.find('.btn-modal-primary').removeClass('btn-primary').addClass('btn-dark');
		dialog.show();
		
		// Fetch default value from HR Addon Settings
		frappe.db.get_single_value('HR Addon Settings', 'skip_workday_if_no_weekly_hours')
			.then(value => {
				dialog.set_value('skip_workday_if_no_weekly_hours', value || 0);
			});
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
