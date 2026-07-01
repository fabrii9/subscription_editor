# -*- coding: utf-8 -*-

from odoo import api, fields, models

from odoo.addons.sale_subscription.models.sale_order import SUBSCRIPTION_PROGRESS_STATE


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    can_edit_subscription_line = fields.Boolean(
        string="Puede editar línea de suscripción",
        compute="_compute_can_edit_subscription_line",
    )

    @api.depends("product_id", "state", "order_id.locked", "qty_invoiced", "qty_delivered", "is_downpayment")
    def _compute_can_edit_subscription_line(self):
        for line in self:
            order = line.order_id
            line.can_edit_subscription_line = bool(
                order.is_subscription
                and order.subscription_state in SUBSCRIPTION_PROGRESS_STATE
                and order.state == "sale"
                and line.env.user.has_group("subscription_editor.group_subscription_editor")
                and not line.is_downpayment
                and not order.locked
                and line.qty_delivered <= 0
                and line.qty_invoiced <= 0
            )

    @api.depends("product_id", "state", "qty_invoiced", "qty_delivered")
    def _compute_product_updatable(self):
        super()._compute_product_updatable()
        for line in self:
            if line.can_edit_subscription_line:
                line.product_updatable = True

    def _check_line_unlink(self):
        """Permite eliminar líneas de suscripción editables para el grupo de editor."""
        undeletable_lines = super()._check_line_unlink()
        if self.env.user.has_group("subscription_editor.group_subscription_editor"):
            return undeletable_lines - self.filtered(lambda line: line.can_edit_subscription_line)
        return undeletable_lines
