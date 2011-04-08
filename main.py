import cgi
import os
import sys
import random
import string
import urllib
import unicodedata
import logging
import datetime
import re
import collections
import base64
import urllib2
from cStringIO import StringIO

from google.appengine.ext import webapp
from google.appengine.ext.webapp import util
from google.appengine.ext.webapp import template
from google.appengine.api import users
from google.appengine.api import urlfetch
from google.appengine.ext.webapp.util import run_wsgi_app
from django.utils import simplejson as json
from google.appengine.ext import db
from appengine_utilities import sessions
from hashlib import sha256

import stripe

from utils import post_multipart

class Link(db.Model):
    owner = db.StringProperty(required=True)
    name = db.StringProperty(required=True)
    unique_permalink = db.StringProperty(required=True)
    url = db.StringProperty(required=True)
    description = db.StringProperty(multiline=True)
    price = db.FloatProperty(required=True, default=1.00)
    create_date = db.DateTimeProperty(auto_now_add=True)
    length_of_exclusivity = db.IntegerProperty(default=0)
    number_of_paid_downloads = db.IntegerProperty(default=0)
    number_of_downloads = db.IntegerProperty(default=0)
    number_of_views = db.IntegerProperty(default=0)
    balance = db.FloatProperty(default=0.00)

class Purchase(db.Model):
    owner = db.StringProperty(required=True)
    unique_permalink = db.StringProperty(required=True)
    price = db.FloatProperty(required=True)
    create_date = db.DateTimeProperty(auto_now_add=True)

class Permalink(db.Model):
    permalink = db.StringProperty(required=True)

class User(db.Model):
    email = db.StringProperty(required=True)
    payment_address = db.StringProperty()
    name = db.StringProperty()
    password = db.StringProperty(required=True)
    create_date = db.DateTimeProperty(auto_now_add=True)
    balance = db.FloatProperty(default=0.00)

class MainHandler(webapp.RequestHandler):
    def get(self):
		
        if is_logged_in():
            self.redirect("/home")
		
        template_values = {
	        'show_login_link': True,
		}
		
        path = os.path.join(os.path.dirname(__file__), 'templates/index.html')
        self.response.out.write(template.render(path, template_values))
    
    def post(self):
        request = self.request
        email = cgi.escape(self.request.get('email'))
        password = cgi.escape(self.request.get('password'))
        
        if not email or not password:
	        error_message = 'Fill in the form please!'
	        success = False
        else:
            users_from_db = db.GqlQuery("SELECT * FROM User WHERE email = :email", email = email)
            if users_from_db.count() == 0:
                user = User(email=email, password=sha256(password).hexdigest())
                user.number_of_links = 0
                user.balance = 0.00
                user.put()
                
                s = sessions.Session()
                s["user"] = email
                
                success = True
            else:
    	        error_message = 'That email is already taken, sorry!'
    	        success = False
        
        if success:
            self.redirect("/home")
    	else:
            template_values = {
		        'show_login_link': True,
		        'show_error': True,
		        'email_address': email,
		        'body_id': 'index',
		        'error_message': error_message
		        }
            
            path = os.path.join(os.path.dirname(__file__), 'templates/index.html')
            self.response.out.write(template.render(path, template_values))

# Authentication methods!
def is_logged_in():
    try:
        s = sessions.Session()
        return s.has_key("user")
    except:
        False

def get_user():
    try:
        s = sessions.Session()
        return s["user"] if s.has_key("user") else None
    except:
        None

#Helper methods!
def formatted_price(price):
    return "%.2f" % price
    
def plural(int):
    if int == 1:
        return ''
    else:
        return 's'
    
def link_to_share(unique_permalink):
    return 'http://gumroad.com/l/' + unique_permalink
    #return 'https://gumroad.appspot.com/l/' + unique_permalink

class LogoutHandler(webapp.RequestHandler):
    def get(self):
        s = sessions.Session()
        s.delete()
        
        self.redirect("/")
        
