// Copyright (c) 2025, Akhilaminc and contributors
// For license information, please see license.txt
const get_last_day_of_month = (date_str) => {
	const date = frappe.datetime.str_to_obj(date_str);
	const year = date.getFullYear();
	const month = date.getMonth();
	return frappe.datetime.obj_to_str(new Date(year, month + 1, 0));
};

const get_current_month_range = () => {
	const today = frappe.datetime.get_today();
	const today_obj = frappe.datetime.str_to_obj(today);
	const first_day_obj = new Date(today_obj.getFullYear(), today_obj.getMonth(), 1);
	const first_day = frappe.datetime.obj_to_str(first_day_obj);
	const last_day = get_last_day_of_month(today);
	return { first_day, last_day };
};

const sync_date_range = () => {
	const from_date = frappe.query_report.get_filter_value("from_date");
	const to_date = frappe.query_report.get_filter_value("to_date");

	if (!from_date) {
		frappe.query_report.set_filter_value("from_date", first_day);
		frappe.query_report.set_filter_value("to_date", last_day);
		return;
	}

	const from_date_obj = frappe.datetime.str_to_obj(from_date);
	if (!from_date_obj) {
		frappe.query_report.refresh();
		return;
	}

	const updated_to_date = get_last_day_of_month(from_date);
	if (updated_to_date !== to_date) {
		frappe.query_report.set_filter_value("to_date", updated_to_date);
		return;
	}

	frappe.query_report.refresh();
};

const refresh_report = () => {
	frappe.query_report.refresh();
};

const { first_day, last_day } = get_current_month_range();

