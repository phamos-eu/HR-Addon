
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, get_time, getdate, nowtime
from hr_addon.events.overtime_ledger import get_employee_overtime_balance


class OvertimePayout(Document):
	"""
	Overtime Pay-out document following ERPNext Stock Entry pattern
	Creates Overtime Ledger Entries similar to Stock Entry → Stock Ledger Entry
	"""
	
	def validate(self):
		"""Validate before save"""
		self.validate_hours()
		self.set_posting_time()
		
	def get_hours_in_hours(self):
		"""Return duration field (stored in seconds) as decimal hours for ledger calculations."""
		seconds = cint(self.hours) or 0
		return flt(seconds / 3600.0, precision=2)

	def validate_hours(self):
		"""Validate hours field based on purpose. Duration field stores value in seconds."""
		if self.hours is None or self.hours == "":
			frappe.throw(_("Hours is mandatory"))
		if self.get_hours_in_hours() <= 0:
			frappe.throw(_("Hours must be greater than zero"))
	
	def set_posting_time(self):
		"""Set posting time if not set"""
		if not self.posting_time:
			self.posting_time = nowtime()
	
	def on_submit(self):
		"""
		On submit: Create Overtime Ledger Entry
		Following Stock Entry pattern
		"""
		self.update_overtime_ledger()
		self._update_overtime_balance_after_submit()

	def on_update_after_submit(self):
		self._update_overtime_balance_after_submit()

	def _update_overtime_balance_after_submit(self):
		"""Refresh and persist overtime_balance_after_submit (after OLE is created/updated)."""
		# Use balance from the OLE created for this voucher to avoid timing/timezone issues
		# (get_employee_overtime_balance uses now() and can miss the new entry)
		oles = frappe.get_all(
			"Overtime Ledger Entry",
			filters={
				"voucher_type": self.doctype,
				"voucher_no": self.name,
				"is_cancelled": 0,
			},
			fields=["balance_after"],
			order_by="creation desc",
			limit=1,
		)
		if oles and oles[0].balance_after is not None:
			new_balance_hours = flt(oles[0].balance_after)
		else:
			balance_info = get_employee_overtime_balance(self.employee)
			new_balance_hours = balance_info.get("balance", 0.0)
		# Duration field stores seconds; convert hours to seconds for display (e.g. 0.98 -> "0h 59m")
		new_balance_seconds = int(round(new_balance_hours * 3600))
		self.db_set("overtime_balance_after_submit", new_balance_seconds, update_modified=False)
		frappe.db.commit()

	
	def on_cancel(self):
		"""
		On cancel: Create reversal OLE
		Following Stock Entry pattern
		"""
		frappe.logger().debug(f"OvertimePayout.on_cancel() called for {self.name}, docstatus={self.docstatus}")
		
		# Ignore Overtime Ledger Entry links (similar to Stock Entry ignoring Stock Ledger Entry)
		# This allows cancellation even when linked to OLE
		self.ignore_linked_doctypes = ("Overtime Ledger Entry",)
		
		# Create reversal entry
		self.update_overtime_ledger()
		
		frappe.logger().debug(f"OvertimePayout.on_cancel() completed for {self.name}")
		
	
	def update_overtime_ledger(self):
		"""
		Create/Cancel Overtime Ledger Entries
		Following Stock Entry.update_stock_ledger() pattern
		"""
		# Build list of OLE entries (similar to sl_entries in Stock Entry)
		ole_entries = []
		
		# Get the OLE entry dict
		ole_entry = self.get_ole_entry()
		ole_entries.append(ole_entry)
		
		# Make OLE entries (similar to make_sl_entries)
		self.make_ole_entries(ole_entries)
	
	def get_ole_entry(self):
		"""
		Build OLE entry dict
		Following StockController.get_sl_entries() pattern
		"""
		from frappe.utils import add_to_date, get_time
		from datetime import datetime, timedelta
		
		# Duration field stores seconds; convert to hours for ledger (hour_variance is in hours)
		hours_in_hours = self.get_hours_in_hours()
		# Pay-out and Negative Adjustment → negative OLE (reduce balance); Positive Adjustment → positive OLE (increase balance)
		if self.purpose in ("Pay-out", "Negative Adjustment"):
			hour_variance = -1 * abs(hours_in_hours)
		else:  # Positive Adjustment
			hour_variance = hours_in_hours
		
		# Reverse if cancelling (docstatus == 2)
		if self.docstatus == 2:
			hour_variance = -1 * hour_variance
		
		# For reversal entries, add 1 second to posting_time to ensure proper ordering
		posting_time = self.posting_time
		if self.docstatus == 2:
			# Parse the time and add 1 second
			time_obj = get_time(self.posting_time)
			# Convert to datetime, add 1 second, convert back to time
			dt = datetime.combine(datetime.today(), time_obj)
			dt = dt + timedelta(seconds=1)
			posting_time = dt.time().strftime("%H:%M:%S")
		
		
		
		# Build OLE dict (similar to sl_dict in StockController)
		ole_dict = frappe._dict({
			"doctype": "Overtime Ledger Entry",
			"employee": self.employee,
			"posting_date": self.posting_date,
			"posting_time": posting_time,
			"voucher_type": self.doctype,
			"voucher_no": self.name,
			"hour_variance": hour_variance,
			"remarks": self.comment or f"{self.purpose}: {abs(flt(hour_variance, precision=2))} hours",
			# Set is_cancelled=1 when docstatus==2 to trigger cancellation logic
			# The reversal entry created will have is_cancelled=0 (active)
			"is_cancelled": 1 if self.docstatus == 2 else 0
		})
		
		return ole_dict
	
	def make_ole_entries(self, ole_entries):
		"""
		Create Overtime Ledger Entries
		Following make_sl_entries() pattern from stock_ledger.py
		"""
		from hr_addon.hr_addon.doctype.overtime_ledger_entry.overtime_ledger_entry import (
			make_ole_entry, 
			set_ole_as_cancel
		)
		
		if not ole_entries:
			return
		
		cancel = ole_entries[0].get("is_cancelled")
		frappe.logger().debug(f"make_ole_entries: cancel={cancel}, docstatus={self.docstatus}, entries={len(ole_entries)}")
		
		if cancel:
			# CANCELLATION PATH: Create reversal with explicit balances, then cancel original
			# Find original active OLEs
			original_oles = frappe.get_all(
				"Overtime Ledger Entry",
				filters={
					"voucher_type": self.doctype,
					"voucher_no": self.name,
					"is_cancelled": 0
				},
				fields=["name", "balance_before", "balance_after", "hour_variance"]
			)

			# Create reversal with EXPLICIT balances that exactly reverse the original
			# The hour_variance is already reversed in get_ole_entry() when docstatus==2
			for i, ole in enumerate(ole_entries):
				# Ensure reversal payload has no is_cancelled flag
				ole.pop("is_cancelled", None)
				
				# Set explicit balances to reverse the original entry
				if i < len(original_oles):
					ole["balance_before"] = original_oles[i].balance_after
					ole["balance_after"] = original_oles[i].balance_before
				
				ole_doc = make_ole_entry(ole)
				frappe.msgprint(
					_("Reversal Overtime Ledger Entry {0} created to cancel {1}").format(
						ole_doc.name, self.name
					),
					alert=True,
					indicator="red"
				)
			
			# NOW cancel the original OLEs after creating reversals
			for o in original_oles:
				frappe.db.set_value("Overtime Ledger Entry", o.name, "is_cancelled", 1, update_modified=True)
			frappe.db.commit()
			
			# Note: Reposting is automatically triggered by after_insert hook on the reversal entry
			# if there are future entries that need recalculation
		else:
			# NORMAL SUBMISSION PATH
			# Check if OLE already exists for this voucher (prevent duplicates)
			existing_ole = frappe.db.exists("Overtime Ledger Entry", {
				"voucher_type": self.doctype,
				"voucher_no": self.name,
				"is_cancelled": 0
			})
			
			if existing_ole:
				frappe.msgprint(
					_("Overtime Ledger Entry already exists: {0}").format(existing_ole),
					alert=True,
					indicator="orange"
				)
				return
			
			# Create new OLE entries
			for ole in ole_entries:
				ole_doc = make_ole_entry(ole)
				
				# Show message
				action = "reduced" if self.purpose in ("Pay-out", "Negative Adjustment") else "increased"
				frappe.msgprint(
					_("Overtime Ledger Entry {0} created. Balance {1} by {2} hours").format(
						ole_doc.name, action, abs(ole["hour_variance"])
					),
					alert=True,
					indicator="green"
				)
