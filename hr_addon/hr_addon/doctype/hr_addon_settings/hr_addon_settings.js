// Copyright (c) 2022, phamos.eu and contributors
// For license information, please see license.txt

frappe.ui.form.on('HR Addon Settings', {
	refresh: function(frm) {
		seed_default_minimum_break_rules_in_form(frm);
        frm.set_query("anniversary_notification_email_list", function () {
            return {
                filters: {
                    status: "Active",
                },
            };
        });
		// Update break calculation logic explanation on form load
		update_break_calculation_logic(frm);
		
		// Listen for theme changes and update the HTML field
		if (!frm._theme_observer) {
			frm._theme_observer = new MutationObserver(function(mutations) {
				mutations.forEach(function(mutation) {
					if (mutation.type === 'attributes' && mutation.attributeName === 'class') {
						update_break_calculation_logic(frm);
					}
				});
			});
			frm._theme_observer.observe(document.body, {
				attributes: true,
				attributeFilter: ['class']
			});
			
			// Also listen for system theme changes
			if (window.matchMedia) {
				frm._theme_media_query = window.matchMedia('(prefers-color-scheme: dark)');
				frm._theme_media_query.addListener(function() {
					update_break_calculation_logic(frm);
				});
			}
		}
	},

	workday_break_calculation_mechanism: function(frm) {
		// Update break calculation logic explanation when option changes
		update_break_calculation_logic(frm);
	},

	swap_hours_worked_and_actual_working_hours: function(frm) {
		// Update break calculation logic explanation when swap field changes
		update_break_calculation_logic(frm);
	},

	validate: function(frm){
		if (frm.doc.name_of_calendar_export_ics_file && frm.doc.name_of_calendar_export_ics_file.length == 0){
			const randomString = generateRandomString(24);
			frm.set_value("name_of_calendar_export_ics_file", randomString)
		}

		const frozen_changed =
			String(frm.doc.overtime_frozen || "") !==
			String(frm.doc.__prev_overtime_frozen || "");
		if (frozen_changed) {
			frm.doc.__repost_oles_after_save = 1;
		}
		if (frm.doc.__repost_oles_after_save) {
			return new Promise(function (resolve) {
				frappe.confirm(
					__("The overtime frozen date has changed. Do you want to repost all Overtime Ledger entries after saving?"),
					function () {
						repost_all_overtime_ledger_entries(frm);
						resolve();
					},
					function () {
						frm.doc.overtime_frozen = frm.doc.__prev_overtime_frozen;
						frm.doc.__repost_oles_after_save = 0;
						resolve();
					}
				);
			});
		}
	},

	after_save: function(frm){
		frm.doc.__repost_oles_after_save = 0;
		frm.doc.__prev_overtime_frozen = frm.doc.overtime_frozen;
		if (frm.doc.name_of_calendar_export_ics_file && frm.doc.name_of_calendar_export_ics_file.length < 24){
			frappe.msgprint("The filename is less than 24 characters. Please, consider to have a longer filename or leave it empty to get a random filename.")
		}
	},

	download_ics_file: function(frm){
		frappe.call({
			method: 'hr_addon.hr_addon.doctype.hr_addon_settings.hr_addon_settings.download_ics_file',
			callback: function (r) {
				var blob = new Blob([r.message], { type: 'application/octet-stream' });
				var link = document.createElement('a');
				link.href = window.URL.createObjectURL(blob);
				link.download = frm.doc.name_of_calendar_export_ics_file + ".ics";
				link.click();
			}
		});
	},

	generate_workdays_for_past_7_days_now: function(frm){
		frappe.call({
			method: "hr_addon.hr_addon.doctype.workday.workday.generate_workdays_for_past_7_days_now",
		}).then(r => {
			frappe.msgprint("The workdays have been generated.")
		})
	}
});

function get_default_minimum_break_rules() {
	return [
		{ from_hours: 0, to_hours: 6, minimum_break_minutes: 0 },
		{ from_hours: 6, to_hours: 9, minimum_break_minutes: 30 },
		{ from_hours: 9, to_hours: 100, minimum_break_minutes: 45 },
	];
}

