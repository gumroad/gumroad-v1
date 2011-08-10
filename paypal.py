'''
PayPal on Python, v. 0.6

$LastChangedDate: 2010-02-05 09:21:47 -0500 (Fri, 05 Feb 2010) $
$LastChangedRevision: 1871 $

Implements the Paypal NVP interface.
Sample usage:

import paypal
pp = paypal.PayPal(MY_USERNAME, MY_PASSWORD,
                   MY_SIGNATURE)
pp.DoDirectPayment(paymentaction='Sale', ipaddress='1.2.3.4', ...)

See the PayPal NVP documentation for a description of which parameters
are required for each API call.

https://cms.paypal.com/cms_content/US/en_US/files/developer/PP_NVPAPI_DeveloperGuide.pdf

'''

#------------------------------------------------------------------------------
# Changes:
#
# version 0.6:
# * Fix date handling.
# * Change license from Affero GPL to GPL.
# * Implement recurring payments.
# * Implement Fraud Management Filters.
# * Implement reference transactions.

################################################################################
# Copyright 2009 Edmund M. Sullivan, Chicken Wing Software
# www.chickenwingsw.com
#
#     This program is free software: you can redistribute it and/or
#     modify it under the terms of the GNU General Public
#     License as published by the Free Software Foundation, either
#     version 3 of the License, or (at your option) any later version.
#
#     This program is distributed in the hope that it will be useful,
#     but WITHOUT ANY WARRANTY; without even the implied warranty of
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#     GNU General Public License for more details.
#
#     You should have received a copy of the GNU General Public
#     License along with this program.  If not, see
#     <http://www.gnu.org/licenses/>.
################################################################################
    
from urllib import urlopen, urlencode
import cgi
from cgi import parse_qs
from decimal import Decimal
from datetime import date, datetime
import logging

# Uncomment this for some debugging info:
#logging.basicConfig(level=logging.DEBUG)

# These are the example credentials from the PayPal developer site.
PAYPAL_TEST_USERNAME = 'sdk-three_api1.sdk.com'
PAYPAL_TEST_PASSWORD = 'QFZCWN5HZM8VBG7Q'
PAYPAL_TEST_SIGNATURE = 'A-IzJhZZjhg29XQ2qnhapuwxIDzyAZQ92FRP5dqBzVesOkzbdUONzmOU'

PAYPAL_TEST_SIG_URL = 'https://api-3t.sandbox.paypal.com/nvp'
PAYPAL_TEST_CERT_URL = 'https://api.sandbox.paypal.com/nvp'

PAYPAL_SIG_URL = 'https://api-3t.paypal.com/nvp'
PAYPAL_CERT_URL = 'https://api.paypal.com/nvp'

SKIP_AMT_VALIDATION = False

class PayPalException(Exception):
    '''
    An exception for when something goes wrong communicating with
    PayPal.
    '''
    def __init__(self, value):
        self.value = value

    def __str__(self):
        return self.value.__str__()

class ShortDate(object):
    '''
    Represents a short date - just year and month.
    '''
    def __init__(self, year, month):
        self.dateObj = date(year, month, 1)
        
    def __str__(self):
        # Convert to MMYYYY - No day #s required for PayPal credit card dates.
        return self.dateObj.strftime('%m%Y')
        
class Param(object):
    '''
    Represents one parameter to a Paypal NVP call.
    '''
    def __init__(self, name, maxLen=None, paramType=str, optional=False, minLen=None, allowedChars=None,
                 allowedValues=None, validatorFun=None, minAmt=None, maxAmt=None):
        self.name = name
        self.paramType = paramType
        self.maxLen = maxLen
        self.minLen = minLen
        self.allowedChars = allowedChars
        self.optional = optional
        self.allowedValues = allowedValues
        self.validatorFun = validatorFun
        self.minAmt = minAmt
        self.maxAmt = maxAmt
        self.val = None

    def __str__(self):
        return self.name

    def toLongString(self):
        return '%s:%s' % (self.name, self.val)

    def validate(self, value):
        '''
        Checks to make sure value is appropriate for this parameter.
        '''
        if isinstance(value, unicode) and self.paramType is str:
            value = value.encode('utf-8')
        if type(value) is not self.paramType:
            raise PayPalException('Parameter %s incorrect type, wanted %s, got %s' %\
                                      (self.name, self.paramType, type(value)))
        # Convert types
        if self.paramType is bool:
            if value:
                value = '1'
            else:
                value = '0'
        elif self.paramType is date:
            value = datetime(value.year, value.month, value.day).isoformat()

        if self.maxLen != None and len(str(value)) > self.maxLen:
            raise PayPalException('Parameter %s too long' % self.name)
        if self.minLen != None and len(str(value)) < self.minLen:
            raise PayPalException('Parameter %s too short' % self.name)
        
        if self.paramType is int and self.minAmt != None and value < self.minAmt:
            raise PayPalException('Parameter %s below minimum value %s' % (self.name, self.minAmt))
        
        if self.paramType is int and self.maxAmt != None and value > self.maxAmt:
            raise PayPalException('Parameter %s exceeds maximum value %s' % (self.name, self.maxAmt))
        if self.allowedChars != None:
            for ch in value:
                if ch not in self.allowedChars:
                    raise PayPalException('Parameter %s has invalid character' % self.name)
        if self.allowedValues != None and value not in self.allowedValues:
            raise PayPalException('Parameter %s has disallowed value' % self.name)
        if self.validatorFun:
            self.validatorFun(value)
        # All good
        self.val = value

    def __str__(self):
        return str(self.val)

    def __unicode__(self):
        return unicode(self.val)
        

# ES: Go through ParamList fields, checking "optional" value.
class ParamList(Param):
    def validate(self, valueList):
        for val in valueList:
            Param.validate(self, val)

    
# Note: This is limited to US currency
def validateAmt(val):
    '''
    Validates a dollar amount.
    '''
    if SKIP_AMT_VALIDATION:
        return
    if val[-3] != '.':
        raise PayPalException('Amount must have two decimal places')
    # Ignore the optional thousands separator.
    val = val.replace(',', '')
    if Decimal(val) > 10000:
        raise PayPalException('Amount too big')

