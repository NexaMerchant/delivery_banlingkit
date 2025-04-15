# Copyright 2022 Tecnativa - David Vidal
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "Delivery Banlingkit Express",
    "summary": "Delivery Carrier implementation for Banlingkit Express API",
    "version": "16.0.1.1.2",
    "category": "Delivery",
    "website": "https://github.com/NexaMerchant/delivery_banlingkit",
    "author": "Steve",
    "license": "AGPL-3",
    "installable": True,
    "depends": ["delivery_package_number", "delivery_state", "delivery_price_method","sale_order_batch"],
    "data": [
        "security/ir.model.access.csv",
        "wizards/banlingkit_manifest_wizard_views.xml",
        "wizards/banlingkit_pickup_wizard.xml",
        "views/delivery_banlingkit_view.xml",
        "views/stock_picking_views.xml",
    ],
}