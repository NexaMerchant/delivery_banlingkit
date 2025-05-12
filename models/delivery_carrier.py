from odoo import _, api, fields, models
from odoo.exceptions import UserError
import logging
from odoo.tools.config import config
from odoo import http
import requests
import base64

_logger = logging.getLogger(__name__)

# from .banlingkit_master_data import (
# )
from .banlingkit_request import BanlingkitExpressRequest


class DeliveryCarrier(models.Model):
    _inherit = "delivery.carrier"

    delivery_type = fields.Selection(
        selection_add=[("banlingkit", "Banlingkit Express")],
        ondelete={"banlingkit": "set default"},
    )
    banlingkit_api_cid = fields.Char(
        string="API Client ID",
        help="BanlingKit Express API Client ID. This is the user used to connect to the API.",
    )
    banlingkit_api_token = fields.Char(
        string="API Token",
        help="BanlingKit Express API Token. This is the password used to connect to the API.",
    )

    banlingkit_document_model_code = fields.Selection(
        selection=[
            ("SINGLE", "Single"),
            ("MULTI1", "Multi 1"),
            ("MULTI3", "Multi 3"),
            ("MULTI4", "Multi 4"),
        ],
        default="SINGLE",
        string="Document model",
    )
    banlingkit_document_format = fields.Selection(
        selection=[("PDF", "PDF"), ("PNG", "PNG"), ("BMP", "BMP")],
        default="PDF",
        string="Document format",
    )
    banlingkit_document_offset = fields.Integer(string="Document Offset")

    @api.onchange("delivery_type")
    def _onchange_delivery_type_ctt(self):
        """Default price method for Banlingkit as the API can't gather prices."""
        if self.delivery_type == "banlingkit":
            self.price_method = "base_on_rule"

    def _bl_request(self):
        """Get Banlingkit Request object

        :return BanlingkitExpressRequest: Banlingkit Express Request object
        """
        _logger.debug("banlingkit_api_cid: %s", self.banlingkit_api_cid)
        if not self.banlingkit_api_cid:
            _logger.warning("banlingkit_api_cid is False, please check configuration.")
        record_values = self.read()[0]
        _logger.debug("banlingkit_api_token: %s", record_values["banlingkit_api_token"])
        if self.banlingkit_api_token is False:
            # read the value from the configuration
            _logger.warning("banlingkit_api_token is False, please check configuration.")
            self.banlingkit_api_token = config.get(
                "banlingkit_api_salt", self.banlingkit_api_token
            )
        if self.banlingkit_api_cid is False:
            self.banlingkit_api_cid = config.get(
                "banlingkit_api_cid", self.banlingkit_api_cid
            )
        print("banlingkit_api_cid")
        print(self.banlingkit_api_cid)
        print("banlingkit_api_token")
        print(self.banlingkit_api_token)

        return BanlingkitExpressRequest(
            api_cid=self.banlingkit_api_cid,
            api_salt=self.banlingkit_api_token,
            prod=self.prod_environment,
        )

    @api.model
    def _bl_log_request(self, bl_request):
        """When debug is active requests/responses will be logged in ir.logging

        :param bl_request bl_request: Banlingkit Express request object
        """
        print("banlingkit cct_request")
        print(bl_request)

    def _bl_check_error(self, error):
        """Common error checking. We stop the program when an error is returned.

        :param list error: List of tuples in the form of (code, description)
        :raises UserError: Prompt the error to the user
        """
        print(error)
        return

    @api.model
    def _banlingkit_format_tracking(self, tracking):
        """Helper to forma tracking history strings

        :param OrderedDict tracking: Banlingkit tracking values
        :return str: Tracking line
        """
        status = "{} - [{}] {}".format(
            fields.Datetime.to_string(tracking["StatusDateTime"]),
            tracking["StatusCode"],
            tracking["StatusDescription"],
        )
        if tracking["IncidentCode"]:
            status += " ({}) - {}".format(
                tracking["IncidentCode"], tracking["IncidentDescription"]
            )
        return status

    @api.onchange("banlingkit_shipping_type")
    def _onchange_banlingkit_shipping_type(self):
        """Control service validity according to credentials

        :raises UserError: We list the available services for given credentials
        """
        if not self.banlingkit_shipping_type:
            return
        # Avoid checking if credentianls aren't setup or are invalid
        bl_request = self._bl_request()
        error, service_types = bl_request.get_service_types()
        self._bl_log_request(bl_request)
        self._bl_check_error(error)
        type_codes, type_descriptions = zip(*service_types)
        if self.banlingkit_shipping_type not in type_codes:
            service_name = dict(
                self._fields["banlingkit_shipping_type"]._description_selection(
                    self.env
                )
            )[self.banlingkit_shipping_type]
            raise UserError(
                _(
                    "This banlingkit Express service (%(service_name)s) isn't allowed for "
                    "this account configuration. Please choose one of the followings\n"
                    "%(type_descriptions)s",
                    service_name=service_name,
                    type_descriptions=type_descriptions,
                )
            )

    def action_bl_validate_user(self):
        """Maps to API's ValidateUser method

        :raises UserError: If the user credentials aren't valid
        """
        self.ensure_one()
        bl_request = self._bl_request()
        error = bl_request.validate_user()
        self._bl_log_request(bl_request)

    def _prepare_banlingkit_shipping(self, picking):
        """Convert picking values for Banlingkit Express API

        :param record picking: `stock.picking` record
        :return dict: Values prepared for the Banlingkit connector
        """
        self.ensure_one()
        # A picking can be delivered from any warehouse
        sender_partner = picking.company_id.partner_id
        if picking.picking_type_id:
            sender_partner = (
                picking.picking_type_id.warehouse_id.partner_id
                or picking.company_id.partner_id
            )
        recipient = picking.partner_id
        recipient_entity = picking.partner_id.commercial_partner_id
        weight = picking.shipping_weight
        reference = picking.name
        if picking.sale_id:
            reference = "{}-{}".format(picking.sale_id.name, reference)

        # https://note.youdao.com/ynoteshare/index.html?id=ae42953f52c03008f1ecdd073e5d4032&type=note&_time=1680855653628

        goodslist = []
        # Get the product name and quantity from the picking
        for move in picking.move_ids:
            # get the product name and quantity from the picking
            goodslist.append(
                {
                    "declaredEnSpecification": move.product_id.declared_name_en,
                    "declaredEnName": move.product_id.declared_name_en,
                    "declaredSpecification": move.product_id.declared_name_cn,
                    "declaredName": move.product_id.declared_name_cn,
                    "quantity": move.product_uom_qty,
                    "barCode": move.product_id.default_code,
                }
            )


        # Get invoice Price from the picking
        invoice_price = 0.0
        for move in picking.move_ids:
            # get the product name and quantity from the picking
            invoice_price += move.product_id.list_price * move.product_uom_qty

        # strplace the reference "/" with "-"
        sourceCode = reference.replace("/", "-")

        return {
            "storehouseCode": "ST00002",
            "sourceCode": sourceCode,
            #"sourceCode": "SS00002",
            "currency": picking.company_id.currency_id.name,
            # order amount
            "invoicePrice": invoice_price,
            "needPack": False,
            "consignee": recipient.name or recipient_entity.name,
            "tel": str(recipient.phone or recipient_entity.phone or ''),
            "contry": recipient.country_id.name,
            "province": recipient.state_id.name,
            "city": recipient.city,
            "detail": recipient.street,
            #"houseNumber": recipient.street2,
            "postCode": recipient.zip,
            "email": str(recipient.email or recipient_entity.email or ''),
            "comments": None,  # Optional
            "items": goodslist,
        }


    def banlingkit_send_shipping(self, pickings):
        """Banlingkit Express wildcard method called when a picking is confirmed

        :param record pickings: `stock.picking` recordset
        :raises UserError: On any API error
        :return dict: With tracking number and delivery price (always 0)
        """
        bl_request = self._bl_request()
        print("banlingkit_send_shipping")
        print(bl_request)
        result = []
        for picking in pickings:

            # Check if the picking is already shipped
            # if picking.state == "done":
            #     raise UserError(_("This picking is already shipped."))
            
            # check if the picking has a tracking number and the same carrier
            if picking.carrier_tracking_ref and picking.carrier_id == self:
                raise UserError(_("This picking already has a tracking number."))


            vals = self._prepare_banlingkit_shipping(picking)
            print("banlingkit_send_shipping vals")
            print(vals)
        
            try:
                error, documents, tracking = bl_request.manifest_shipping(shipping_values=vals)
                self._bl_check_error(error)
            except Exception as e:
                raise (e)
            finally:
                self._bl_log_request(bl_request)
                #return result
                print("banlingkit_send_shipping finally" + str(bl_request))
                print("banlingkit_send_shipping finally" + str(error))

            print(tracking)
            print(documents)

            if tracking:
                vals.update({"carrier_tracking_ref": tracking})

            # if documents is empty, we need to use the default url
            if not documents:
                documents = "/delivery/print_label?tracking_no={}".format(
                    tracking
                )
                base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
                documents = base_url.rstrip('/') + documents
                print("documents", documents)


            vals.update({"tracking_number": tracking, "exact_price": 0})
            vals.update({"carrier_tracking_ref": tracking})
            # save the tracking number to carrier_tracking_ref field
            picking.carrier_tracking_ref = tracking

            # save the tracking number to carrier_tracking_ref field
            picking.carrier_tracking_ref = tracking
            picking.update({"carrier_tracking_ref": tracking})

            # if documents is a url, we need to download the file and save it as an attachment 
            attachment = False
            if documents:
                response = requests.get(documents)
                print("response", response.status_code)
                if response.status_code != 200:
                    raise Exception("Error in request")
                pdf_content = response.content
                
                attachment = self.env['ir.attachment'].create({
                    'name': tracking + '.pdf',
                    'datas': base64.b64encode(pdf_content),
                    'db_datas': base64.b64encode(pdf_content),
                    'res_model': 'stock.picking',  # Attach to the stock.picking
                    'res_id': pickings.id,  # Attach to the current picking
                    'type': 'binary',
                    'mimetype': 'application/pdf',
                    'url': documents,
                })

            # The default shipping method doesn't allow to configure the label
            # format, so once we get the tracking, we ask for it again.
            #documents = self.banlingkit_get_label(tracking)
            # We post an extra message in the chatter with the barcode and the
            # label because there's clean way to override the one sent by core.
            
            body = _("Banlingkit Shipping Documents")
            picking.message_post(body=body)

            picking.sale_id.shipping_time = fields.Datetime.now()

            result.append(vals)
        return result

    def banlingkit_cancel_shipment(self, pickings):
        """Cancel the expedition

        :param recordset: pickings `stock.picking` recordset
        :returns boolean: True if success
        """
        bl_request = self._bl_request()
        for picking in pickings.filtered("carrier_tracking_ref"):
            try:
                error = bl_request.cancel_shipping(picking.carrier_tracking_ref)
                self._bl_check_error(error)
            except Exception as e:
                raise (e)
            finally:
                self._bl_log_request(bl_request)
        return True

    def banlingkit_get_label(self, reference):
        """Generate label for picking

        :param str reference: shipping reference
        :returns tuple: (file_content, file_name)
        """
        if not self:
            return False
        if not reference:
            return False
        self.ensure_one()
        bl_request = self._bl_request()
        try:
            error, label = bl_request.get_documents_multi(
                reference,
                model_code=self.banlingkit_document_model_code,
                kind_code=self.banlingkit_document_format,
                offset=self.banlingkit_document_offset,
            )
            self._bl_check_error(error)
        except Exception as e:
            raise (e)
        finally:
            self._bl_log_request(bl_request)
        if not label:
            return False
        return label

    def banlingkit_tracking_state_update(self, picking):
        """Wildcard method for Banlingkit Express tracking followup

        :param recod picking: `stock.picking` record
        """
        self.ensure_one()
        if not picking.carrier_tracking_ref:
            return
        bl_request = self._bl_request()
        try:
            error, trackings = bl_request.get_tracking(picking.carrier_tracking_ref)
            self._bl_check_error(error)
        except Exception as e:
            raise (e)
        finally:
            self._bl_log_request(bl_request)
        picking.tracking_state_history = "\n".join(
            [self._banlingkit_format_tracking(tracking) for tracking in trackings]
        )
        current_tracking = trackings.pop()
        picking.tracking_state = self._banlingkit_format_tracking(current_tracking)
        

    def banlingkit_get_tracking_link(self, picking):
        """Wildcard method for Banlingkit Express tracking link.

        :param record picking: `stock.picking` record
        :return str: tracking url
        """
        tracking_url = (
            "http://admin.banlingwuliu.com:8010/tracks/track-search.html#nums={}"
        )
        return tracking_url.format(picking.carrier_tracking_ref)
