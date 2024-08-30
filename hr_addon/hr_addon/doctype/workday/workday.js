// Copyright (c) 2022, Jide Olayinka and contributors
// For license information, please see license.txt

frappe.ui.form.on("Workday", {
  refresh: function (frm) {
    if (frm.doc.break_hours == -360 && frm.doc.hours_worked == -36) {
      $(".control-input-wrapper > .control-value.like-disabled-input").css(
        "color",
        "red"
      );
    } else {
      // Reset the color to default (or any other color) when the condition is not met
      $(".control-input-wrapper > .control-value.like-disabled-input").css(
        "color",
        ""
      );
    }
  },
  setup: function (frm) {
    frm.set_query("attendance", function () {
      return {
        filters: [
          ["Attendance", "employee", "=", frm.doc.employee],
          ["Attendance", "attendance_date", "=", frm.doc.log_date],
        ],
      };
    });
    /* frm.set_query('Employee Checkins','employee_checkins', function(){
			return{
				'filters':[
					['employee_checkins','employee_checkin','=',frm.doc.attendance]
					
				],
			};
		}); */
  },
  /* onload: function(frm){
		frm.set_query('Employee Checkins','employee_checkins', function(){
			return{
				'filters':{
					'employee_checkin':['=',frm.attendance]
				}
			};
		});
	}, */

  attendance: function (frm) {
    get_hours(frm);
  },

  log_date: function (frm) {
    if (frm.doc.employee && frm.doc.log_date) {
      frappe.call({
        method: "hr_addon.hr_addon.api.utils.date_is_in_holiday_list",
        args: {
          employee: frm.doc.employee,
          date: frm.doc.log_date,
        },
        callback: function (r) {
          if (r.message == true) {
            frappe.msgprint("Given Date is Holiday");
            unset_fields(frm);
          } else {
            get_hours(frm);
          }
        },
      });
    }
  },

  status(frm) {
    if (frm.doc.status === "On Leave") {
      setTimeout(() => {
        frm.set_value("target_hours", 0);
        frm.set_value("expected_break_hours", 0);
        frm.set_value("actual_working_hours", 0);
        frm.set_value("total_target_seconds", 0);
        frm.set_value("total_break_seconds", 0);
        frm.set_value("total_work_seconds", 0);
      }, 1000);
    } // TODO: consider case of frm.doc.status === "Half Day"
  },
});

var get_hours = function (frm) {
  let aemployee = frm.doc.employee;
  let adate = frm.doc.log_date;
  if (aemployee && adate) {
    frappe
      .call({
        method: "hr_addon.hr_addon.api.utils.get_actual_employee_log",
        args: { aemployee: aemployee, adate: adate },
      })
      .done((r) => {
        if (r.message && Object.keys(r.message).length > 0) {
          frm.doc.employee_checkins = [];
          let alog = r.message;

          frm.set_value("hours_worked", alog.hours_worked);
          frm.set_value("break_hours", alog.break_hours);
          frm.set_value("total_work_seconds", alog.total_work_seconds);
          frm.set_value("total_break_seconds", alog.total_break_seconds);
          frm.set_value("target_hours", alog.target_hours);
          frm.set_value("expected_break_hours", alog.expected_break_hours);
          frm.set_value("total_target_seconds", alog.total_target_seconds);

          frm.set_value("actual_working_hours", alog.actual_working_hours);
          let employee_checkins = alog.employee_checkins;
          if (employee_checkins) {
            frm.set_value("first_checkin", employee_checkins[0].time);
            frm.set_value(
              "last_checkout",
              employee_checkins[employee_checkins.length - 1].time
            );
            $.each(employee_checkins, function (i, e) {
              let nw_checkins = frm.add_child("employee_checkins");
              nw_checkins.employee_checkin = e.name;
              nw_checkins.log_type = e.log_type;
              nw_checkins.log_time = e.time;
              nw_checkins.skip_auto_attendance = e.skip_auto_attendance;
              refresh_field("employee_checkins");
            });
          }
        } else {
          unset_fields(frm);
        }
      });
  }
};

var unset_fields = function (frm) {
  frm.set_value("hours_worked", 0);
  frm.set_value("break_hours", 0);
  frm.set_value("total_work_seconds", 0);
  frm.set_value("total_break_seconds", 0);
  frm.set_value("target_hours", 0);
  frm.set_value("total_target_seconds", 0);
  frm.set_value("expected_break_hours", 0);
  frm.set_value("actual_working_hours", 0);
  frm.set_value("employee_checkins", []);
  frm.set_value("first_checkin", "");
  frm.set_value("last_checkout", "");
  frm.refresh_fields();
};
