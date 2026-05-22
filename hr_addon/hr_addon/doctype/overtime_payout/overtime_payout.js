// Copyright (c) 2026, Akhilaminc and contributors
// For license information, please see license.txt

frappe.ui.form.on("Overtime Payout", {
    refresh(frm) {
        frm.trigger("update_overtime_preview");
    },
    employee(frm) {
        frm.trigger("fetch_current_overtime_balance");
    },
    purpose(frm) {
        frm.trigger("update_overtime_preview");
    },
    hours(frm) {
        frm.trigger("update_overtime_preview");
    },

    fetch_current_overtime_balance(frm) {
        if (frm.doc.employee) {
            frappe.call({
                method: "hr_addon.events.overtime_ledger.get_employee_overtime_balance",
                args: { employee: frm.doc.employee },
                callback: function (r) {
                    if (r.message) {
                        const balance_hours = typeof r.message === "object" && "balance" in r.message
                            ? parseFloat(r.message.balance) || 0
                            : parseFloat(r.message) || 0;
                        const balance_seconds = Math.round(balance_hours * 3600);
                        frm.set_value("current_overtime_balance", balance_seconds, null, true);
                        frm.refresh_field("current_overtime_balance");
                        frm.trigger("update_overtime_preview");
                    }
                }
            });
        } else {
            frm.set_value("current_overtime_balance", 0, null, true);
            frm.set_value("overtime_balance_after_submit", null, null, true);
            frm.refresh_field("current_overtime_balance");
            frm.refresh_field("overtime_balance_after_submit");
        }
    },

    update_overtime_preview(frm) {
        // Preview: Pay-out and Negative Adjustment → subtract hours (negative OLE); Positive Adjustment → add hours (positive OLE)
        const current_seconds = parseInt(frm.doc.current_overtime_balance, 10) || 0;
        const hours_seconds = parseInt(frm.doc.hours, 10) || 0;
        const purpose = frm.doc.purpose;

        let variance_seconds;
        if (purpose === "Pay-out" || purpose === "Negative Adjustment") {
            variance_seconds = -Math.abs(hours_seconds);
        } else if (purpose === "Positive Adjustment") {
            variance_seconds = hours_seconds;
        } else {
            frm.set_value("overtime_balance_after_submit", null, null, true);
            frm.refresh_field("overtime_balance_after_submit");
            return;
        }

        const preview_seconds = current_seconds + variance_seconds;
        frm.set_value("overtime_balance_after_submit", preview_seconds, null, true);
        frm.refresh_field("overtime_balance_after_submit");
    }
});