frappe.query_reports["Overtime Ledger"] = {
	"filters": [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: first_day,
			reqd: 1,
			on_change: sync_date_range
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: last_day,
			reqd: 1,
			on_change: refresh_report
		},
		{
			fieldname: "employee",
			label: __("Employees"),
			fieldtype: "MultiSelectList",
			options: "Employee",
			"get_data": async function(txt) {
				const filters = window.overtime_ledger_employee_filters || [["Employee", "status", "=", "Active"]];
				const response = await frappe.call({
					method: "frappe.desk.search.search_link",
					args: {
						doctype: "Employee",
						txt: txt,
						filters: filters,
						page_length: 20
					}
				});
				const data = response.message || [];
				return data.map(item => ({
					value: item.value,
					description: item.description
				}));
			},
		},
		{
			fieldname: "show_cancelled_entries",
			label: __("Show Cancelled Entries"),
			fieldtype: "Check",
			default: 0,
		},
		{
			fieldname: "specific_date",
			label: __("Specific Date"),
			fieldtype: "Check",
			default: 0,
		},
		{
			fieldname: "range_delta",
			label: __("Range Delta"),
			fieldtype: "Check",
			default: 0,
		},
		{
			fieldname: "show_time_in_decimal",
			label: __("Show Time in Decimal"),
			fieldtype: "Check",
			default: 0,
		}
	],
	onload: function(report) {
		// Page class for dual datatable styles
		setTimeout(function () {
			if (report && report.page && report.page.main) {
				const page_form = report.page.main.find(".page-form");
				if (page_form && page_form.length) {
					report.page.main.addClass("overtime-ledger-page");
				}
			}
		}, 300);

		window.overtime_ledger_employee_filters = [["Employee", "status", "=", "Active"]];
		const employee_filter = report.get_filter("employee");
		if (employee_filter) {
			employee_filter.refresh();
		}

		// Handle specific_date checkbox change
		const specific_date_filter = report.get_filter("specific_date");
		const range_delta_filter = report.get_filter("range_delta");
		const to_date_filter = report.get_filter("to_date");
		
		if (specific_date_filter && to_date_filter) {
			specific_date_filter.$input.on("change", function() {
				const is_checked = $(this).is(":checked");
				if (is_checked) {
					// When checked, uncheck range_delta if it's checked
					if (range_delta_filter && range_delta_filter.get_value()) {
						range_delta_filter.set_value(0);
					}
					// Set to_date to same as from_date and disable it
					const from_date_filter = report.get_filter("from_date");
					if (from_date_filter) {
						to_date_filter.set_value(from_date_filter.get_value());
					}
					to_date_filter.df.hidden = 1;
					to_date_filter.refresh();
				} else {
					// When unchecked, enable to_date field
					to_date_filter.df.hidden = 0;
					to_date_filter.refresh();
				}
			});

			// Set initial state
			if (specific_date_filter.get_value()) {
				const from_date_filter = report.get_filter("from_date");
				if (from_date_filter) {
					to_date_filter.set_value(from_date_filter.get_value());
				}
				to_date_filter.df.hidden = 1;
				to_date_filter.refresh();
			}
		}

		// Handle range_delta checkbox change
		if (range_delta_filter && specific_date_filter) {
			range_delta_filter.$input.on("change", function() {
				const is_checked = $(this).is(":checked");
				if (is_checked) {
					// When checked, uncheck specific_date if it's checked
					if (specific_date_filter.get_value()) {
						specific_date_filter.set_value(0);
					}
					// Ensure to_date is visible for range delta
					if (to_date_filter) {
						to_date_filter.df.hidden = 0;
						to_date_filter.refresh();
					}
				}
			});
		}
	},
	
	formatter: function (value, row, column, data, default_formatter) {
		if (column.fieldname === "employee") {
			const name = (data && data.employee_name) || value || "";
			return name;
		}

		value = default_formatter(value, row, column, data);

		const showDecimal = frappe.query_report.get_filter_value("show_time_in_decimal") || 0;
		const is_reversal = data && data.remarks && data.remarks.includes("Reversal of");
		const is_cancelled_or_reversal =
			data && (cint(data.voucher_docstatus) == 2 || cint(data.is_cancelled) == 1 || is_reversal);
		const formatDecimalHours = (rawValue) => {
			const parsed = parseFloat(rawValue);
			if (rawValue == null || rawValue === "" || Number.isNaN(parsed)) {
				return "";
			}
			return parsed.toFixed(2);
		};

		// Convert hours to h:m format for time columns
		if (column.fieldname == "in_hour" || column.fieldname == "out_hour") {
			value = showDecimal ? formatDecimalHours(value) : convertHoursToHM(value);
		}
		if (column.fieldname == "target_hours" || column.fieldname == "actual_hours") {
			value = showDecimal ? formatDecimalHours(value) : convertHoursToHM(value);
		}

		// Column-specific formatting first
		if (column.fieldname == "out_hour" && data && data.out_hour < 0) {
			value = "<span style='color:red'>" + value + "</span>";
		} else if (column.fieldname == "in_hour" && data && data.in_hour > 0) {
			value = "<span style='color:green'>" + value + "</span>";
		} else if (column.fieldname == "balance_after") {
			const raw = data && data.balance_after != null ? parseFloat(data.balance_after) : null;
			if (raw == null || Number.isNaN(raw)) {
				value = "";
			} else {
				value = showDecimal ? formatDecimalHours(raw) : convertHoursToHM(raw);
				if (raw < 0) {
					value = "<span style='color:red'>" + value + "</span>";
				} else if (raw > 0) {
					value = "<span style='color:blue'>" + value + "</span>";
				}
			}
		} else if (column.fieldname == "delta") {
			if (data && data.delta != null && data.delta !== undefined) {
				const raw = parseFloat(data.delta);
				if (Number.isNaN(raw)) {
					value = "";
				} else {
					value = showDecimal ? formatDecimalHours(raw) : convertHoursToHM(raw);
					if (raw < 0) {
						value = "<span style='color:red'>" + value + "</span>";
					} else if (raw > 0) {
						value = "<span style='color:green'>" + value + "</span>";
					}
				}
			} else {
				value = "";
			}
		} else if (
			column.fieldname === "voucher_no" &&
			data &&
			data.voucher_type &&
			data.voucher_no
		) {
			value = frappe.utils.get_form_link(data.voucher_type, data.voucher_no, true);
		}

		// Apply cancelled/reversal styling at the end so formatted value is preserved
		if (is_cancelled_or_reversal) {
			value = "<span style='color:#888'>" + value + "</span>";
		}

		return value;
	},


	get_datatable_options(options) {
		return Object.assign(options || {}, {
			checkboxColumn: false,
			layout: "fixed",
			cellHeight: 36,
			dynamicRowHeight: true,
			inlineFilters: true,
		});
	},

	// Same dual-table pattern as Suncycle Work Hours: fixed serial + posting time + employee; scroll the rest.
	after_datatable_render: function (datatable) {
		const minPostingTime = 180;
		const minEmployee = 240;
		const fixedPaneWidth = minPostingTime + minEmployee;

		if (!$("#ole-col-styles").length) {
			$("<style id='ole-col-styles'>")
				.text(
					".overtime-ledger-page .dt-cell[data-fieldname=\"posting_datetime\"], .overtime-ledger-page .dt-header[data-fieldname=\"posting_datetime\"] { min-width: " +
						minPostingTime +
						"px !important; }\n" +
						".overtime-ledger-page .dt-cell[data-fieldname=\"employee\"], .overtime-ledger-page .dt-header[data-fieldname=\"employee\"] { min-width: " +
						minEmployee +
						"px !important; }\n" +
						".ole-data-table .dt-cell__content--col-0, .ole-data-table .dt-cell__content--header-0 { display: none !important; }\n" +
						".ole-data-table .dt-cell__content--col-1, .ole-data-table .dt-cell__content--header-1 { display: none !important; }\n" +
						".ole-data-table .dt-cell__content--col-2, .ole-data-table .dt-cell__content--header-2 { display: none !important; }\n" +
						".ole-data-table .dt-row .dt-cell:nth-child(1), .ole-data-table .dt-header-row .dt-header:nth-child(1), .ole-data-table .dt-head .dt-header:nth-child(1) { display: none !important; }\n" +
						".ole-data-table .dt-row .dt-cell:nth-child(2), .ole-data-table .dt-header-row .dt-header:nth-child(2), .ole-data-table .dt-head .dt-header:nth-child(2) { display: none !important; }\n" +
						".ole-data-table .dt-row .dt-cell:nth-child(3), .ole-data-table .dt-header-row .dt-header:nth-child(3), .ole-data-table .dt-head .dt-header:nth-child(3) { display: none !important; }\n"
				)
				.appendTo("head");
		}

		// min-width: 0 / flex-basis on the scroll pane is required so columns to the right actually scroll (flex default min-width: auto).
		if (!$("#ole-dual-table-styles-v2").length) {
			$("<style id='ole-dual-table-styles-v2'>")
				.text(
					".ole-tables-container { display: flex; overflow: hidden; width: 100%; min-width: 0; }\n" +
						".ole-fixed-table { flex: 0 0 " +
						fixedPaneWidth +
						"px; width: " +
						fixedPaneWidth +
						"px; overflow: hidden; border-right: 1px solid var(--table-border-color); }\n" +
						".ole-data-table { flex: 1 1 0%; min-width: 0; max-width: 100%; overflow-x: auto; overflow-y: visible; }\n" +
						".ole-data-table > .datatable { max-width: 100%; }\n" +
						".ole-data-table .dt-scrollable { overflow-x: auto !important; overflow-y: visible !important; }\n" +
						".ole-fixed-table .dt-scrollable { overflow: hidden !important; }\n" +
						".ole-fixed-table .dt-header { overflow: hidden !important; }\n" +
						".ole-fixed-table .dt-cell, .ole-fixed-table .dt-header { border-right: none !important; }"
				)
				.appendTo("head");
		}

		let $container = $(".ole-tables-container");
		let $mainTable;

		if ($container.length) {
			$mainTable = $container.find(".ole-data-table .datatable").first();
			if (!$mainTable.length) {
				$mainTable = $container.find(".datatable").first();
			}
			if (!$mainTable.length) {
				return;
			}
			$container.find(".ole-fixed-table").remove();
		} else {
			$mainTable = $(".datatable").first();
			if (!$mainTable.length) {
				return;
			}
			$mainTable.wrap('<div class="ole-data-table"></div>');
			$container = $mainTable.parent().wrap('<div class="ole-tables-container"></div>').parent();
		}

		const $fixedTable = $mainTable.clone();
		function keepFixedColumns($table) {
			$table.find(".dt-row").each(function () {
				const $cells = $(this).children(".dt-cell");
				$cells.each(function (idx) {
					if (idx !== 0 && idx !== 1 && idx !== 2) {
						$(this).remove();
					}
				});
			});
			$table.find(".dt-header-row, .dt-head").each(function () {
				const $headers = $(this).children(".dt-header");
				$headers.each(function (idx) {
					if (idx !== 0 && idx !== 1 && idx !== 2) {
						$(this).remove();
					}
				});
			});
		}
		keepFixedColumns($fixedTable);

		$fixedTable.wrap('<div class="ole-fixed-table"></div>');
		$container.prepend($fixedTable.parent());

		const $fixedScrollable = $fixedTable.find(".dt-scrollable");
		const $dataScrollable = $mainTable.find(".dt-scrollable");
		$dataScrollable.css({ "overflow-x": "auto", "overflow-y": "visible" });
		$dataScrollable.off("scroll.ole").on("scroll.ole", function () {
			$fixedScrollable.scrollTop($dataScrollable.scrollTop());
		});

		function syncFixedTableWithMain() {
			const $mainScrollable = $mainTable.find(".dt-scrollable");
			const $fixScrollable = $fixedTable.find(".dt-scrollable");
			const $mainRows = $mainScrollable.find(".dt-row").filter(function () {
				return !$(this).hasClass("dt-row-header") && !$(this).hasClass("dt-row-filter");
			});
			if ($mainScrollable.find(".dt-scrollable__no-data, .no-data-message").length) {
				$fixScrollable.find(".dt-row").filter(function () {
					return !$(this).hasClass("dt-row-header") && !$(this).hasClass("dt-row-filter");
				}).remove();
				return;
			}
			const $newRows = [];
			$mainRows.each(function () {
				const $mainRow = $(this).clone();
				$mainRow.find(".dt-cell").each(function (idx) {
					if (idx !== 0 && idx !== 1 && idx !== 2) {
						$(this).remove();
					}
				});
				$newRows.push($mainRow[0]);
			});
			const $fixDataRows = $fixScrollable.find(".dt-row").filter(function () {
				return !$(this).hasClass("dt-row-header") && !$(this).hasClass("dt-row-filter");
			});
			const $fixContainer = $fixDataRows.length ? $fixDataRows.first().parent() : $fixScrollable;
			$fixDataRows.remove();
			$newRows.forEach(function (el) {
				$fixContainer.append(el);
			});
			$fixedScrollable.scrollTop($dataScrollable.scrollTop());
			[1, 2].forEach(function (colIdx) {
				const mainVal = $mainTable.find(".dt-cell--col-" + colIdx + " .dt-filter").val() || "";
				const $parentFilter = $fixedTable.find(".dt-cell--col-" + colIdx + " .dt-filter");
				if ($parentFilter.val() !== mainVal) {
					$parentFilter.val(mainVal);
				}
			});
		}

		const debouncedSync = frappe.utils.debounce(syncFixedTableWithMain, 80);
		if ($dataScrollable[0]) {
			const obs = new MutationObserver(function () {
				debouncedSync();
			});
			obs.observe($dataScrollable[0], { childList: true, subtree: true });
		}
		const origApplyFilter = datatable.columnmanager.applyFilter.bind(datatable.columnmanager);
		datatable.columnmanager.applyFilter = function (filters) {
			origApplyFilter(filters);
			setTimeout(debouncedSync, 150);
		};
		[1, 2].forEach(function (colIdx) {
			const $parentFilter = $fixedTable.find(".dt-cell--col-" + colIdx + " .dt-filter");
			const $mainFilter = $mainTable.find(".dt-cell--col-" + colIdx + " .dt-filter");
			const applyParentToMain = frappe.utils.debounce(function () {
				$mainFilter.val($parentFilter.val() || "");
				datatable.columnmanager.applyFilter(datatable.columnmanager.getAppliedFilters());
			}, 300);
			$parentFilter.off("input.ole keydown.ole").on("input.ole keydown.ole", applyParentToMain);
		});

		setTimeout(syncFixedTableWithMain, 0);
	},
};

// Helper function to convert decimal hours to "Xh Ym" format (similar to hitt function in Work Hour Report)
function convertHoursToHM(hours) {
	if (hours == 0 || hours == null) return "0h";
	
	// Handle negative values
	let isNegative = hours < 0;
	hours = Math.abs(hours);
	
	// Calculate hours and minutes
	let h = Math.floor(hours);
	let m = Math.round((hours - h) * 60);
	
	// Format output
	let hDisplay = h > 0 ? h + "h " : "";
	let mDisplay = m > 0 ? m + "m" : "";
	let result = (hDisplay + mDisplay).trim();
	
	// Add negative sign if needed
	if (isNegative) {
		result = "-" + result;
	}
	
	return result || "0h";
}