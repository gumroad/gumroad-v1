# Stripe python bindings
# for usage, see example.py
# author: Patrick Collison <patrick@collison.ie>

import urllib2
import urllib # need urlencode

# Python 2.5 and below do not ship with json
__loaded = None
try:
  import json
  __loaded = hasattr(json, 'loads')
except ImportError:
  pass

if not __loaded:
  try:
    import simplejson as json
  except ImportError:
    if __loaded is None:
      raise ImportError("Stripe requires a JSON library, which you do not appear to have.  Please install the simplejson library.  HINT: Try installing the python simplejson library via 'easy_install simplejson', or contact support@stripe.com with questions.")
    else:
      raise ImportError("Stripe requires a JSON library with the same interface as the Python 2.6 'json' library.  You appear to have a 'json' library with a different interface.  Please install the simplejson library.  HINT: Try installing the python simplejson library via 'easy_install simplejson', or contact support@stripe.com with questions.")

class Response(object):
  def __init__(self, d):
    self.dict = d
  
  def __getattr__(self, name):
    return self.dict[name]

class StripeException(Exception):
  def __init__(self, msg):
    self.message = msg
    super(StripeException, self).__init__(msg)
  
  def message(self):
    self.message

class CardException(StripeException):
  def __init__(self, resp):
    self.code = resp.get('code', '')
    self.param = resp.get('param', '')
    super(CardException, self).__init__(resp['message'])

class InvalidRequestException(StripeException):
  def __init__(self, resp):
    self.param = resp.get('param', '')
    super(InvalidRequestException, self).__init__(resp['message'])

class APIException(StripeException):
  pass

class APIConnectionException(StripeException):
  pass

class Client(object):
  API_URL = 'https://api.stripe.com/v1'
  
  def __init__(self, key):
    self.key = key

  def retrieve(self, **params):
    """
    Fetch a charge token representing the supplied transaction as described in params, assuming the transaction has previously been prepared or executed; does not execute the transaction.
    """
    self.__requireParams(params, ['id'])
    return self.__req('retrieve_charge', params)

  def execute(self, **params):
    """
    Execute the described transaction. Transaction is specified either using a charge token or by supplying amount and currency arguments.

      params:
        {
        * amount: integer amount to be charged in cents
        * currency: lowercase 3-character string from set {usd, cad, ars,...} - for full specification see http://en.wikipedia.org/wiki/ISO_4217
        }
        AND
        * card: dictionary object describing card details
        {
          * number: string representing credit card number
          * exp_year: integer representing credit card expiry year
          * exp_month: integer representing credit card expiry month
          *OPTIONAL* name: string representing cardholder name
          *OPTIONAL* address_line_1: string representing cardholder address, line 1
          *OPTIONAL* address_line_2: string representing cardholder address, line 2
          *OPTIONAL* address_zip: string representing cardholder zip
          *OPTIONAL* address_state: string representing cardholder state
          *OPTIONAL* address_country: string representing cardholder country
          *OPTIONAL* cvc: CVC Number
        }
        OR
        * customer: the id of an existing customer
          
    """
    self.__requireParams(params, ['amount', 'currency'])

    return self.__req('execute_charge', params)

  def refund(self, **params):
    """
    Refund a previously executed charge by passing this method the charge token
    """
    self.__requireParams(params, ['id'])
    return self.__req('refund_charge', params)
    
  def createCustomer(self, **params):
    """
    Create a new customer with the given token, and set the supplied
    credit card as the active card to be their active card.
    Used for recurring billing.
    """
    return self.__req('create_customer', params)
    
  def updateCustomer(self, **params):
    """
    Set a credit card as the active card for a given customer. Used for recurring billing.
    """
    self.__requireParams(params, ['id'])
    return self.__req('update_customer', params)

  def billCustomer(self, **params):
    """
    Add a once-off amount to a customer's account. Used for recurring billing.
    """
    self.__requireParams(params, ['id', 'amount'])
    return self.__req('bill_customer', params)
    
  def retrieveCustomer(self, **params):
    """
    Retrieve billing info for the given customer. Used for recurring billing.
    """
    self.__requireParams(params, ['id'])
    return self.__req('retrieve_customer', params)
    
  def deleteCustomer(self, **params):
    """
    Delete the given customer. They will not be charged again, even if their is an outstanding balance on their account.
    """
    self.__requireParams(params, ['id'])
    return self.__req('delete_customer', params)

  def __encodeInner(self, d):
    """
    We want post vars of form:
    {'foo': 'bar', 'nested': {'a': 'b', 'c': 'd'}}
    to become:
    foo=bar&nested[a]=b&nested[c]=d
    """
    stk = []    
    for key, value in d.items():
      if isinstance(value, dict):
        n = {}
        for k, v in value.items():
          n["%s[%s]" % (key, k)] = v
        stk.extend(self.__encodeInner(n))
      else:
        stk.append((key, value))
    return stk

  def __encode(self, d):
    """
    Internal: encode a string for url representation
    """
    return urllib.urlencode(self.__encodeInner(d))

  def __requireParams(self, params, req):
    """
    Internal: strict verification of parameter list
    """
    for r in req:
      if not params.has_key(r):
        raise InvalidRequestException({ 'message' : 'Missing required param: %s' % r })

  def __req(self, meth, params):
    """
    Internal: mechanism for requesting an API call from the pay-server
    """
    params = params.copy()
    params['method'] = meth
    params['key'] = self.key
    params['client'] = {'type':'binding', 'language':'python', 'version':'1.4.5'}
    try:
      c = urllib2.urlopen(self.API_URL, self.__encode(params))
    except urllib2.URLError, e:
      raise APIException("Could not connect to Stripe API: %s" % (e, ))
    resp = json.loads(c.read())

    if resp.get('error'):
        err = {
            'card_error': lambda resp: CardException(resp),
            'invalid_request_error': lambda resp: InvalidRequestException(resp),
            'api_error': lambda resp: APIException(resp['message'])
        }
        raise err[resp['error']['type']](resp['error'])
      
    return Response(resp)