def validateIp(val):
    '''
    Validates an IP address.
    '''
    nums = val.split('.')
    if len(nums) != 4:
        raise PayPalException('Invalid IP address value (wrong number of dots): %s' % val)
    for numStr in nums:
        try:
            num = int(numStr)
            if num < 0 or num > 255:
                raise PayPalException('Invalid IP address value (%d out of range): %s' % (num, val))
        except ValueError:
            raise PayPalException('Invalid IP address value (%s not an integer): %s' % (numStr, val))

NUMBERS='0123456789'
HEX_DIGITS=NUMBERS+'abcdefABCDEF'
ALPHA='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
ALPHANUM=ALPHA+NUMBERS

def ParamAmt(name='amt', optional=False):
    '''
    Creates a parameter for a dollar amount.
    '''
    # Note: This is limited to US currency
    return Param(name, maxLen=8, allowedChars=NUMBERS+'.,-',
                 validatorFun=validateAmt, optional=optional)

def ParamListAmt(name='amt', optional=False):
    # Note: This is limited to US currency
    return ParamList(name, maxLen=8, allowedChars=NUMBERS+'.,-',
                     validatorFun=validateAmt, optional=optional)

def ParamColor(name, optional=False):
    '''
    Creates a parameter for a color as hex digits.
    '''
    return Param(name, maxLen=6, minLen=6, allowedChars=HEX_DIGITS, optional=optional)

def ParamCurrencyCode(name='currencycode', optional=False):
    '''
    Creates a parameter for a currency code.
    '''
    return Param(name, maxLen=3, optional=optional)
        
