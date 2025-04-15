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
    def _ctt_log_request(self, ctt_request):
        """When debug is active requests/responses will be logged in ir.logging

        :param ctt_request ctt_request: Banlingkit Express request object
        """
        self.log_xml(ctt_request.ctt_last_request, "ctt_request")
        self.log_xml(ctt_request.ctt_last_response, "ctt_response")

    def _ctt_check_error(self, error):
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
        ctt_request = self._bl_request()
        error, service_types = ctt_request.get_service_types()
        self._ctt_log_request(ctt_request)
        self._ctt_check_error(error)
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

    def action_ctt_validate_user(self):
        """Maps to API's ValidateUser method

        :raises UserError: If the user credentials aren't valid
        """
        self.ensure_one()
        ctt_request = self._bl_request()
        error = ctt_request.validate_user()
        self._ctt_log_request(ctt_request)

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

        return {
            "storehouseCode": "ST00002",
            "sourceCode": reference,
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
        ctt_request = self._bl_request()
        print("banlingkit_send_shipping")
        print(ctt_request)
        result = []
        for picking in pickings:
            vals = self._prepare_banlingkit_shipping(picking)
            print("banlingkit_send_shipping vals")
            print(vals)
        
            try:
                error, documents, tracking = ctt_request.manifest_shipping(shipping_values=vals)
                self._ctt_check_error(error)
            except Exception as e:
                raise (e)
            finally:
                self._ctt_log_request(ctt_request)

            vals.update({"tracking_number": tracking, "exact_price": 0})
            vals.update({"carrier_tracking_ref": tracking})
            # save the tracking number to carrier_tracking_ref field
            picking.carrier_tracking_ref = tracking

            # save the tracking number to carrier_tracking_ref field
            picking.carrier_tracking_ref = tracking
            picking.update({"carrier_tracking_ref": tracking})

            # Download the PDF document from the URL
            response = requests.get(documents)
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
            picking.message_post(body=body, attachments=documents)

            # the documents is a url, we need to redirect to the url to print the label

            http.redirect(
            documents
            )

            result.append(vals)
        return result

    def banlingkit_cancel_shipment(self, pickings):
        """Cancel the expedition

        :param recordset: pickings `stock.picking` recordset
        :returns boolean: True if success
        """
        ctt_request = self._bl_request()
        for picking in pickings.filtered("carrier_tracking_ref"):
            try:
                error = ctt_request.cancel_shipping(picking.carrier_tracking_ref)
                self._ctt_check_error(error)
            except Exception as e:
                raise (e)
            finally:
                self._ctt_log_request(ctt_request)
        return True

    def banlingkit_get_label(self, reference):
        """Generate label for picking

        :param str reference: shipping reference
        :returns tuple: (file_content, file_name)
        """
        self.ensure_one()
        if not reference:
            return False
        ctt_request = self._bl_request()
        try:
            error, label = ctt_request.get_documents_multi(
                reference,
                model_code=self.banlingkit_document_model_code,
                kind_code=self.banlingkit_document_format,
                offset=self.banlingkit_document_offset,
            )
            self._ctt_check_error(error)
        except Exception as e:
            raise (e)
        finally:
            self._ctt_log_request(ctt_request)
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
        ctt_request = self._bl_request()
        try:
            error, trackings = ctt_request.get_tracking(picking.carrier_tracking_ref)
            self._ctt_check_error(error)
        except Exception as e:
            raise (e)
        finally:
            self._ctt_log_request(ctt_request)
        picking.tracking_state_history = "\n".join(
            [self._banlingkit_format_tracking(tracking) for tracking in trackings]
        )
        current_tracking = trackings.pop()
        picking.tracking_state = self._banlingkit_format_tracking(current_tracking)
        picking.delivery_state = BanlingkitXPRESS_DELIVERY_STATES_STATIC.get(
            current_tracking["StatusCode"], "incidence"
        )

    def banlingkit_get_tracking_link(self, picking):
        """Wildcard method for Banlingkit Express tracking link.

        :param record picking: `stock.picking` record
        :return str: tracking url
        """
        tracking_url = (
            "https://t.17track.net/en#nums={}"
        )
        return tracking_url.format(picking.carrier_tracking_ref)
