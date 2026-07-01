# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.sale_subscription.models.sale_order import SUBSCRIPTION_PROGRESS_STATE


class SaleOrder(models.Model):
    _inherit = "sale.order"

    can_edit_subscription = fields.Boolean(
        string="Puede editar suscripción",
        compute="_compute_can_edit_subscription",
    )

    @api.depends("is_subscription", "subscription_state", "state")
    def _compute_can_edit_subscription(self):
        group = self.env.user.has_group("subscription_editor.group_subscription_editor")
        for order in self:
            order.can_edit_subscription = bool(
                group
                and order.is_subscription
                and order.subscription_state in SUBSCRIPTION_PROGRESS_STATE
                and order.state == "sale"
            )

    def _can_edit_subscription(self):
        """Verifica si el usuario actual puede editar la suscripción."""
        self.ensure_one()
        return self.env.user.has_group("subscription_editor.group_subscription_editor")

    def _check_subscription_editable(self):
        """Valida que la suscripción esté en un estado editable."""
        for order in self:
            if not order.is_subscription:
                raise UserError(_("El pedido %s no es una suscripción.", order.name))
            if order.subscription_state not in SUBSCRIPTION_PROGRESS_STATE:
                raise UserError(_(
                    "Solo se pueden editar suscripciones en estado 'En progreso' o 'Pausada'. "
                    "El estado actual de %s es %s.", order.name, order.subscription_state
                ))
            if order.state != "sale":
                raise UserError(_("La suscripción %s debe estar confirmada para editarse.", order.name))

    def action_open_subscription_editor(self):
        """Abre el wizard para editar la suscripción activa."""
        self.ensure_one()
        self._check_subscription_editable()
        if not self._can_edit_subscription():
            raise UserError(_("No tienes permiso para editar suscripciones activas."))

        # Precargar líneas existentes en el wizard
        line_vals = []
        for line in self.order_line:
            line_vals.append((0, 0, {
                "sale_line_id": line.id,
                "product_id": line.product_id.id,
                "name": line.name,
                "product_uom_qty": line.product_uom_qty,
                "product_uom_id": line.product_uom_id.id,
                "price_unit": line.price_unit,
                "discount": line.discount,
                "tax_ids": [(6, 0, line.tax_ids.ids)],
                "sequence": line.sequence,
                "display_type": line.display_type,
            }))

        wizard = self.env["subscription.editor.wizard"].create({
            "order_id": self.id,
            "line_ids": line_vals,
        })

        return {
            "type": "ir.actions.act_window",
            "name": _("Editar Suscripción"),
            "res_model": "subscription.editor.wizard",
            "res_id": wizard.id,
            "view_mode": "form",
            "target": "new",
            "context": {"default_order_id": self.id},
        }