# Methods in the PayPal API
METHODS = {
    'AddressVerify': (
        Param('email', maxLen=255),
        Param('street', maxLen=35, allowedChars = ALPHANUM + '-,.#\\ '),
        Param('zip', maxLen=16)
        ),

    'DoCapture': (
        Param('authorizationid', maxLen=19),
        ParamAmt(),
        ParamCurrencyCode(),
        Param('completetype', allowedValues=('Complete', 'NotComplete')),
        Param('invnum', optional=True, maxLen=127, allowedChars=ALPHANUM),
        Param('note', optional=True, maxLen=255),
        Param('softdescriptor', optional=True, allowedChars=ALPHANUM + '-*. ',
              maxLen=18) # Length validation is really more complicated than this.
        ),

    'DoAuthorization': (
        Param('transactionid', maxLen=19),
        ParamAmt(),
        Param('transactionentity', optional=True, allowedValues=('Order')),
        ParamCurrencyCode()
        ),

    'DoReauthorization': (
        Param('authorizationid', maxLen=19),
        ParamAmt(),
        ParamCurrencyCode(),
        ),
    
    'DoVoid': (
        Param('authorizationid', maxLen=19),
        Param('note', optional=True, maxLen=255)
        ),

    'DoDirectPayment': (
        # DoDirectPayment request fields
        Param('paymentaction', optional=True, allowedValues=('Authorization', 'Sale')),
        Param('ipaddress', maxLen=15, validatorFun=validateIp),
        Param('returnfmfdetails', paramType=bool, optional=True),

        # Credit card details fields
        Param('creditcardtype', allowedValues=('Visa',
                                               'MasterCard',
                                               'Discover',
                                               'Amex',
                                               'Maestro', # Only for GBP
                                               'Solo')), # Only for GBP
        Param('acct', allowedChars=NUMBERS), # Complicated validation for CC#.
        Param('expdate', paramType=ShortDate),
        Param('cvv2', optional=True, # Sometimes required.
              allowedChars=NUMBERS, maxLen=4, minLen=3), # 4 for AmEx, 3 otherwise.
        Param('startdate', paramType=ShortDate, optional=True), # Maestro or Solo only
        Param('issuenumber', allowedChars=NUMBERS, maxLen=2, optional=True), # Maestro or Solo only

        # PayerInfo type fields
        # ES: No info in spec on whether these are optional
        Param('email', maxLen=127, optional=True),
        Param('payerid', maxLen=13, optional=True),
        Param('payerstatus', allowedValues=('verified', 'unverified'), optional=True),
        # ES: countrycode is listed twice in spec
        # ES: ??? Param('countrycode', maxLen=2, optional=True),
        Param('business', maxLen=127, optional=True),

        # Payer name fields
        # ES: No info in spec on whether these are optional
        Param('salutation', maxLen=20),
        Param('firstname', maxLen=25),
        Param('middlename', maxLen=25),
        Param('lastname', maxLen=25),
        Param('suffix', maxLen=12),

        # Address fields
        Param('street', maxLen=100),
        Param('street2', maxLen=100, optional=True),
        Param('city', maxLen=40),
        Param('state', maxLen=40),
        Param('countrycode', maxLen=2),
        Param('zip', maxLen=20),
        Param('phonenum', maxLen=20),

        # Payment details type fields
        ParamAmt(),
        ParamCurrencyCode(optional=True),
        ParamAmt('itemamt', True), # Required if you specify l_amt or shippingamt
        ParamAmt('shippingamt', True),
        ParamAmt('insuranceamt', True),
        ParamAmt('shippingdiscount', True),
        ParamAmt('handlingamt', True),
        ParamAmt('taxamt', True),
        Param('desc', maxLen=127, optional=True),
        Param('custom', maxLen=256, optional=True),
        Param('invnum', maxLen=127, optional=True),
        Param('buttonsource', maxLen=32, optional=True),
        Param('notifyurl', maxLen=2048, optional=True),
        
        # Payment details item type fields
        ParamList('name', maxLen=127, optional=True),
        ParamList('desc', maxLen=127, optional=True),
        ParamListAmt(optional=True),
        ParamList('number', maxLen=127, optional=True),
        ParamList('qty', paramType=int, optional=True),
        ParamListAmt('taxamt', True),

        # Ebay item payment details item type fields
        ParamList('ebayitemnumber', maxLen=765, optional=True),
        ParamList('ebayitemauctiontxnid', maxLen=255, optional=True),
        ParamList('ebayitemorderid', maxLen=64, optional=True),

        # Ship to address fields
        Param('shiptoname', maxLen=32, optional=True),
        Param('shiptostreet', maxLen=100),
        Param('shiptostreet2', maxLen=100, optional=True),
        Param('shiptocity', maxLen=40),
        Param('shiptostate', maxLen=40),
        Param('shiptozip', maxLen=20),
        Param('shiptocountrycode', maxLen=2),
        Param('shiptophonenum', maxLen=20, optional=True)
        ),

    'DoNonReferencedCredit': (
        ParamAmt(),
        ParamAmt('netamt', True),
        ParamAmt('shippingamt', True),
        ParamAmt('taxamt', True),
        ParamCurrencyCode(),
        Param('note', optional=True),
        
        # Credit card details fields
        Param('creditcardtype', allowedValues=('Visa',
                                               'MasterCard',
                                               'Discover',
                                               'Amex',
                                               'Maestro', # Only for GBP
                                               'Solo')), # Only for GBP
        Param('acct', allowedChars=NUMBERS), # Complicated validation for CC#.
        Param('expdate', paramType=ShortDate),
        Param('cvv2', optional=True, # Sometimes required.
              allowedChars=NUMBERS, maxLen=4, minLen=3), # 4 for AmEx, 3 otherwise.
        Param('startdate', paramType=ShortDate, optional=True), # Maestro or Solo only
        Param('issuenumber', allowedChars=NUMBERS, maxLen=2, optional=True), # Maestro or Solo only

        # Payer Info Type Fields
        Param('email', maxLen=127, optional=True),
        Param('firstname', maxLen=25),
        Param('lastname', maxLen=25),

        # Address Fields
        Param('street', maxLen=100),
        Param('street2', maxLen=100, optional=True),
        Param('city', maxLen=40),
        Param('state', maxLen=40),
        Param('countrycode', maxLen=2),
        Param('zip', maxLen=20),
        Param('phonenum', maxLen=20)
        ),
    
    'SetExpressCheckout': (
        Param('token', maxLen=20, optional=True),
        ParamAmt(),
        ParamCurrencyCode(optional=True),
        ParamAmt('maxamt', optional=True),
        Param('desc', maxLen=127, optional=True),
        Param('custom', 256, optional=True),
        Param('invnum', 127, optional=True),
        Param('returnurl', 2048),
        Param('cancelurl', 2048),
        Param('reqconfirmshipping', paramType=bool, optional=True),
        Param('noshipping', paramType=bool, optional=True),
        Param('allownote', paramType=bool, optional=True),
        Param('addressoverride', paramType=bool, optional=True),
        Param('localecode', 2, optional=True,
              allowedValues=('AU', 'DE', 'FR', 'IT',
                             'GB', 'ES', 'US')),
        Param('pagestyle', 30, optional=True, allowedChars=ALPHA),
        Param('hdrimg', 127, optional=True),
        ParamColor('hdrbordercolor', optional=True),
        ParamColor('hdrbackcolor', optional=True),
        ParamColor('payflowcolor', optional=True),
        Param('email', 127, optional=True),
        Param('solutiontype', optional=True, allowedValues=('Sole', 'Mark')),
        Param('landingpage', optional=True, allowedValues=('Billing', 'Login')),
        Param('channeltype', optional=True, allowedValues=('Merchant', 'eBayItem')),

        # ES:  Skipping German giropay stuff.

        # ES: These things are duplicated in the spec.
        #ParamList('billingtype'), # For recurring payments, must be set to RecurringPayments
        #ParamList('billingagreementdescription'),
        #ParamList('custom'),
        #ParamList('paymenttype', allowedValues=('Any', 'Instantonly')),
        
        # Address fields
        Param('name', maxLen=32),
        Param('shiptostreet', maxLen=100),
        Param('shiptostreet2', maxLen=100, optional=True),
        Param('shiptocity', maxLen=40),
        Param('shiptostate', maxLen=40),
        Param('shiptozip', maxLen=20),
        Param('shiptocountry', maxLen=2),
        Param('phonenum', maxLen=20, optional=True),
        
        # Payment details type fields
        ParamAmt(),
        ParamCurrencyCode(optional=True),
        ParamAmt('itemamt'),
        ParamAmt('shippingamt', True),
        ParamAmt('insuranceamt', True),
        ParamAmt('shippingdiscount', True),
        ParamAmt('handlingamt', True),
        ParamAmt('taxamt', True),
        Param('desc', maxLen=127, optional=True, allowedChars=ALPHANUM),
        Param('custom', maxLen=256, optional=True, allowedChars=ALPHANUM),
        Param('invnum', maxLen=127, optional=True, allowedChars=ALPHANUM),
        Param('buttonsource', maxLen=32, optional=True, allowedChars=ALPHANUM),
        Param('notifyurl', maxLen=2048, optional=True), # ES: Spec says alphanumeric!
            
        # Payment details item type fields
        ParamList('name', maxLen=127, optional=True),
        ParamList('desc', maxLen=127, optional=True),
        ParamListAmt(optional=True),
        ParamList('number', maxLen=127, optional=True),
        ParamList('qty', paramType=int, optional=True, minAmt=1),
        ParamListAmt('taxamt', optional=True),

        # Ebay item payment details item type fields
        ParamList('ebayitemnumber', maxLen=765, optional=True),
        ParamList('ebayitemauctiontxnid', maxLen=255, optional=True),
        ParamList('ebayitemorderid', maxLen=64, optional=True),

        # Billing agreement details fields
        ParamList('billingtype',
                  allowedValues=('MerchantInitiatedBilling',
                                 'RecurringPayments')),
        ParamList('billingagreementdescription', maxLen=127, optional=True),
        ParamList('paymenttype', allowedValues=('Any', 'InstantOnly'),
                  optional=True),
        ParamList('custom', maxLen=256, optional=True)
        ),

    'GetExpressCheckoutDetails': (
        Param('token', maxLen=20)
        ),

    'DoExpressCheckoutPayment': (
        Param('token', maxLen=20),
        Param('paymentaction', allowedValues=('Authorization',
                                              'Order',
                                              'Sale')),
        Param('payerid', maxLen=13, allowedChars=ALPHANUM),
        Param('returnfmfdetails', paramType=bool, optional=True),

        # Payment details type fields
        ParamAmt(),
        ParamCurrencyCode(),
        ParamAmt('itemamt', True),
        ParamAmt('shippingamt', True),
        ParamAmt('insuranceamt', True),
        ParamAmt('shippingdiscount', True),
        ParamAmt('handlingamt', True),
        ParamAmt('taxamt', True),
        Param('desc', maxLen=127, optional=True, allowedChars=ALPHANUM),
        Param('custom', maxLen=256, optional=True, allowedChars=ALPHANUM),
        Param('invnum', maxLen=127, optional=True, allowedChars=ALPHANUM),
        Param('buttonsource', maxLen=32, optional=True, allowedChars=ALPHANUM),
        Param('notifyurl', maxLen=2048, optional=True), # ES: Spec says alphanumeric!

        # Payment details item type fields
        ParamList('name', maxLen=127, optional=True),
        ParamList('desc', maxLen=127, optional=True),
        ParamListAmt(optional=True),
        ParamList('number', maxLen=127, optional=True),
        ParamList('qty', paramType=int, optional=True, minAmt=1),
        ParamListAmt('taxamt', optional=True),

        # Ebay item payment details item type fields
        ParamList('ebayitemnumber', maxLen=765, optional=True),
        ParamList('ebayitemauctiontxnid', maxLen=255, optional=True),
        ParamList('ebayitemorderid', maxLen=64, optional=True),
        
        # Ship to address fields
        Param('name', maxLen=32),
        Param('shiptostreet', maxLen=100),
        Param('shiptostreet2', maxLen=100, optional=True),
        Param('shiptocity', maxLen=40),
        Param('shiptostate', maxLen=40),
        Param('shiptozip', maxLen=20),
        Param('shiptocountry', maxLen=2),
        Param('phonenum', maxLen=20, optional=True)
        ),

    'GetBalance':(
        Param('returnallcurrencies', paramType=bool, optional=True)
        ),

    'GetTransactionDetails':(
        Param('transactionid', maxLen=17)
        ),

    'MassPay':(
        Param('emailsubject', maxLen=255, optional=True),
        ParamCurrencyCode(),
        Param('receivertype',
              allowedValues=('EmailAddress', 'UserID'), optional=True),
        # MassPay Item type fields
        # Note: Must specify exactly one of email/receiverid.
        ParamList('email', maxLen=127, optional=True),
        ParamList('receiverid', maxLen=17, optional=True),
        ParamListAmt(),
        ParamList('uniqueid', maxLen=30, optional=True),
        ParamList('note', maxLen=4000, optional=True, allowedChars=ALPHANUM)
        ),

    'RefundTransaction':(
        Param('transactionid', maxLen=17),
        Param('refundtype', allowedValues=('Other', 'Full', 'Partial')),
        ParamAmt(optional=True),
        Param('note', maxLen=255, allowedChars=ALPHANUM),
        ),

    'TransactionSearch':(
        Param('startdate', paramType=date),
        Param('enddate', optional=True, paramType=date),
        Param('email', optional=True, maxLen=127), # ES: Spec says alphanumeric
        Param('receiver', optional=True),
        Param('receiptid', optional=True),
        Param('transactionid', optional=True, maxLen=19),
        Param('invnum', optional=True, maxLen=127),
        Param('acct', optional=True, minLen=11, maxLen=25,
              allowedChars=NUMBERS), # ES: Spec says punctuation is ignored. Safer just to omit it.
        Param('auctionitemnumber', optional=True),
        Param('transactionclass', optional=True,
              allowedValues=('All', 'Sent',
                             'Received', 'MassPay',
                             'MoneyRequest',
                             'FundsAdded',
                             'FundsWithdrawn',
                             'Referral',
                             'Fee',
                             'Subscription',
                             'Dividend',
                             'Billpay',
                             'Refund',
                             'CurrencyConversions',
                             'BalanceTransfer',
                             'Reversal',
                             'Shipping',
                             'BalanceAffecting',
                             'ECheck')),
        ParamAmt(optional=True),
        Param('currencycode', optional=True, maxLen=3),
        Param('status', optional=True,
              allowedValues=('Pending',
                             'Processing',
                             'Success',
                             'Denied',
                             'Reversed')),
        # Payer name fields
        Param('salutation', optional=True, maxLen=20),
        Param('firstname', optional=True, maxLen=25),
        Param('middlename', optional=True, maxLen=25),
        Param('lastname', optional=True, maxLen=25),
        Param('suffix', optional=True, maxLen=12),
        
        ),

    ## Recurring payments
    # ES: The spec says method must be 'DoDirectPayment'. I think that's incorrect.
    'CreateRecurringPaymentsProfile':(
        Param('token'),
        # Recurring Payments Profile Details Fields
        Param('subscribername', optional=True, maxLen=32),
        Param('profilestartdate', paramType=date),
        Param('profilereference', optional=True, maxLen=127, allowedChars=ALPHANUM),
        # ScheduleDetails Fields
        Param('desc', maxLen=127, allowedChars=ALPHANUM),
        Param('note', optional=True, maxLen=127, allowedChars=ALPHANUM),
        Param('maxfailedpayments', optional=True, paramType=int),
        Param('autobillamt', optional=True,
              allowedValues=('NoAutoBill', 'AddToNextBilling')),
        # Billing Period Details Type
        Param('billingperiod', allowedValues=('Day', 'Week', 'SemiMonth',
                                              'Month', 'Year')),
        Param('billingfrequency', paramType=int, minAmt=1),
        Param('totalbillingcycles', optional=True, paramType=int),
        ParamAmt(),
        Param('currencycode', optional=True, maxLen=3),
        ParamAmt('shippingamt', True),
        ParamAmt('taxamt', True),
        # Activation Details Type
        ParamAmt('initamt', True),
        Param('failedinitamtaction', optional=True, allowedValues=('ContinueOnFailure',
                                                                   'CancelOnFailure')),
        # Ship To Address Fields
        Param('shiptoname', maxLen=32, optional=True),
        Param('shiptostreet', maxLen=100),
        Param('shiptostreet2', maxLen=100, optional=True),
        Param('shiptocity', maxLen=40),
        Param('shiptostate', maxLen=40),
        Param('shiptozip', maxLen=20),
        Param('shiptocountrycode', maxLen=2),
        Param('shiptophonenum', maxLen=20, optional=True),
        # Credit Card Details Fields
        Param('creditcardtype', allowedValues=('Visa',
                                               'MasterCard',
                                               'Discover',
                                               'Amex',
                                               'Maestro', # Only for GBP
                                               'Solo')), # Only for GBP
        Param('acct', allowedChars=NUMBERS), # Complicated validation for CC#.
        Param('expdate', paramType=ShortDate),
        Param('cvv2', optional=True, # Sometimes required.
              allowedChars=NUMBERS, maxLen=4, minLen=3), # 4 for AmEx, 3 otherwise.
        Param('startdate', paramType=ShortDate, optional=True), # Maestro or Solo only
        Param('issuenumber', allowedChars=NUMBERS, maxLen=2, optional=True), # Maestro or Solo only
        # PayerInfo Type Fields
        Param('email', maxLen=127, optional=True),
        Param('payerid', maxLen=13, allowedChars=ALPHANUM),
        Param('payerstatus', allowedValues=('verified', 'unverified'), optional=True),
        Param('countrycode', maxLen=2),
        Param('business', maxLen=127, optional=True),
        # Payer Name Fields
        # ES: No info in spec on whether these are optional
        Param('salutation', maxLen=20),
        Param('firstname', maxLen=25),
        Param('middlename', maxLen=25),
        Param('lastname', maxLen=25),
        Param('suffix', maxLen=12),
        # Address fields
        Param('street', maxLen=100),
        Param('street2', maxLen=100, optional=True),
        Param('city', maxLen=40),
        Param('state', maxLen=40),
        Param('countrycode', maxLen=2),
        Param('zip', maxLen=20),
        Param('phonenum', maxLen=20),        
        ),

    'GetRecurringPaymentsProfileDetails':(
        Param('profileid', maxLen=19),
        ),

    'ManageRecurringPaymentsProfileStatus':(
        Param('profileid', maxLen=19),
        Param('action', allowedValues=('Cancel', 'Suspend', 'Reactivate')),
        Param('note', optional=True),
        ),

    'BillOutstandingAmount':(
        Param('profileid', maxLen=19),
        ParamAmt(optional=True),
        Param('note', optional=True),
        ),

    'UpdateRecurringPaymentsProfile':(
        Param('profileid', maxLen=19),
        Param('note', optional=True),
        Param('desc', maxLen=127, allowedChars=ALPHANUM),
        Param('subscribername', optional=True, maxLen=32),
        Param('profilereference', optional=True, maxLen=127, allowedChars=ALPHANUM),
        Param('additionalbillingcycles', optional=True, paramType=int),
        ParamAmt(optional=True),
        ParamAmt('shippingamt', True),
        ParamAmt('taxamt', True),
        ParamAmt('outstandingamt', True),
        Param('autobillamt', optional=True,
              allowedValues=('NoAutoBill', 'AddToNextBilling')),
        Param('maxfailedpayments', optional=True, paramType=int),
        # Ship To Address Fields
        Param('shiptoname', maxLen=32, optional=True),
        Param('shiptostreet', maxLen=100),
        Param('shiptostreet2', maxLen=100, optional=True),
        Param('shiptocity', maxLen=40),
        Param('shiptostate', maxLen=40),
        Param('shiptozip', maxLen=20),
        Param('shiptocountrycode', maxLen=2),
        Param('shiptophonenum', maxLen=20, optional=True),
        # Credit Card Details Fields
        Param('creditcardtype', allowedValues=('Visa',
                                               'MasterCard',
                                               'Discover',
                                               'Amex',
                                               'Maestro', # Only for GBP
                                               'Solo')), # Only for GBP
        Param('acct', allowedChars=NUMBERS), # Complicated validation for CC#.
        Param('expdate', paramType=ShortDate),
        Param('cvv2', optional=True, # Sometimes required.
              allowedChars=NUMBERS, maxLen=4, minLen=3), # 4 for AmEx, 3 otherwise.
        Param('startdate', paramType=ShortDate, optional=True), # Maestro or Solo only
        Param('issuenumber', allowedChars=NUMBERS, maxLen=2, optional=True), # Maestro or Solo only
        # Payer Info Type Fields
        Param('email', maxLen=127, optional=True),
        Param('firstname', maxLen=25),
        Param('lastname', maxLen=25),
        # Address fields
        Param('street', maxLen=100),
        Param('street2', maxLen=100, optional=True),
        Param('city', maxLen=40),
        Param('state', maxLen=40),
        Param('countrycode', maxLen=2),
        Param('zip', maxLen=20),
        Param('phonenum', maxLen=20),
        ),

    'SetCustomerBillingAgreement':(
        Param('returnurl'),
        Param('cancelurl'),
        Param('localecode', 2, optional=True,
              allowedValues=('AU', 'DE', 'FR', 'IT',
                             'GB', 'ES', 'US')),
        Param('pagestyle', optional=True, maxLen=30, allowedChars=ALPHA),
        Param('hdriimg', optional=True, maxLen=127), # ES: Spec says alphanumeric.
        ParamColor('hdrbordercolor', optional=True),
        ParamColor('hdrbackcolor', optional=True),
        ParamColor('payflowcolor', optional=True),
        Param('email', 127, optional=True), # ES: Spec says alphanumeric
        Param('billingtype',
              allowedValues=('MerchantInitiatedBilling',
                             'RecurringPayments')),
        Param('billingagreementdescription', maxLen=127, optional=True),
        Param('paymenttype', allowedValues=('Any', 'InstantOnly'),
              optional=True),
        Param('billingagreementcustom', maxLen=256, optional=True),
        ),

    'GetBillingAgreementCustomerDetails':(
        Param('token', maxLen=20),
        ),

    'DoReferenceTransaction':(
        # DoReferenceTransaction Request Fields
        Param('referenceid'),
        Param('paymentaction', optional=True, allowedValues=('Authorization',
                                                             'Sale')),
        Param('returnfmfdetails', optional=True, paramType=bool),
        Param('softdescriptor', optional=True, allowedChars=ALPHANUM + '-*. ',
              maxLen=18), # Length validation is really more complicated than this.
        # Ship To Address Fields
        Param('shiptoname', maxLen=32, optional=True),
        Param('shiptostreet', maxLen=100),
        Param('shiptostreet2', maxLen=100, optional=True),
        Param('shiptocity', maxLen=40),
        Param('shiptostate', maxLen=40),
        Param('shiptozip', maxLen=20),
        Param('shiptocountrycode', maxLen=2),
        Param('shiptophonenum', maxLen=20, optional=True),
        # Payment Details Fields
        ParamAmt(),
        ParamCurrencyCode(optional=True),
        ParamAmt('itemamt', True), # Required if you specify l_amt or shippingamt
        ParamAmt('shippingamt', True),
        ParamAmt('insuranceamt', True),
        ParamAmt('shippingdiscount', True),
        ParamAmt('handlingamt', True),
        ParamAmt('taxamt', True),
        Param('desc', maxLen=127, optional=True),
        Param('custom', maxLen=256, optional=True),
        Param('invnum', maxLen=127, optional=True),
        Param('buttonsource', maxLen=32, optional=True),
        Param('notifyurl', maxLen=2048, optional=True),
        # Payment Item Details Fields
        ParamList('name', maxLen=127, optional=True),
        ParamList('desc', maxLen=127, optional=True),
        ParamListAmt(optional=True),
        ParamList('number', maxLen=127, optional=True),
        ParamList('qty', paramType=int, optional=True),
        ParamListAmt('taxamt', True),
        # Ebay Payment Detail Item Fields
        ParamList('ebayitemnumber', maxLen=765, optional=True),
        ParamList('ebayitemauctiontxnid', maxLen=255, optional=True),
        ParamList('ebayitemorderid', maxLen=64, optional=True),
        # Credit Card Fields
        Param('creditcardtype', allowedValues=('Visa',
                                               'MasterCard',
                                               'Discover',
                                               'Amex',
                                               'Maestro', # Only for GBP
                                               'Solo')), # Only for GBP
        Param('acct', allowedChars=NUMBERS), # Complicated validation for CC#.
        Param('expdate', paramType=ShortDate),
        Param('cvv2', optional=True, # Sometimes required.
              allowedChars=NUMBERS, maxLen=4, minLen=3), # 4 for AmEx, 3 otherwise.
        Param('startdate', paramType=ShortDate, optional=True), # Maestro or Solo only
        Param('issuenumber', allowedChars=NUMBERS, maxLen=2, optional=True), # Maestro or Solo only
        # Payer Information Fields
        Param('email', maxLen=127, optional=True),
        Param('firstname', maxLen=25),
        Param('lastname', maxLen=25),
        # Billing Address Fields
        Param('street', maxLen=100),
        Param('street2', maxLen=100, optional=True),
        Param('city', maxLen=40),
        Param('state', maxLen=40),
        Param('countrycode', maxLen=2),
        Param('zip', maxLen=20),
        Param('phonenum', maxLen=20),
        ),

    'ManagePendingTransactionStatus':(
        Param('transactionid'),
        Param('action', allowedValues=('Accept', 'Deny')),
        ),
    }