class LoginHandler(webapp.RequestHandler):
    def get(self):
        		
        if is_logged_in():
            self.redirect("/home")
		
        template_values = {
		    'show_login_link': False,
	        'body_id': 'login',
	        'title': 'Gumroad / Login'
		}
		
        path = os.path.join(os.path.dirname(__file__), 'templates/login.html')
        self.response.out.write(template.render(path, template_values))
    
    def post(self):
        request = self.request
        email = cgi.escape(self.request.get('email'))
        password = cgi.escape(self.request.get('password'))
        
        if not email or not password:
            success = False
            error_message = 'Fill in the form please!'
        else:	        
            users_from_db = db.GqlQuery("SELECT * FROM User WHERE email = :email", email = email)
            if users_from_db.count() == 0:
                error_message = "That email address isn't being used!"
                success = False
            else:
                user_from_db = users_from_db.get()
                
                if sha256(password).hexdigest() == user_from_db.password:
                    s = sessions.Session()
                    s["user"] = email
                    success = True                    
                else:
                    success = False
                    error_message = "Wrong credentials, please try again!"
        
        if success:
            self.redirect("/home")
    	else:
            template_values = {
		        'show_login_link': False,
		        'show_error': True,
		        'email_address': email,
		        'body_id': 'login',
		        'error_message': error_message
		        }
            
            path = os.path.join(os.path.dirname(__file__), 'templates/login.html')
            self.response.out.write(template.render(path, template_values))

class HomeHandler(webapp.RequestHandler):
    def get(self):
        		
        email = get_user()
        links = []
        
        if not email:
            self.redirect("/")
        else:
            user = db.GqlQuery("SELECT * FROM User WHERE email = :email", email = email).get()
            if not user:
                self.redirect("/")
            links = db.GqlQuery("SELECT * FROM Link WHERE owner = :email", email = email).fetch(999)

            seven_days_ago = datetime.date.today() - datetime.timedelta(7)
            month_ago = datetime.date.today() - datetime.timedelta(30)

            seven_days_purchases = db.GqlQuery("SELECT * FROM Purchase WHERE owner = :email AND create_date >= :seven_days_ago", email = email, seven_days_ago = seven_days_ago).fetch(99999)
            month_purchases = db.GqlQuery("SELECT * FROM Purchase WHERE owner = :email AND create_date >= :month_ago ", email = email, month_ago = month_ago).fetch(99999)
            all_purchases = db.GqlQuery("SELECT * FROM Purchase WHERE owner = :email", email = email).fetch(99999)

            last_seven_days_purchase_total = 0
            last_seven_days_purchase_total = sum(purchase.price for purchase in seven_days_purchases)

            last_month_purchase_total = 0
            last_month_purchase_total = sum(purchase.price for purchase in month_purchases) 

            purchase_total = 0
            purchase_total = sum(purchase.price for purchase in all_purchases)
            
            bins = {}
            for purchase in month_purchases:
                bins.setdefault(purchase.create_date.date(), []).append(purchase)            
            
            counts = collections.defaultdict(int)
            for purchase in seven_days_purchases:
                counts[purchase.create_date.date()] += 1
            
            chart_numbers = []
            
            for k, v in counts.iteritems():
                chart_numbers.append(v)
            
            chart_numbers[0:14]
            
            if len(chart_numbers) > 0:
                chart_max = int(1.2*float(max(chart_numbers)))
                show_chart = True
            else:
                chart_max = 0
                show_chart = False
            
            chart_numbers = ",".join([str(x) for x in chart_numbers])
            
            s = plural(len(chart_numbers))
            
            template_values = {
	            'show_login_link': False,
	            'show_chart': show_chart,
    	        'logged_in': True,
    	        'body_id': 'home',
    	        'user_email': email,
    	        'number_of_links': len(links),
    	        'links': links,
    	        'purchases': all_purchases,
    	        'number_of_days': len(chart_numbers),
    	        's': s,
    	        'chart_numbers': chart_numbers,
    	        'chart_max': chart_max,
    	        'last_seven_days_purchase_total': formatted_price(last_seven_days_purchase_total),
    	        'last_month_purchase_total': formatted_price(last_month_purchase_total),
    	        'purchase_total': formatted_price(purchase_total),
    	        'title': 'Gumroad / Home',
    	        'user_balance': formatted_price(user.balance)
    		}
		
            path = os.path.join(os.path.dirname(__file__), 'templates/home.html')
            self.response.out.write(template.render(path, template_values))

class DeleteHandler(webapp.RequestHandler):
    def get(self, permalink):
        self.redirect("/")
    def post(self, permalink):
        email = get_user()

        if not email:
            self.redirect("/")
        else:
            user = db.GqlQuery("SELECT * FROM User WHERE email = :email", email = email).get()
            link = db.GqlQuery("SELECT * FROM Link WHERE unique_permalink = :permalink", permalink = permalink).get()
            db.delete(link)
        
        self.redirect("/")
    
