try:
    from decimal import Decimal, ROUND_HALF_UP
except:
    from django.utils._decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ImproperlyConfigured
from django.db.models import Q
from satchmo.configuration import config_value
from satchmo.contact.models import Contact
from satchmo.l10n.models import AdminArea, Country
from satchmo.shop.models import Config
from satchmo.utils import is_string_like
from satchmo.tax.models import TaxRate, TaxClass
import logging

log = logging.getLogger('tax.area')

class Processor(object):
    
    method = "area"
    
    def __init__(self, order=None, user=None):
        """
        Any preprocessing steps should go here
        For instance, copying the shipping and billing areas
        """
        self.order = order
        self.user = user
        
    def _get_location(self):
        area=country=None
        
        if self.order:
            country = self.order.ship_country
            area = self.order.ship_state
        
        elif self.user and self.user.is_authenticated():
            try:
                contact = Contact.objects.get(user=self.user)
                try:
                    area = contact.state
                except AttributeError:
                    pass
                try:
                    country = contact.country
                except AttributeError:
                    pass

            except Contact.DoesNotExist:
                pass
        
        if country:
            try:
                country = Country.objects.get(iso2_code__exact=country)
            except Country.DoesNotExist:
                log.info("Couldn't find Country from string: %s", country)
                country = None

        if not country:
            country = Config.objects.get_current().sales_country

        if area:
            try:
                area = AdminArea.objects.get(name__iexact=area,
                                             country=country)
            except AdminArea.DoesNotExist:
                try:
                    area = AdminArea.objects.get(abbrev__iexact=area,
                                                 country=country)
                except AdminArea.DoesNotExist:
                    log.info("Couldn't find AdminArea from string: %s", area)
                    area = None


        return area, country
        
    def get_percent(self, taxclass="Default", area=None, country=None):
        return 100*self.get_rate(taxclass=taxclass, area=area, country=country)
        
    def get_rate(self, taxclass=None, area=None, country=None, get_object=False, **kwargs):
        if not taxclass:
            taxclass = "Default"
        rate = None
        if not (area or country):
            area, country = self._get_location()
            
        if is_string_like(taxclass):
            try:
                taxclass = TaxClass.objects.get(title__iexact=taxclass)
            
            except TaxClass.DoesNotExist:
                raise ImproperlyConfigured("Can't find a '%s' Tax Class", taxclass)            
            
        if area:
            try:
                rate = TaxRate.objects.get(taxClass=taxclass, taxZone=area)
                
            except TaxRate.DoesNotExist:
                rate = None
                
        if not rate:
            try:
                rate = TaxRate.objects.get(taxClass=taxclass, taxCountry=country)
                
            except TaxRate.DoesNotExist:
                rate = None
        
        log.debug("Got rate [%s] = %s", taxclass, rate)
        if get_object:
            return rate
        else:
            if rate:
                return rate.percentage
            else:
                return Decimal("0.00")

    def by_price(self, taxclass, price):
        rate = self.get_rate(taxclass)

        if not rate:
            t = Decimal("0.00")
        else:
            t = Decimal(rate * price).quantize(Decimal("0.01"), ROUND_HALF_UP)

        return t

    def by_product(self, product, quantity=1):
        """Get the tax for a given product"""
        price = product.get_qty_price(quantity)
        tc = product.taxClass
        return self.by_price(tc, price)
        
    def by_orderitem(self, orderitem):
        if orderitem.product.taxable:
            price = orderitem.sub_total
            taxclass = orderitem.product.taxClass
            return self.by_price(taxclass, price)
        else:
            return Decimal("0.00")

    def shipping(self, subtotal=None):
        if subtotal is None and self.order:
            subtotal = self.order.shipping_sub_total

        if subtotal:
            rate = None
            if config_value('TAX','TAX_SHIPPING'):
                try:
                    tc = TaxClass.objects.get(title=config_value('TAX', 'TAX_CLASS'))
                    rate = self.get_rate(taxclass=tc)
                except:
                    log.error("'Shipping' TaxClass doesn't exist.")

            if rate:
                t = rate * subtotal
            else:
                t = Decimal("0.00")
            
        else:
            t = Decimal("0.00")
        
        return t

    def process(self, order=None):
        """
        Calculate the tax and return it.
        
        Probably need to make a breakout.
        """
        if order:
            self.order = order
        else:
            order = self.order
        
        sub_total = Decimal('0.00')
        taxes = {}
        
        rates = {}
        for item in order.orderitem_set.filter(product__taxable=True):
            tc = item.product.taxClass
            if tc:
                tc_key = tc.title
            else:
                tc_key = "Default"
                
            if rates.has_key(tc_key):
                rate = rates[tc_key]
            else:
                rate = self.get_rate(tc, get_object=True)
                rates[tc_key] = rate
                taxes[tc_key] = Decimal("0.00")
                
            price = item.sub_total
            if rate:
                t = Decimal(price*rate.percentage).quantize(Decimal("0.01"), ROUND_HALF_UP)
            else:
                t = Decimal("0.00")
            sub_total += t
            taxes[tc_key] += t
        
        ship = self.shipping()
        sub_total += ship
        taxes['Shipping'] = ship
        
        for k in taxes:
            taxes[k] = taxes[k]
        
        return sub_total, taxes