class PayPal(object):
    '''
    The main class for the PayPal NVP interface.
    '''
    def __init__(self, userName, password, signature, apiUrl=PAYPAL_SIG_URL):
        self.userName = userName
        self.password = password
        self.signature = signature
        self.apiUrl = apiUrl

    def __getattr__(self, name):
        try:
            method = METHODS[name]
        except:
            raise AttributeError
        def callable(*args, **kwargs):
            self.validateCall(name, method, **kwargs)
            return self.makeCall(name, method)
        return callable
            
    def validateCall(self, methodName, method, **kwparams):
        logging.debug('validateCall: len(method) %d' % len(method))
        # method is a list of params.
        # Make sure all required params are present, in the right format
        #goodParams = {}
        for p in method:
            logging.debug('checking for param %s (type %s)' % (p.name, p.paramType))
            # ES: Make all this logic part of Param/ParamList object???
            if type(p) is Param:
                if p.name not in kwparams:
                    if not p.optional:
                        raise PayPalException('Missing required parameter to %s: %s' % (methodName, p.name))
                    else:
                        continue
                logging.debug('validateCall: before: %s' % kwparams[p.name])
                p.validate(kwparams[p.name])
                logging.debug('validateCall: after: %s, p is %s' % (kwparams[p.name], p))
                #goodParams[p.name] = kwparams[p.name]
                del(kwparams[p.name])
            elif type(p) is ParamList:
                i = 0
                paramName = 'l_%s%d' % (p.name, i)
                while paramName in kwparams:
                    p.validate(kwparams[paramName])
                    #goodParams[paramName] = kwparams[paramName]
                    del(kwparams[paramName])
                    i += 1
                    paramName = 'l_%s%d' % (p.name, i)
        if len(kwparams) != 0:
            raise PayPalException('Extra parameters to %s: %s' % (methodName, ','.join([str(k) for k in kwparams.keys()])))
    

    def makeCall(self, methodName, method):
        logging.debug('makeCall: method is %s' % ', '.join([p.toLongString() for p in method]))
        params = dict([(p.name, p.val) for p in method if p.val is not None])
        params['method'] = methodName
        params['user'] = self.userName
        params['pwd'] = self.password
        params['version'] = '3.2'
        if self.signature:
            params['signature'] = self.signature
        else:
            params['certificate'] = self.certificate
        paramString = urlencode(params)
        logging.debug('Making PayPal call with paramString: %s' % paramString)
        response = urlopen(self.apiUrl, paramString).read()
        parsedResponse = cgi.parse_qs(response)
        logging.debug('Got PayPal response with ACK %s: %s' % (parsedResponse['ACK'], response))
        if parsedResponse['ACK'][0] not in ('Success', 'SuccessWithWarning'):
            raise PayPalException(getMultipleVals(parsedResponse, 'LONGMESSAGE'))
        return parsedResponse