class EditLinkHandler(webapp.RequestHandler):
    def get(self, permalink):
        email = get_user()

        if not email:
            self.redirect("/")
        else:
            links = db.GqlQuery("SELECT * FROM Link WHERE owner = :email", email = email).fetch(999)
            user = db.GqlQuery("SELECT * FROM User WHERE email = :email", email = email).get()
            link = db.GqlQuery("SELECT * FROM Link WHERE unique_permalink = :permalink", permalink = permalink).get()
            
            if not link or not link.owner == email:
                self.redirect("/home")
            else:
                
                if link.number_of_views > 0:
                    conversion = 100.0*link.number_of_downloads//link.number_of_views
                    hundred_minus_conversion = 100.0-conversion
                else:
                    conversion = 0
                    hundred_minus_conversion = 100.0
                    
                template_values = {
                    'name': link.name,
                    'url_encoded_name': urllib.quote(link.name),
                    'link_to_share': link_to_share(permalink),
                    'price': '$' + formatted_price(link.price),
                    'views': link.number_of_views,
                    'number_of_downloads': link.number_of_downloads,
                    'total_profit': '$' + formatted_price(link.balance),
                    'conversion': conversion,
                    'hundred_minus_conversion': hundred_minus_conversion,
                    'url': link.url,
                    'description': link.description,
        	        'show_login_link': False,
        	        'editing': True,
        	        'permalink': permalink,
        	        'logged_in': True,
        	        'body_id': 'home',
        	        'user_email': email,
        	        'number_of_links': len(links),
        	        'links': links,
        	        'title': 'Gumroad / ' + link.name,
        	        'user_balance': formatted_price(user.balance)
        		}

                path = os.path.join(os.path.dirname(__file__), 'templates/link.html')
                self.response.out.write(template.render(path, template_values))
        
    def post(self, permalink):
        email = get_user()
    
        if not email:
            self.redirect("/")
        else:
            user = db.GqlQuery("SELECT * FROM User WHERE email = :email", email = email).get()
            links = db.GqlQuery("SELECT * FROM Link WHERE owner = :email", email = email).fetch(999)

        request = self.request
        name = cgi.escape(self.request.get('name'))
        price = cgi.escape(self.request.get('price'))
        non_decimal = re.compile(r'[^\d.]+')
        price = non_decimal.sub('', price)
        logging.debug(price)
        
        if float(price) < 0.99 and not float(price) == 0:
            price = str(0.99)
        
        url = cgi.escape(self.request.get('url'))
        description = cgi.escape(self.request.get('description'))

        success = False

        if not name or not price or not url:
            error_message = 'Fill in the whole form please!'
            success = False
        else:
            if eval(price) > 999:
                error_message = 'We don\'t support prices that high yet!'
    	        success = False
    	    else:
                price = '%.3g' % (eval(price))

                link = db.GqlQuery("SELECT * FROM Link WHERE unique_permalink = :permalink", permalink = permalink).get()
                
                if not link.owner == email:
                    self.redirect("/home")
                    success = False
                else:                    
                    link.owner = email
                    link.name = name
                    link.description = description
                    link.url = url
                    link.price = float(price)
                    link.put()    
                    success = True

        if success:
            self.redirect("/" + permalink)
    	else:
            template_values = {
    	        'name': name,
                'url_encoded_name': urllib.quote(name),
    	        'price': '$' + price,
    	        'url': url,
    	        'description': description,
                'link_to_share': link_to_share(permalink),
    	        'show_login_link': False,
    	        'editing': True,
    	        'permalink': permalink,
    	        'logged_in': True,
    	        'body_id': 'home',
    	        'user_email': email,
    	        'number_of_links': len(links),
    	        'links': links,
    	        'title': 'Gumroad / Edit Link',
    	        'user_balance': formatted_price(user.balance),
    	        'show_error': True,
    	        'error_message': error_message
    	        }

            path = os.path.join(os.path.dirname(__file__), 'templates/link.html')
            self.response.out.write(template.render(path, template_values))

class FileUploadHandler(webapp.RequestHandler):
    def get(self):
        self.redirect("/home")
        
    def post(self):
        random_id = "".join([random.choice(string.letters[:26]) for i in xrange(6)])
        
        logging.debug(self.request.arguments())
        	
        result = post_multipart("api.letscrate.com", "/1/files/upload.json", [("crate_id", '14270')], [("file", random_id + str(self.request.get('qqfile')), self.request.body_file.read())])

        self.response.headers['Content-Type'] = 'application/json'
        self.response.out.write(json.dumps(result))

