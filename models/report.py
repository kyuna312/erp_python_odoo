from datetime import datetime
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError
import requests, json
import logging
from odoo import tools

class payment_report_view(models.Model):
    def init(self):
        tools.drop_view_if_exists(self._cr, 'payment_report_view')
        self._cr.execute("""
            CREATE OR REPLACE VIEW payment_report_view AS (
                SELECT 
            )""")