def getMultipleVals(resp, valName):
    ret = []
    index = 0
    while True:
        itemName = 'L_%s%s' % (valName, index)
        if not itemName in resp:
            break
        ret.extend(resp[itemName])
        index += 1
    return ret

def creditCardTypeFromNumber(numStringIn):
    # Filter out non-digits
    numString = ''
    for ch in numStringIn:
        if ch.isdigit():
            numString += ch
    if len(numString) in (13, 16) and numString[0] == '4':
        return 'Visa'
    if len(numString) == 16 and numString[0] == '5' and numString[1] in '12345':
        return 'MasterCard'
    if len(numString) == 15 and numString[0] == '3' and numString[1] in '47':
        return 'Amex'
    if len(numString) == 16 and numString[0:4] == '6011':
        return 'Discover'
    # TODO: Handle Maestro and Solo
    return None


################################################################################
## Some values for Django forms use.

COUNTRY_CODES = (("US", "United States"),
                 ("AL", "Albania"),
                 ("DZ", "Algeria"),
                 ("AD", "Andorra"),
                 ("AO", "Angola"),
                 ("AI", "Anguilla"),
                 ("AG", "Antigua and Barbuda"),
                 ("AR", "Argentina"),
                 ("AM", "Armenia"),
                 ("AW", "Aruba"),
                 ("AU", "Australia"),
                 ("AT", "Austria"),
                 ("AZ", "Azerbaijan Republic"),
                 ("BS", "Bahamas"),
                 ("BH", "Bahrain"),
                 ("BB", "Barbados"),
                 ("BE", "Belgium"),
                 ("BZ", "Belize"),
                 ("BJ", "Benin"),
                 ("BM", "Bermuda"),
                 ("BT", "Bhutan"),
                 ("BO", "Bolivia"),
                 ("BA", "Bosnia and Herzegovina"),
                 ("BW", "Botswana"),
                 ("BR", "Brazil"),
                 ("VG", "British Virgin Islands"),
                 ("BN", "Brunei"),
                 ("BG", "Bulgaria"),
                 ("BF", "Burkina Faso"),
                 ("BI", "Burundi"),
                 ("KH", "Cambodia"),
                 ("CA", "Canada"),
                 ("CV", "Cape Verde"),
                 ("KY", "Cayman Islands"),
                 ("TD", "Chad"),
                 ("CL", "Chile"),
                 ("C2", "China"),
                 ("CO", "Colombia"),
                 ("KM", "Comoros"),
                 ("CK", "Cook Islands"),
                 ("CR", "Costa Rica"),
                 ("HR", "Croatia"),
                 ("CY", "Cyprus"),
                 ("CZ", "Czech Republic"),
                 ("CD", "Democratic Republic of the Congo"),
                 ("DK", "Denmark"),
                 ("DJ", "Djibouti"),
                 ("DM", "Dominica"),
                 ("DO", "Dominican Republic"),
                 ("EC", "Ecuador"),
                 ("SV", "El Salvador"),
                 ("ER", "Eritrea"),
                 ("EE", "Estonia"),
                 ("ET", "Ethiopia"),
                 ("FK", "Falkland Islands"),
                 ("FO", "Faroe Islands"),
                 ("FM", "Federated States of Micronesia"),
                 ("FJ", "Fiji"),
                 ("FI", "Finland"),
                 ("FR", "France"),
                 ("GF", "French Guiana"),
                 ("PF", "French Polynesia"),
                 ("GA", "Gabon Republic"),
                 ("GM", "Gambia"),
                 ("DE", "Germany"),
                 ("GI", "Gibraltar"),
                 ("GR", "Greece"),
                 ("GL", "Greenland"),
                 ("GD", "Grenada"),
                 ("GP", "Guadeloupe"),
                 ("GT", "Guatemala"),
                 ("GN", "Guinea"),
                 ("GW", "Guinea Bissau"),
                 ("GY", "Guyana"),
                 ("HN", "Honduras"),
                 ("HK", "Hong Kong"),
                 ("HU", "Hungary"),
                 ("IS", "Iceland"),
                 ("IN", "India"),
                 ("ID", "Indonesia"),
                 ("IE", "Ireland"),
                 ("IL", "Israel"),
                 ("IT", "Italy"),
                 ("JM", "Jamaica"),
                 ("JP", "Japan"),
                 ("JO", "Jordan"),
                 ("KZ", "Kazakhstan"),
                 ("KE", "Kenya"),
                 ("KI", "Kiribati"),
                 ("KW", "Kuwait"),
                 ("KG", "Kyrgyzstan"),
                 ("LA", "Laos"),
                 ("LV", "Latvia"),
                 ("LS", "Lesotho"),
                 ("LI", "Liechtenstein"),
                 ("LT", "Lithuania"),
                 ("LU", "Luxembourg"),
                 ("MG", "Madagascar"),
                 ("MW", "Malawi"),
                 ("MY", "Malaysia"),
                 ("MV", "Maldives"),
                 ("ML", "Mali"),
                 ("MT", "Malta"),
                 ("MH", "Marshall Islands"),
                 ("MQ", "Martinique"),
                 ("MR", "Mauritania"),
                 ("MU", "Mauritius"),
                 ("YT", "Mayotte"),
                 ("MX", "Mexico"),
                 ("MN", "Mongolia"),
                 ("MS", "Montserrat"),
                 ("MA", "Morocco"),
                 ("MZ", "Mozambique"),
                 ("NA", "Namibia"),
                 ("NR", "Nauru"),
                 ("NP", "Nepal"),
                 ("NL", "Netherlands"),
                 ("AN", "Netherlands Antilles"),
                 ("NC", "New Caledonia"),
                 ("NZ", "New Zealand"),
                 ("NI", "Nicaragua"),
                 ("NE", "Niger"),
                 ("NU", "Niue"),
                 ("NF", "Norfolk Island"),
                 ("NO", "Norway"),
                 ("OM", "Oman"),
                 ("PW", "Palau"),
                 ("PA", "Panama"),
                 ("PG", "Papua New Guinea"),
                 ("PE", "Peru"),
                 ("PH", "Philippines"),
                 ("PN", "Pitcairn Islands"),
                 ("PL", "Poland"),
                 ("PT", "Portugal"),
                 ("QA", "Qatar"),
                 ("CG", "Republic of the Congo"),
                 ("RE", "Reunion"),
                 ("RO", "Romania"),
                 ("RU", "Russia"),
                 ("RW", "Rwanda"),
                 ("VC", "Saint Vincent and the Grenadines"),
                 ("WS", "Samoa"),
                 ("SM", "San Marino"),
                 ("ST", "Sao Tome and Principe"),
                 ("SA", "Saudi Arabia"),
                 ("SN", "Senegal"),
                 ("SC", "Seychelles"),
                 ("SL", "Sierra Leone"),
                 ("SG", "Singapore"),
                 ("SK", "Slovakia"),
                 ("SI", "Slovenia"),
                 ("SB", "Solomon Islands"),
                 ("SO", "Somalia"),
                 ("ZA", "South Africa"),
                 ("KR", "South Korea"),
                 ("ES", "Spain"),
                 ("LK", "Sri Lanka"),
                 ("SH", "St. Helena"),
                 ("KN", "St. Kitts and Nevis"),
                 ("LC", "St. Lucia"),
                 ("PM", "St. Pierre and Miquelon"),
                 ("SR", "Suriname"),
                 ("SJ", "Svalbard and Jan Mayen Islands"),
                 ("SZ", "Swaziland"),
                 ("SE", "Sweden"),
                 ("CH", "Switzerland"),
                 ("TW", "Taiwan"),
                 ("TJ", "Tajikistan"),
                 ("TZ", "Tanzania"),
                 ("TH", "Thailand"),
                 ("TG", "Togo"),
                 ("TO", "Tonga"),
                 ("TT", "Trinidad and Tobago"),
                 ("TN", "Tunisia"),
                 ("TR", "Turkey"),
                 ("TM", "Turkmenistan"),
                 ("TC", "Turks and Caicos Islands"),
                 ("TV", "Tuvalu"),
                 ("UG", "Uganda"),
                 ("UA", "Ukraine"),
                 ("AE", "United Arab Emirates"),
                 ("GB", "United Kingdom"),
                 ("UY", "Uruguay"),
                 ("VU", "Vanuatu"),
                 ("VA", "Vatican City State"),
                 ("VE", "Venezuela"),
                 ("VN", "Vietnam"),
                 ("WF", "Wallis and Futuna Islands"),
                 ("YE", "Yemen"),
                 ("ZM", "Zambia"))