class AddLinkHandler(webapp.RequestHandler):
    def get(self):
        email = get_user()

        links = []
        
        if not email:
            self.redirect("/home")
        else:
            user = db.GqlQuery("SELECT * FROM User WHERE email = :email", email = email).get()
            links = db.GqlQuery("SELECT * FROM Link WHERE owner = :email", email = email).fetch(999)

            template_values = {
    	        'show_login_link': False,
    	        'logged_in': True,
    	        'body_id': 'home',
    	        'user_email': email,
    	        'number_of_links': len(links),
    	        'links': links,
    	        'title': 'Gumroad / Add Link',
    	        'user_balance': formatted_price(user.balance)
    		}

            path = os.path.join(os.path.dirname(__file__), 'templates/link.html')
            self.response.out.write(template.render(path, template_values))

    def post(self):
        email = get_user()

        if not email:
            self.redirect("/")
        else:
            user = db.GqlQuery("SELECT * FROM User WHERE email = :email", email = email).get()
            links = db.GqlQuery("SELECT * FROM Link WHERE owner = :email", email = email).fetch(999)

            request = self.request
            name = cgi.escape(self.request.get('name'))
            price = cgi.escape(self.request.get('price'))
            non_decimal = re.compile(r'[^\d.]+')
            price = non_decimal.sub('', price)
            url = cgi.escape(self.request.get('url'))
            description = cgi.escape(self.request.get('description'))

            if not price == None and not price == '':
                if float(price) < 0.99 and not float(price) == 0:
                    price = str(0.99)

            if not name or not price or not url:
    	        error_message = 'Fill in the whole form please!'
    	        success = False
            else:
                if eval(price) > 999:
                    error_message = 'We don\'t support prices that high yet!'
                    success = False
                else:
                    price = '%.3g' % (eval(price))
                
                    x = 1
                    while x == 1:
                        permalink = "".join([random.choice(string.letters[:26]) for i in xrange(6)])	
                        new_permalink = Permalink(permalink=permalink)
                        permalinks_from_db = db.GqlQuery("SELECT * FROM Permalink WHERE permalink = :permalink", permalink = permalink)
                        if permalinks_from_db.count() == 0:
                            new_permalink.put()
                            x = 0                    

                    new_link = Link(owner=email, name=name, url=url, price=float(price), unique_permalink=permalink)
                    new_link.description = description
                    new_link.put()

                    s = sessions.Session()
                    s["user"] = email

                    success = True

            if success:
                self.redirect("/" + permalink)
            else:
                template_values = {
    		        'name': name,
    		        'price': '$' + price,
    		        'url': url,
    		        'description': description,
        	        'show_login_link': False,
        	        'logged_in': True,
        	        'body_id': 'home',
        	        'user_email': email,
        	        'number_of_links': len(links),
        	        'links': links,
        	        'title': 'Gumroad / Add Link',
        	        'user_balance': formatted_price(user.balance),
    		        'show_error': True,
    		        'error_message': error_message
    		        }

                path = os.path.join(os.path.dirname(__file__), 'templates/link.html')
                self.response.out.write(template.render(path, template_values))

class AccountHandler(webapp.RequestHandler):
    def get(self):
        email = get_user()

        if not email:
            self.redirect("/")
        else:
            user = db.GqlQuery("SELECT * FROM User WHERE email = :email", email = email).get()
            links = db.GqlQuery("SELECT * FROM Link WHERE owner = :email", email = email).fetch(999)

            template_values = {
                'name': user.name,
                'payment_address': user.payment_address,            
    	        'show_login_link': False,
    	        'logged_in': True,
    	        'body_id': 'home',
    	        'user_email': email,
    	        'email': email,
    	        'number_of_links': len(links),
    	        'links': links,
    	        'title': 'Gumroad / Edit Link',
    	        'user_balance': formatted_price(user.balance)
    		}

            path = os.path.join(os.path.dirname(__file__), 'templates/account.html')
            self.response.out.write(template.render(path, template_values))

    def post(self):
        email = get_user()

        if not email:
            self.redirect("/")
        else:
            user = db.GqlQuery("SELECT * FROM User WHERE email = :email", email = email).get()
            links = db.GqlQuery("SELECT * FROM Link WHERE owner = :email", email = email).fetch(999)

            request = self.request
            name = cgi.escape(self.request.get('name'))
            email = cgi.escape(self.request.get('email'))
            payment_address = cgi.escape(self.request.get('payment_address'))

            if not email:
                error_message = 'Fill in your email please!'
                success = False
            else:
                user.email = email
                user.name = name
                user.payment_address = payment_address
                user.put()    
                success = True

            if success:
                self.redirect("/account")
            else:
                template_values = {
        	        'name': name,
        	        'url': url,
        	        'description': description,
        	        'show_login_link': False,
        	        'editing': True,
        	        'permalink': permalink,
        	        'logged_in': True,
        	        'body_id': 'home',
        	        'user_email': email,
        	        'number_of_links': len(links),
        	        'links': links,
        	        'title': 'Gumroad / Edit Link',
        	        'user_balance': formatted_price(user.balance),
        	        'show_error': True,
        	        'error_message': error_message
        	    }

                path = os.path.join(os.path.dirname(__file__), 'templates/account.html')
                self.response.out.write(template.render(path, template_values))

