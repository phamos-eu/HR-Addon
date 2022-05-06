// Copyright (c) 2022, Jide Olayinka and contributors
// For license information, please see license.txt

frappe.ui.form.on('Weekly Working Hours', {
	setup: function(frm){
		frm.check_days_for_duplicates = function(frm,row){
			frm.doc.hours.forEach(tm => {
				if(!( row.day =='' || tm.idx==row.idx)){
					if(row.day==tm.day){
						row.hours = '';	
						//console.log('Work hour already set for ');				
					}
					
				}
			});
		}

		frm.get_total_hours = function(frm){
			let total_hour = 0;
			let t_hour_time = 0;
			frm.doc.hours.forEach(tm=>{
				total_hour += flt(tm.hours);
				//in sec total
				t_hour_time += flt(tm.hour_time);
			})
			frm.set_value("total_work_hours",total_hour);
			// set total in seconds			
			frm.set_value("total_hours_time",t_hour_time);
		}

		frm.set_work_hour_in_seconds = function(frm,tm){
			$.each(frm.doc.hours|| [], function(i,d){
				d.hour_time = flt(d.hours)*60*60;
			});
			
		}
	}
	
	// refresh: function(frm) {

	// }
});

frappe.ui.form.on('Daily Hours Detail',{

	hours: function(frm, cdt, cdn){
		//set in time		
		let row = locals[cdt][cdn];
		frm.set_work_hour_in_seconds(frm);

		frm.check_days_for_duplicates(frm, row);
		frm.get_total_hours(frm);
		
		frm.refresh_field('hours');
		
	},
	
	hours_remove: function(frm,cdt,cdn){
		frm.get_total_hours(frm);
	}
});