STATE_CODES = (("AK", "AK"),
               ("AL", "AL"),
               ("AR", "AR"),
               ("AZ", "AZ"),
               ("CA", "CA"),
               ("CO", "CO"),
               ("CT", "CT"),
               ("DC", "DC"),
               ("DE", "DE"),
               ("FL", "FL"),
               ("GA", "GA"),
               ("HI", "HI"),
               ("IA", "IA"),
               ("ID", "ID"),
               ("IL", "IL"),
               ("IN", "IN"),
               ("KS", "KS"),
               ("KY", "KY"),
               ("LA", "LA"),
               ("MA", "MA"),
               ("MD", "MD"),
               ("ME", "ME"),
               ("MI", "MI"),
               ("MN", "MN"),
               ("MO", "MO"),
               ("MS", "MS"),
               ("MT", "MT"),
               ("NC", "NC"),
               ("ND", "ND"),
               ("NE", "NE"),
               ("NH", "NH"),
               ("NJ", "NJ"),
               ("NM", "NM"),
               ("NV", "NV"),
               ("NY", "NY"),
               ("OH", "OH"),
               ("OK", "OK"),
               ("OR", "OR"),
               ("PA", "PA"),
               ("RI", "RI"),
               ("SC", "SC"),
               ("SD", "SD"),
               ("TN", "TN"),
               ("TX", "TX"),
               ("UT", "UT"),
               ("VA", "VA"),
               ("VT", "VT"),
               ("WA", "WA"),
               ("WI", "WI"),
               ("WV", "WV"),
               ("WY", "WY"),
               ("AA", "AA"),
               ("AE", "AE"),
               ("AP", "AP"),
               ("AS", "AS"),
               ("FM", "FM"),
               ("GU", "GU"),
               ("MH", "MH"),
               ("MP", "MP"),
               ("PR", "PR"),
               ("PW", "PW"),
               ("VI", "VI"))

