# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command

from odoo.addons.sale_subscription.models.sale_order import SUBSCRIPTION_PROGRESS_STATE


class SubscriptionEditorWizard(models.TransientModel):
    _name = "subscription.editor.wizard"
    _description = "Wizard de edición de suscripción"

    order_id = fields.Many2one(
        "sale.order",
        string="Suscripción",
        required=True,
        ondelete="cascade",
        domain=[("is_subscription", "=", True), ("state", "=", "sale")],
    )
    line_ids = fields.One2many(
        "subscription.editor.wizard.line",
        "wizard_id",
        string="Líneas",
    )
    cancel_draft_invoices = fields.Boolean(
        string="Cancelar facturas en borrador",
        default=True,
        help="Si está marcado, las facturas en borrador asociadas a la suscripción se cancelarán y se regenerarán."
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("order_id"):
                order = self.env["sale.order"].browse(vals["order_id"])
                order._check_subscription_editable()
        return super().create(vals_list)

    def _validate_before_apply(self):
        """Valida que la suscripción pueda editarse."""
        self.ensure_one()
        order = self.order_id
        order._check_subscription_editable()

    def _cancel_draft_invoices(self):
        """Cancela las facturas en borrador asociadas a la suscripción."""
        self.ensure_one()
        order = self.order_id
        draft_invoices = order.invoice_ids.filtered(lambda inv: inv.state == "draft")
        if draft_invoices:
            if not self.cancel_draft_invoices:
                raise UserError(_(
                    "La suscripción %s tiene facturas en borrador. Activa 'Cancelar facturas en borrador' o cancele las facturas manualmente.",
                    order.name
                ))
            draft_invoices.button_cancel()
        return draft_invoices

    def _prepare_line_values(self, wizard_line):
        """Prepara los valores para crear/actualizar una línea de pedido."""
        vals = {
            "product_id": wizard_line.product_id.id,
            "name": wizard_line.name,
            "product_uom_qty": wizard_line.product_uom_qty,
            "product_uom_id": wizard_line.product_uom_id.id,
            "price_unit": wizard_line.price_unit,
            "discount": wizard_line.discount,
            "tax_ids": [(6, 0, wizard_line.tax_ids.ids)],
            "sequence": wizard_line.sequence,
            "display_type": wizard_line.display_type,
        }
        if not wizard_line.product_id:
            vals.pop("product_id")
            vals.pop("product_uom_id")
            vals.pop("price_unit")
            vals.pop("discount")
            vals.pop("tax_ids")
            vals.pop("product_uom_qty")
        return vals

    def action_apply_changes(self):
        """Aplica los cambios del wizard a la suscripción."""
        self.ensure_one()
        self._validate_before_apply()

        order = self.order_id
        if not self.env.user.has_group("subscription_editor.group_subscription_editor"):
            raise UserError(_("No tienes permiso para editar suscripciones activas."))

        # Guardar MRR anterior para el log
        old_mrr = order.recurring_monthly

        # Cancelar facturas en borrador
        cancelled_invoices = self._cancel_draft_invoices()

        # Mapear líneas del wizard con líneas existentes
        wizard_lines_by_sale_line = {line.sale_line_id.id: line for line in self.line_ids if line.sale_line_id}
        original_line_ids = set(order.order_line.ids)
        updated_line_ids = set()

        # Actualizar líneas existentes
        for wizard_line in self.line_ids:
            if wizard_line.display_type and not wizard_line.product_id:
                # Línea de sección o nota
                if wizard_line.sale_line_id:
                    wizard_line.sale_line_id.write({
                        "name": wizard_line.name,
                        "sequence": wizard_line.sequence,
                        "display_type": wizard_line.display_type,
                    })
                    updated_line_ids.add(wizard_line.sale_line_id.id)
                else:
                    self.env["sale.order.line"].create({
                        "order_id": order.id,
                        "name": wizard_line.name,
                        "sequence": wizard_line.sequence,
                        "display_type": wizard_line.display_type,
                    })
                continue

            if wizard_line.sale_line_id:
                # Actualizar línea existente
                vals = self._prepare_line_values(wizard_line)
                wizard_line.sale_line_id.write(vals)
                updated_line_ids.add(wizard_line.sale_line_id.id)
            else:
                # Crear nueva línea
                vals = self._prepare_line_values(wizard_line)
                vals["order_id"] = order.id
                self.env["sale.order.line"].create(vals)

        # Eliminar líneas originales que el usuario sacó del wizard, solo si no están
        # facturadas/entregadas. Las líneas con facturación o entrega se mantienen para
        # no romper la integridad contable/logística.
        lines_to_remove = order.order_line.filtered(
            lambda line: line.id in original_line_ids and line.id not in updated_line_ids
        )
        lines_to_remove = lines_to_remove.filtered(
            lambda line: line.qty_invoiced <= 0 and line.qty_delivered <= 0 and not line.is_downpayment
        )
        lines_to_remove.unlink()

        # Recomputar totales y MRR
        order.invalidate_recordset()
        order._compute_recurring_total()
        order._compute_recurring_monthly()

        # Registrar cambio de MRR en los logs
        new_mrr = order.recurring_monthly
        if old_mrr != new_mrr:
            self.env["sale.order.log"]._create_mrr_change_log(order, {"recurring_monthly": old_mrr})

        # Mensaje en el chatter
        changes_summary = _(
            "Suscripción editada manualmente por %s. MRR anterior: %s, MRR nuevo: %s.",
            self.env.user.name,
            order.currency_id.format(old_mrr),
            order.currency_id.format(new_mrr),
        )
        if cancelled_invoices:
            changes_summary += _(" Facturas en borrador canceladas: %s", ", ".join(cancelled_invoices.mapped("name")))
        order.message_post(body=changes_summary)

        # Regenerar factura en borrador si había una cancelada
        if cancelled_invoices:
            try:
                order.with_context(recurring_automatic=True)._create_invoices(final=True)
            except Exception as e:
                raise UserError(_(
                    "Los cambios se aplicaron pero no se pudo regenerar la factura: %s", str(e)
                )) from e

        return {"type": "ir.actions.act_window_close"}


class SubscriptionEditorWizardLine(models.TransientModel):
    _name = "subscription.editor.wizard.line"
    _description = "Línea del wizard de edición de suscripción"
    _order = "sequence, id"

    wizard_id = fields.Many2one("subscription.editor.wizard", required=True, ondelete="cascade")
    sale_line_id = fields.Many2one("sale.order.line", string="Línea original")
    sequence = fields.Integer(default=10)
    display_type = fields.Selection(
        selection=[
            ("line_section", "Sección"),
            ("line_note", "Nota"),
        ],
        string="Tipo de línea",
    )
    product_id = fields.Many2one(
        "product.product",
        string="Producto",
        domain="[('sale_ok', '=', True)]",
    )
    name = fields.Text(string="Descripción")
    product_uom_qty = fields.Float(string="Cantidad", default=1.0)
    product_uom_id = fields.Many2one(
        "uom.uom",
        string="Unidad de medida",
    )
    price_unit = fields.Float(string="Precio unitario", digits="Product Price")
    discount = fields.Float(string="Descuento (%)", digits="Discount")
    tax_ids = fields.Many2many(
        "account.tax",
        string="Impuestos",
        domain="[('type_tax_use', '=', 'sale')]",
    )

    @api.onchange("product_id")
    def _onchange_product_id(self):
        """Actualiza descripción, UoM y precio al cambiar el producto."""
        if not self.product_id:
            return
        self.product_uom_id = self.product_id.uom_id.id
        self.name = self.product_id.get_product_multiline_description_sale()
        # Precio base del producto (sin pricelist específico)
        self.price_unit = self.product_id.lst_price
