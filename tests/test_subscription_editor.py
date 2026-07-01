# -*- coding: utf-8 -*-

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase


class TestSubscriptionEditor(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Cliente de prueba"})
        cls.plan = cls.env["sale.subscription.plan"].create({
            "name": "Plan mensual de prueba",
            "billing_period_value": 1,
            "billing_period_unit": "month",
        })
        cls.product_a = cls.env["product.product"].create({
            "name": "Producto A recurrente",
            "type": "service",
            "recurring_invoice": True,
            "list_price": 100.0,
            "taxes_id": False,
        })
        cls.product_b = cls.env["product.product"].create({
            "name": "Producto B recurrente",
            "type": "service",
            "recurring_invoice": True,
            "list_price": 200.0,
            "taxes_id": False,
        })
        cls.product_c = cls.env["product.product"].create({
            "name": "Producto C recurrente",
            "type": "service",
            "recurring_invoice": True,
            "list_price": 50.0,
            "taxes_id": False,
        })

    def _create_confirmed_subscription(self):
        """Crea y confirma una suscripción con producto A."""
        order = self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "plan_id": self.plan.id,
            "order_line": [(0, 0, {
                "product_id": self.product_a.id,
                "product_uom_qty": 1.0,
                "price_unit": 100.0,
            })],
        })
        order.action_confirm()
        return order

    def _open_editor(self, order):
        """Abre el wizard de edición para una suscripción."""
        action = order.action_open_subscription_editor()
        return self.env["subscription.editor.wizard"].browse(action["res_id"])

    def test_edit_price(self):
        """Prueba editar el precio de una línea de suscripción."""
        order = self._create_confirmed_subscription()
        self.assertEqual(order.recurring_monthly, 100.0)

        wizard = self._open_editor(order)
        wizard.line_ids.price_unit = 150.0
        wizard.action_apply_changes()

        order.invalidate_recordset()
        self.assertEqual(order.order_line.price_unit, 150.0)
        self.assertEqual(order.recurring_monthly, 150.0)

    def test_change_product(self):
        """Prueba cambiar el producto de una línea."""
        order = self._create_confirmed_subscription()
        wizard = self._open_editor(order)

        wizard.line_ids.product_id = self.product_b.id
        wizard.line_ids.price_unit = 200.0
        wizard.action_apply_changes()

        order.invalidate_recordset()
        self.assertEqual(order.order_line.product_id, self.product_b)
        self.assertEqual(order.recurring_monthly, 200.0)

    def test_add_line(self):
        """Prueba añadir una nueva línea a la suscripción."""
        order = self._create_confirmed_subscription()
        wizard = self._open_editor(order)

        self.env["subscription.editor.wizard.line"].create({
            "wizard_id": wizard.id,
            "product_id": self.product_c.id,
            "name": self.product_c.name,
            "product_uom_qty": 1.0,
            "product_uom_id": self.product_c.uom_id.id,
            "price_unit": 50.0,
            "sequence": 20,
        })
        wizard.action_apply_changes()

        order.invalidate_recordset()
        self.assertEqual(len(order.order_line), 2)
        self.assertEqual(order.recurring_monthly, 150.0)

    def test_remove_line(self):
        """Prueba eliminar una línea de la suscripción."""
        order = self._create_confirmed_subscription()
        # Añadir una segunda línea primero
        wizard = self._open_editor(order)
        self.env["subscription.editor.wizard.line"].create({
            "wizard_id": wizard.id,
            "product_id": self.product_c.id,
            "name": self.product_c.name,
            "product_uom_qty": 1.0,
            "product_uom_id": self.product_c.uom_id.id,
            "price_unit": 50.0,
            "sequence": 20,
        })
        wizard.action_apply_changes()

        # Eliminar la segunda línea
        order.invalidate_recordset()
        wizard = self._open_editor(order)
        line_to_remove = wizard.line_ids.filtered(lambda l: l.product_id == self.product_c)
        line_to_remove.unlink()
        wizard.action_apply_changes()

        order.invalidate_recordset()
        self.assertEqual(len(order.order_line), 1)
        self.assertEqual(order.recurring_monthly, 100.0)

    def test_block_if_paid_invoice(self):
        """Prueba que no se pueda editar si hay una factura pagada."""
        order = self._create_confirmed_subscription()
        invoice = order.with_context(recurring_automatic=True)._create_invoices(final=True)
        invoice.action_post()
        # Simular pago asignando payment_state (no es posible en compute real,
        # pero validamos que el bloqueo funciona si payment_state es paid)
        invoice.payment_state = "paid"

        with self.assertRaises(UserError):
            order.action_open_subscription_editor()