class LinkHandler(webapp.RequestHandler):
    def get(self, permalink):

        if self.request.url.startswith('http://www.gumroad.com/'):
            self.redirect("https://gumroad.appspot.com/l/" + permalink)

        links_from_db = db.GqlQuery("SELECT * FROM Link WHERE unique_permalink = :permalink", permalink = permalink)

        if links_from_db.count() == 0:
            self.redirect("/")
        else:
            link = links_from_db.get()
            link.number_of_views += 1
            link.put()
            user = db.GqlQuery("SELECT * FROM User WHERE email = :email", email = link.owner).get()
            
            if len(link.description) > 0:
                show_description = True
            else:
                show_description = False
            
            if link.price < 0.01:
                link.number_of_downloads += 1
                link.put()
                self.redirect(link.url)            

            description = " <br /> ".join(link.description.split("\n"))
            r = re.compile(r"(http://[^ ]+)")
            description = r.sub(r'<a href="\1">\1</a>', description)            

            template_values = {
                'name': link.name,
                'permalink': permalink,
                'description': description,
                'show_description': show_description,
                'user_name': user.name,
                'user_email': user.email,
    	        'body_id': 'visiting-link',
    	        'title': 'Gumroad / ' + link.name,
    	        'user_balance': formatted_price(user.balance),
    	        'price': formatted_price(link.price)
    		}

            path = os.path.join(os.path.dirname(__file__), 'templates/visiting-link.html')
            self.response.out.write(template.render(path, template_values))

    def post(self, permalink):

        links_from_db = db.GqlQuery("SELECT * FROM Link WHERE unique_permalink = :permalink", permalink = permalink)

        if links_from_db.count() == 0:
            self.redirect("/")
        else:
            link = links_from_db.get()
            link.number_of_views += 1
            link.put()
            
            user = db.GqlQuery("SELECT * FROM User WHERE email = :email", email = link.owner).get()

            if link.price < 0.01:
                link.number_of_downloads += 1
                link.put()          
                self.redirect(link.url)  

            show_error = False
            error_message = ''

            request = self.request
            card_number = cgi.escape(self.request.get('card_number'))        
            expiry_month = cgi.escape(self.request.get('date_month'))
            expiry_year = cgi.escape(self.request.get('date_year'))            
            cvv = cgi.escape(self.request.get('card_security_code'))

            non_decimal = re.compile(r'[^\d.]+')
            card_number = non_decimal.sub('', card_number)
            cvv = non_decimal.sub('', cvv)
            expiry_month = non_decimal.sub('', expiry_month)
            expiry_year = non_decimal.sub('', expiry_year)
        
            if not card_number or not cvv:     
                self.response.headers['Content-Type'] = 'application/json'         
                self.response.out.write(json.dumps({
                    'error_message': 'Fill in the whole form please!',
                    'show_error': True
                }))
            else:
                #Stripe payments!
                identifier = link.unique_permalink + ' ' + str(link.number_of_views)
                client = stripe.Client('T10Jab3Cir6v3SJFMooSKTdGNUERR4jh')
                cents = int(link.price*100)
                try:
                    resp = client.execute(amount=cents, currency='usd', card={'number': card_number, 'exp_month': expiry_month, 'exp_year': expiry_year}, identifier=identifier)
                    logging.debug(resp.dict)
                    logging.debug(resp.dict['paid'])
                
                    if resp.dict['paid']:                
                        link.number_of_paid_downloads += 1
                        link.number_of_downloads += 1
                        link.balance += link.price
                        link.put()
                        
                        user.balance += link.price
                        user.put()
                                                
                        new_purchase = Purchase(owner=link.owner, price=float(link.price), unique_permalink=link.unique_permalink)
                        new_purchase.put()
                        
                        self.response.headers['Content-Type'] = 'application/json'         
                        self.response.out.write(json.dumps({
                            'success': True,
                            'redirect_url': link.url
                        }))
                    else:
                        self.response.headers['Content-Type'] = 'application/json'         
                        self.response.out.write(json.dumps({
                            'error_message': 'Your payment didn\'t go through! Please double-check your card details:',
                            'show_error': True
                        }))                                 
                except:
                    self.response.headers['Content-Type'] = 'application/json'         
                    self.response.out.write(json.dumps({
                        'error_message': 'Please double-check your card details:',
                        'show_error': True
                    }))                    