function seed_default_minimum_break_rules_in_form(frm) {
	if (!frm.doc || !Array.isArray(frm.doc.minimum_break_rule)) return;
	if (frm.doc.minimum_break_rule.length > 0) return;

	get_default_minimum_break_rules().forEach((row) => {
		frm.add_child("minimum_break_rule", row);
	});
	frm.refresh_field("minimum_break_rule");
}

function generateRandomString(length) {
	const characters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
	let randomString = '';
	
	for (let i = 0; i < length; i++) {
	  const randomIndex = Math.floor(Math.random() * characters.length);
	  randomString += characters.charAt(randomIndex);
	}
	
	return randomString;
}

function get_break_calculation_logic_html(mechanism, swapEnabled = false) {
	// Detect theme (dark or light)
	const isDarkTheme = document.body.classList.contains('dark-theme') || 
		(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
	
	// Theme-aware colors
	const colors = {
		light: {
			bg1: '#e7f3ff',
			bg2: '#fff3cd',
			bg3: '#d1ecf1',
			border1: '#007bff',
			border2: '#ffc107',
			border3: '#17a2b8',
			text: '#333',
			textSecondary: '#666',
			heading1: '#007bff',
			heading2: '#856404',
			heading3: '#0c5460'
		},
		dark: {
			bg1: 'rgba(0, 123, 255, 0.15)',
			bg2: 'rgba(255, 193, 7, 0.15)',
			bg3: 'rgba(23, 162, 184, 0.15)',
			border1: '#4dabf7',
			border2: '#ffd43b',
			border3: '#66d9ef',
			text: 'var(--text-color)',
			textSecondary: 'var(--text-muted)',
			heading1: '#4dabf7',
			heading2: '#ffd43b',
			heading3: '#66d9ef'
		}
	};
	
	const theme = isDarkTheme ? colors.dark : colors.light;
	
	const swapInfo = swapEnabled ? `
			<div style="padding: 12px; background-color: ${isDarkTheme ? 'rgba(255, 193, 7, 0.1)' : '#fff9e6'}; border-left: 3px solid ${theme.border2}; margin-top: 12px; border-radius: 3px;">
				<p style="margin: 0 0 8px 0; color: ${theme.text}; line-height: 1.6;">
					<strong style="color: ${theme.heading2};">Swap Hours worked and Actual Working Hours:</strong> Enabled
				</p>
				<p style="margin-bottom: 6px; color: ${theme.text}; line-height: 1.6; font-size: 13px;">
					When swap is enabled, the system swaps the meaning of these fields:
				</p>
				<ul style="margin: 6px 0 0 0; padding-left: 20px; color: ${theme.text}; line-height: 1.6; font-size: 13px;">
					<li><strong>Hours Worked</strong> = Time span from first check-in to last checkout (including breaks)</li>
					<li><strong>Actual Working Hours</strong> = Sum of work periods (excluding breaks) - Break Hours</li>
				</ul>
				<p style="margin: 8px 0 0 0; color: ${theme.textSecondary}; font-size: 12px; line-height: 1.5;">
					<strong>Note:</strong> This is useful when you want "Hours Worked" to represent the total time span at work, and "Actual Working Hours" to represent only productive work time.
				</p>
			</div>
		` : `
			<div style="padding: 12px; background-color: ${isDarkTheme ? 'rgba(108, 117, 125, 0.1)' : '#f8f9fa'}; border-left: 3px solid ${isDarkTheme ? '#6c757d' : '#6c757d'}; margin-top: 12px; border-radius: 3px;">
				<p style="margin: 0 0 8px 0; color: ${theme.text}; line-height: 1.6;">
					<strong>Swap Hours worked and Actual Working Hours:</strong> Disabled
				</p>
				<p style="margin-bottom: 6px; color: ${theme.text}; line-height: 1.6; font-size: 13px;">
					When swap is disabled (default behavior):
				</p>
				<ul style="margin: 6px 0 0 0; padding-left: 20px; color: ${theme.text}; line-height: 1.6; font-size: 13px;">
					<li><strong>Hours Worked</strong> = Sum of work periods (excluding breaks)</li>
					<li><strong>Actual Working Hours</strong> = Hours Worked - Break Hours</li>
				</ul>
			</div>
		`;

	const logicContent = {
		"Break Hours from Employee Checkins": `
			<div style="padding: 15px; background-color: ${theme.bg1}; border-left: 4px solid ${theme.border1}; margin: 10px 0; border-radius: 4px;">
				<h4 style="margin-top: 0; color: ${theme.heading1}; font-size: 14px; font-weight: 600;">Break Hours from Employee Checkins</h4>
				<p style="margin-bottom: 8px; color: ${theme.text}; line-height: 1.6;">
					<strong>Logic:</strong> Uses the actual break time calculated from time gaps between consecutive checkouts and checkins.
				</p>
				<p style="margin-bottom: 8px; color: ${theme.text}; line-height: 1.6;">
					<strong>Calculation:</strong> The system sums all time differences between each clockout and the next clockin to determine total break hours.
				</p>
				<p style="margin-bottom: 0; color: ${theme.textSecondary}; font-size: 12px; line-height: 1.5;">
					<strong>Example:</strong> If an employee clocks out at 12:00 and clocks in at 13:00, the break time is 1 hour. All such gaps throughout the day are summed.
				</p>
				${swapInfo}
			</div>
		`,
		"Break Hours from Weekly Working Hours": `
			<div style="padding: 15px; background-color: ${theme.bg2}; border-left: 4px solid ${theme.border2}; margin: 10px 0; border-radius: 4px;">
				<h4 style="margin-top: 0; color: ${theme.heading2}; font-size: 14px; font-weight: 600;">Break Hours from Weekly Working Hours</h4>
				<p style="margin-bottom: 8px; color: ${theme.text}; line-height: 1.6;">
					<strong>Logic:</strong> Uses the predefined break time configured in Weekly Working Hours.
				</p>
				<p style="margin-bottom: 8px; color: ${theme.text}; line-height: 1.6;">
					<strong>Calculation:</strong> The break hours are taken directly from the Weekly Working Hours configuration (break_minutes converted to hours). This is a fixed value regardless of actual checkin patterns.
				</p>
				<p style="margin-bottom: 0; color: ${theme.textSecondary}; font-size: 12px; line-height: 1.5;">
					<strong>Note:</strong> The actual break time from checkins is ignored. The system always uses the configured break time from Weekly Working Hours.
				</p>
			</div>
		`,
		"Break Hours from Weekly Working Hours if Shorter breaks": `
			<div style="padding: 15px; background-color: ${theme.bg3}; border-left: 4px solid ${theme.border3}; margin: 10px 0; border-radius: 4px;">
				<h4 style="margin-top: 0; color: ${theme.heading3}; font-size: 14px; font-weight: 600;">Break Hours from Weekly Working Hours if Shorter breaks</h4>
				<p style="margin-bottom: 8px; color: ${theme.text}; line-height: 1.6;">
					<strong>Logic:</strong> Compares the actual break time from checkins with the default break hours from Weekly Working Hours.
				</p>
				<p style="margin-bottom: 8px; color: ${theme.text}; line-height: 1.6;">
					<strong>Calculation:</strong>
					<ul style="margin: 8px 0; padding-left: 20px; color: ${theme.text}; line-height: 1.6;">
						<li>If actual break from checkins ≤ default break hours: Uses default break hours from Weekly Working Hours</li>
						<li>If actual break from checkins > default break hours: Uses the actual break time from checkins</li>
					</ul>
				</p>
				<p style="margin-bottom: 0; color: ${theme.textSecondary}; font-size: 12px; line-height: 1.5;">
					<strong>Example:</strong> If default break is 0.5 hours (30 min) but employee took 1 hour break, the system uses 1 hour. If employee took only 0.25 hours break, the system uses 0.5 hours (default).
				</p>
			</div>
		`
	};

	const defaultMsg = `<div style="padding: 15px; color: ${theme.textSecondary};">Please select a break calculation mechanism to see the logic explanation.</div>`;
	return logicContent[mechanism] || defaultMsg;
}

function update_break_calculation_logic(frm) {
	const mechanism = frm.doc.workday_break_calculation_mechanism;
	const swapEnabled = mechanism === "Break Hours from Employee Checkins" && frm.doc.swap_hours_worked_and_actual_working_hours;
	const htmlContent = get_break_calculation_logic_html(mechanism, swapEnabled);
	
	// Update the HTML field
	const htmlField = frm.fields_dict.workday_break_calculation_logic;
	if (htmlField && htmlField.$wrapper) {
		htmlField.$wrapper.html(htmlContent);
	}
}