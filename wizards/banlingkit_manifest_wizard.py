# Copyright 2022 Tecnativa - David Vidal
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
import base64

from odoo import fields, models


class BanlingkitExpressManifestWizard(models.TransientModel):
    _name = "banlingkit.manifest.wizard"
    _description = "Get the Banlingkit Express Manifest for the given date range"

    document_type = fields.Selection(
        selection=[("XLSX", "Excel"), ("PDF", "PDF")],
        string="Format",
        default="XLSX",
        required=True,
    )
    from_date = fields.Date(required=True, default=fields.Date.context_today)
    to_date = fields.Date(required=True, default=fields.Date.context_today)
    carrier_ids = fields.Many2many(
        string="Filter accounts",
        comodel_name="delivery.carrier",
        domain=[("delivery_type", "=", "banlingkit")],
        help="Leave empty to gather all the Banlingkit account manifests",
    )
    state = fields.Selection(
        selection=[("new", "new"), ("done", "done")],
        default="new",
        readonly=True,
    )
    attachment_ids = fields.Many2many(
        comodel_name="ir.attachment", readonly=True, string="Manifests"
    )

    def get_manifest(self):
        """List of shippings for the given dates as Banlingkit provides them"""
        carriers = self.carrier_ids or self.env["delivery.carrier"].search(
            [("delivery_type", "=", "banlingkit")]
        )
        # Avoid getting repeated manifests. Carriers with different service
        # configuration would produce the same manifest.
        unique_accounts = {
            (c.banlingkit_customer, c.banlingkit_contract, c.banlingkit_agency)
            for c in carriers
        }
        filtered_carriers = self.env["delivery.carrier"]
        for customer, contract, agency in unique_accounts:
            filtered_carriers += fields.first(
                carriers.filtered(
                    lambda x: x.banlingkit_customer == customer
                    and x.banlingkit_contract == contract
                    and x.banlingkit_agency == agency
                )
            )
        for carrier in filtered_carriers:
            bl_request = carrier._bl_request()
            from_date = fields.Date.to_string(self.from_date)
            to_date = fields.Date.to_string(self.to_date)
            error, manifest = bl_request.report_shipping(
                "ODOO", self.document_type, from_date, to_date
            )
            carrier._bl_check_error(error)
            carrier._bl_log_request(bl_request)
            for _filename, file in manifest:
                filename = "{}{}{}-{}-{}.{}".format(
                    carrier.banlingkit_customer,
                    carrier.banlingkit_contract,
                    carrier.banlingkit_agency,
                    from_date.replace("-", ""),
                    to_date.replace("-", ""),
                    self.document_type.lower(),
                )
                self.attachment_ids += self.env["ir.attachment"].create(
                    {
                        "datas": base64.b64encode(file),
                        "name": filename,
                        "res_model": self._name,
                        "res_id": self.id,
                        "type": "binary",
                    }
                )
        self.state = "done"
        return dict(
            self.env["ir.actions.act_window"]._for_xml_id(
                "delivery_banlingkit.action_delivery_banlingkit_manifest_wizard"
            ),
            res_id=self.id,
        )