class StatsHandler(webapp.RequestHandler):
    def get(self):
        links_from_db = Link.all().fetch(9999)
        users_from_db = User.all().fetch(9999)
        purchases_from_db = Purchase.all().fetch(9999)
        links = len(links_from_db)
        users = len(users_from_db)
        purchases = len(purchases_from_db)
		
        purchase_total = 0
        purchase_total = sum(purchase.price for purchase in purchases_from_db)
		
        downloads = 0
        downloads = sum(link.number_of_downloads for link in links_from_db)
        views = 0
        views = sum(link.number_of_views for link in links_from_db)

        try:
            last_purchase_date = datetime.datetime.now()-Purchase.all().order('-create_date').get().create_date
        except:
            last_purchase_date = None

        template_values = {
    	    'number_of_links': links,
    	    'number_of_users': users,
    	    'number_of_purchases': purchases,
    	    'number_of_downloads': downloads,
    	    'number_of_views': views,
    	    'purchase_total': formatted_price(purchase_total),
    	    'average_downloads': downloads//links,
    	    'average_purchase': formatted_price(purchase_total//purchases),
    	    'average_views': views//links,
    	    'last_link_date': datetime.datetime.now()-Link.all().order('-create_date').get().create_date,
    	    'last_purchase_date': last_purchase_date
        }

        path = os.path.join(os.path.dirname(__file__), 'templates/stats.html')
        self.response.out.write(template.render(path, template_values))

class FAQHandler(webapp.RequestHandler):
    def get(self):
        
        template_values = {
            'body_id': 'static-content'
        }
        
        path = os.path.join(os.path.dirname(__file__), 'templates/faq.html')
        self.response.out.write(template.render(path, template_values))

class AboutHandler(webapp.RequestHandler):
    def get(self):
        
        template_values = {
            'body_id': 'static-content'
        }
        
        path = os.path.join(os.path.dirname(__file__), 'templates/about.html')
        self.response.out.write(template.render(path, template_values))

def main():
    logging.getLogger().setLevel(logging.DEBUG)
    application = webapp.WSGIApplication([('/', MainHandler),
 	                                      ('/stats/', StatsHandler), ('/stats', StatsHandler),
                                    	  ('/faq', FAQHandler), ('/faq/', FAQHandler),
                                    	  ('/about', AboutHandler), ('/about/', AboutHandler),
                                   	      ('/login/', LoginHandler),
                                    	  ('/login', LoginHandler),
                                    	  ('/account/', AccountHandler),
                                    	  ('/account', AccountHandler),
                                    	  ('/logout/', LogoutHandler),
                                    	  ('/logout', LogoutHandler),
                                    	  ('/upload/', FileUploadHandler),
                                    	  ('/upload', FileUploadHandler),
                                    	  ('/delete/(\S+)$', DeleteHandler),
                                    	  ('/delete/(\S+)/$', DeleteHandler),
                                    	  ('/home/', HomeHandler),
                                    	  ('/home', HomeHandler),
                                    	  ('/add/', AddLinkHandler),
                                    	  ('/add', AddLinkHandler),
                                    	  ('/l/(\S+)$', LinkHandler),
                                    	  ('/l/(\S+)/$', LinkHandler),
                                    	  ('/(\S+)$', EditLinkHandler),
                                    	  ('/(\S+)/$', EditLinkHandler)],
                                         debug=True)
    util.run_wsgi_app(application)


if __name__ == '__main__':
    main()