PROVINCE_CODES = (("Alberta", "Alberta"),
                  ("British Columbia", "British Columbia"),
                  ("Manitoba", "Manitoba"),
                  ("New Brunswick", "New Brunswick"),
                  ("Newfoundland", "Newfoundland and Labrador"),
                  ("Nova Scotia", "Nova Scotia"),
                  ("Nunavut", "Nunavut"),
                  ("Northwest Territories", "Northwest Territories"),
                  ("Ontario", "Ontario"),
                  ("Prince Edward Island", "Prince Edward Island"),
                  ("Quebec", "Quebec"),
                  ("Saskatchewan", "Saskatchewan"),
                  ("Yukon", "Yukon"))


def testPayPal(ccNum):
    pp = PayPal(PAYPAL_TEST_USERNAME, PAYPAL_TEST_PASSWORD,
                PAYPAL_TEST_SIGNATURE, PAYPAL_TEST_SIG_URL)
    resp = pp.DoDirectPayment(paymentaction='Sale',
                              ipaddress='192.168.1.1',
                              creditcardtype='Visa',
                              acct=ccNum, # From Sandbox account
                              expdate=ShortDate(2018, 4),
                              cvv2='111',
                              salutation='',
                              firstname='Homer',
                              middlename='J',
                              lastname='Simpson',
                              suffix='',
                              street='300 Evergreen Terrace.',
                              city='Springfield',
                              state='CA',
                              countrycode='US',
                              zip='94131',
                              phonenum='123-456-7890',
                              amt='100.00',
                              currencycode='USD',
                              shiptostreet='',
                              shiptocity='',
                              shiptostate='',
                              shiptozip='',
                              shiptocountrycode='')
    logging.info('testPayPal: got response %s' % resp)

def usage():
    print >> sys.stderr, "Provide sandbox credit card # on command line."
    print >> sys.stderr, "Possible option: -d: Turn on debugging."
    sys.exit(1)
    
if __name__ == '__main__':
    import sys
    ccNum = None
    for a in sys.argv[1:]:
        if a == '-d':
            # Turn on debugging.
            logging.basicConfig(level=logging.DEBUG)
        elif a.isdigit():
            ccNum = a
        else:
            print >> sys.stderr, 'Invalid option: "%s"' % a
            usage()
    if not ccNum:
        usage()
    testPayPal(ccNum)
