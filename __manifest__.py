# -*- coding: utf-8 -*-
{
    "name": "Subscription Editor",
    "summary": "Permite editar suscripciones activas: productos, precios, cantidades y líneas.",
    "version": "19.0.1.0.0",
    "category": "Sales/Subscriptions",
    "author": "AfterMoves",
    "website": "https://aftermoves.com",
    "license": "LGPL-3",
    "depends": ["sale_subscription"],
    "data": [
        "security/subscription_editor_security.xml",
        "security/ir.model.access.csv",
        "views/sale_order_views.xml",
        "views/subscription_editor_wizard_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
