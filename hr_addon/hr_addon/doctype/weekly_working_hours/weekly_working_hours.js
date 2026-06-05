// Copyright (c) 2022, phamos.eu and contributors
// For license information, please see license.txt

const MECHANISM_MINIMUM_BREAK_RULE = 'Break Hours from Minimum Break Rule';
const BREAK_MINUTES_HIDE_STYLE_ID = 'wwh-hide-break-minutes-style';

function ensure_break_minutes_hide_style() {
	if (document.getElementById(BREAK_MINUTES_HIDE_STYLE_ID)) {
		return;
	}

	const style = document.createElement('style');
	style.id = BREAK_MINUTES_HIDE_STYLE_ID;
	style.textContent = `
		.weekly-working-hours-hide-break-minutes .grid-heading-row [data-fieldname="break_minutes"],
		.weekly-working-hours-hide-break-minutes .grid-row [data-fieldname="break_minutes"],
		.weekly-working-hours-hide-break-minutes .grid-row-open [data-fieldname="break_minutes"] {
			display: none !important;
		}
	`;
	document.head.appendChild(style);
}

function update_break_minutes_docfield(frm, hidden) {
	// Child table column: fieldname, property, value, parent_docname, child_fieldname
	frm.set_df_property('hours', 'hidden', hidden, frm.docname, 'break_minutes');

	const child_df = frappe.meta.get_docfield(
		'Daily Hours Detail',
		'break_minutes',
		frm.docname
	);
	if (child_df) {
		child_df.hidden = hidden;
	}
}

function refresh_hours_grid_columns(frm, hide) {
	const hidden = hide ? 1 : 0;
	const grid = frm.fields_dict.hours?.grid;
	if (!grid) {
		return false;
	}

	update_break_minutes_docfield(frm, hidden);

	const df = grid.get_docfield('break_minutes');
	if (df) {
		df.hidden = hidden;
	}

	grid.docfields?.forEach((docfield) => {
		if (docfield.fieldname === 'break_minutes') {
			docfield.hidden = hidden;
		}
	});

	if (grid.user_defined_columns?.length) {
		grid.user_defined_columns = grid.user_defined_columns.filter(
			(column) => column.fieldname !== 'break_minutes' || !hide
		);
	}

	ensure_break_minutes_hide_style();
	frm.fields_dict.hours.$wrapper
		.closest('.frappe-control')
		.toggleClass('weekly-working-hours-hide-break-minutes', hide);

	// Frappe caches visible_columns; clearing it is required to rebuild the header row.
	grid.visible_columns = [];
	grid.refresh();
	return true;
}

function set_break_minutes_column_visibility(frm, hide) {
	frm.set_df_property('no_break_hours', 'read_only', hide ? 1 : 0);
	update_break_minutes_docfield(frm, hide ? 1 : 0);

	const apply_to_grid = () => refresh_hours_grid_columns(frm, hide);

	if (!apply_to_grid()) {
		let attempts = 0;
		const interval = setInterval(() => {
			attempts += 1;
			if (apply_to_grid() || attempts >= 30) {
				clearInterval(interval);
			}
		}, 100);
	}
}

function apply_hr_addon_weekly_form_settings(frm) {
	frappe.db
		.get_value(
			'HR Addon Settings',
			'HR Addon Settings',
			'workday_break_calculation_mechanism'
		)
		.then((r) => {
			const hide =
				r.message?.workday_break_calculation_mechanism ===
				MECHANISM_MINIMUM_BREAK_RULE;
			set_break_minutes_column_visibility(frm, hide);
		});
}

frappe.ui.form.on('Weekly Working Hours', {
	setup(frm) {
		frm.check_days_for_duplicates = function (frm, row) {
			frm.doc.hours.forEach((tm) => {
				if (!(row.day == '' || tm.idx == row.idx)) {
					if (row.day == tm.day) {
						row.hours = '';
					}
				}
			});
		};

		frm.get_total_hours = function (frm) {
			let total_hour = 0;
			frm.doc.hours.forEach((tm) => {
				total_hour += flt(tm.hours);
			});
			frm.set_value('total_work_hours', total_hour);
		};

		frm.set_work_hour_in_seconds = function (frm) {
			$.each(frm.doc.hours || [], function (i, d) {
				d.hour_time = flt(d.hours) * 60 * 60;
			});
		};
	},
	onload(frm) {
		apply_hr_addon_weekly_form_settings(frm);
	},
	refresh(frm) {
		apply_hr_addon_weekly_form_settings(frm);
	},
});

frappe.ui.form.on('Daily Hours Detail', {
	hours(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		frm.set_work_hour_in_seconds(frm);
		frm.check_days_for_duplicates(frm, row);
		frm.get_total_hours(frm);
	},
	hours_remove(frm) {
		frm.get_total_hours(frm);
	},
	form_render(frm) {
		apply_hr_addon_weekly_form_settings(frm);
	},
});
