import cgi
import os
import sys
import random
import string
import urllib
import unicodedata
import logging
import datetime
import time
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
from google.appengine.api import mail

from google.appengine.ext import blobstore
from google.appengine.ext.webapp import blobstore_handlers

import stripe

#ROOT_URL = 'http://localhost:8888'
ROOT_URL = 'http://www.gumroad.com'

class Link(db.Model):
    owner = db.StringProperty(required=True)
    name = db.StringProperty(required=True)
    unique_permalink = db.StringProperty(required=True)
    url = db.StringProperty(required=True)
    preview_url = db.StringProperty()
    description = db.StringProperty(multiline=True)
    price = db.FloatProperty(required=True, default=1.00)
    create_date = db.DateTimeProperty(auto_now_add=True)
    length_of_exclusivity = db.IntegerProperty(default=0)
    number_of_paid_downloads = db.IntegerProperty(default=0)
    number_of_downloads = db.IntegerProperty(default=0)
    download_limit = db.IntegerProperty(default=0)
    number_of_views = db.IntegerProperty(default=0)
    balance = db.FloatProperty(default=0.00)

class File(db.Model):
    unique_permalink = db.StringProperty(required=True)
    blob_key = db.StringProperty()
    file_name = db.StringProperty()
    file_type = db.StringProperty()
    date = db.DateTimeProperty(auto_now_add=True) 

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
    reset_hash = db.StringProperty()
    create_date = db.DateTimeProperty(auto_now_add=True)
    balance = db.FloatProperty(default=0.00)

class MainHandler(webapp.RequestHandler):
    def get(self):
        if is_logged_in():
            return self.redirect("/home")

        template_values = {
            'body_id': 'index',
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
                
                x = 1
                while x == 1:
                    permalink = "".join([random.choice(string.letters[:26]) for i in xrange(6)])
                    new_permalink = Permalink(permalink=permalink)
                    permalinks_from_db = db.GqlQuery("SELECT * FROM Permalink WHERE permalink = :permalink", permalink = permalink)
                    if permalinks_from_db.count() == 0:
                        new_permalink.put()
                        x = 0
                
                user.reset_hash = permalink
                user.put()

                failing = True
                
                try:
                    s = sessions.Session()
                    s["user"] = email
                except:
                    pass

                success = True
            else:
                user_from_db = users_from_db.get()

                if sha256(password).hexdigest() == user_from_db.password:
                    try:
                        s = sessions.Session()
                        s["user"] = email
                    except:
                        pass

                    success = True
                else:
        	        error_message = 'That email is already taken, sorry!'
        	        success = False

        if success:
            return self.redirect("/links")
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

def file_link(unique_permalink):
    return ROOT_URL + '/f/' + unique_permalink

def link_to_share(unique_permalink):
    return ROOT_URL + '/l/' + unique_permalink
    
def secure_link_to_share(unique_permalink):
    return 'https://gumroad.appspot.com/l/' + unique_permalink

def confirm_link_to_share(unique_permalink):
    return ROOT_URL + '/confirm/' + unique_permalink

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
	        'title': 'Log in to Gumroad'
		}

        path = os.path.join(os.path.dirname(__file__), 'templates/login.html')
        self.response.out.write(template.render(path, template_values))

    def post(self):
        request = self.request
        email = cgi.escape(request.get('email'))
        password = cgi.escape(request.get('password'))

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
                    try:
                        s = sessions.Session()
                        s["user"] = email
                    except:
                        pass
                            
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

class ForgotPasswordHandler(webapp.RequestHandler):
    def get(self):

        template_values = {
		    'show_login_link': False,
	        'body_id': 'login',
	        'title': 'Gumroad - Forgotten Password'
		}

        path = os.path.join(os.path.dirname(__file__), 'templates/forgot-password.html')
        self.response.out.write(template.render(path, template_values))

    def post(self):
        request = self.request
        email = cgi.escape(request.get('email'))

        if not email:
            success = False
            error_message = 'Fill in the form please!'
        else:
            users_from_db = db.GqlQuery("SELECT * FROM User WHERE email = :email", email = email)
            if users_from_db.count() == 0:
                error_message = "That email address isn't being used!"
                success = False
            else:
                success_message = "Check your email!"
                success = True
                
                user = users_from_db.get()
                reset_hash = "".join([random.choice(string.letters[:26]) for i in xrange(6)])
                user.reset_hash = reset_hash
                user.put()

                message = mail.EmailMessage(sender="Sahil @ Gumroad <sahil@slavingia.com>",
                                            subject="Gumroad password reset!")
                message.to = email

                message.body="""
                Hi!

                You recently asked for a password reset. Please visit
                http://gumroad.com/reset-password/%s to
                reset your password.

                So sorry for the inconvenience!
                
                Please let us know if you have any questions,
                The Gumroad Team
                """ % reset_hash
                                
                try:
                    message.send()
                except:
                    error_message = "Something bad happened! Working on it."
                    success = False

        if success:
            template_values = {
		        'show_login_link': False,
		        'show_error': False,
		        'email_address': email,
		        'body_id': 'login',
		        'success_message': success_message
		        }

            path = os.path.join(os.path.dirname(__file__), 'templates/forgot-password.html')
            self.response.out.write(template.render(path, template_values))
    	else:
            template_values = {
		        'show_login_link': False,
		        'show_error': True,
		        'email_address': email,
		        'body_id': 'login',
		        'error_message': error_message
		        }

            path = os.path.join(os.path.dirname(__file__), 'templates/forgot-password.html')
            self.response.out.write(template.render(path, template_values))

class ResetPasswordHandler(webapp.RequestHandler):
    def get(self, reset_hash):

        users_from_db = db.GqlQuery("SELECT * FROM User WHERE reset_hash = :reset_hash", reset_hash = reset_hash)
        
        if users_from_db.count() > 0:
            user = users_from_db.get()
            email = user.email
        else:
            error_message = 'Wrong reset link, sorry!'
            email = ''
            success = False

        template_values = {
		    'show_login_link': False,
	        'body_id': 'login',
	        'email_address': email,
	        'reset_hash': reset_hash,
	        'title': 'Gumroad - Reset Password'
		}

        path = os.path.join(os.path.dirname(__file__), 'templates/reset-password.html')
        self.response.out.write(template.render(path, template_values))

    def post(self, reset_hash):
        request = self.request
        email = cgi.escape(self.request.get('email'))
        password = cgi.escape(self.request.get('password'))

        if not email or not password:
	        error_message = 'Fill in the form please!'
	        success = False
        else:
            users_from_db = db.GqlQuery("SELECT * FROM User WHERE email = :email AND reset_hash = :reset_hash", email = email, reset_hash = reset_hash)
            if users_from_db.count() == 0:
                error_message = 'Something went wrong, sorry!'
    	        success = False
            else:
                user = users_from_db.get()
                user.password = password=sha256(password).hexdigest()
                user.put()

                s = sessions.Session()
                s["user"] = email

                success = True

        if success:
            self.redirect("/home")
    	else:
            template_values = {
		        'show_login_link': False,
		        'title': 'Gumroad - Reset Password',
    	        'show_error': True,
		        'email_address': email,
    	        'reset_hash': reset_hash,
    	        'body_id': 'login',
		        'error_message': error_message
		        }

            path = os.path.join(os.path.dirname(__file__), 'templates/reset-password.html')
            self.response.out.write(template.render(path, template_values))

class LinksHandler(webapp.RequestHandler):
    def get(self):
        email = get_user()
        links = []

        if not email:
            return self.redirect("/")
        else:
            user = db.GqlQuery("SELECT * FROM User WHERE email = :email", email = email).get()
            if not user:
                return self.redirect("/")
            links = db.GqlQuery("SELECT * FROM Link WHERE owner = :email", email = email).fetch(999)

            s = plural(len(links))

            if len(links) == 0:
                links_message = 'create one, you know you want to'
            else:
                if len(links) < 3:
                    links_message = 'not too bad...'
                else:
                    links_message = 'that\'s a lot!'

            for link in links:
                link.formatted_price = formatted_price(link.price)

            template_values = {
	            'show_login_link': False,
    	        'logged_in': True,
    	        'body_id': 'app',
    	        'user_email': email,
    	        'number_of_links': len(links),
    	        'links': links,
    	        'on_links_page': True,
    	        'links_message': links_message,
    	        's': s,
    	        'title': 'Gumroad',
    	        'user_balance': formatted_price(user.balance)
    		}

            path = os.path.join(os.path.dirname(__file__), 'templates/links.html')
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

            #todo: make sure right amount of days and create bins for each day, even days with 0 sales.
            counts = collections.defaultdict(int)
            for purchase in seven_days_purchases:
                counts[purchase.create_date.date()] += 1

            chart_numbers = []

            for k, v in counts.iteritems():
                if int(v) > 0:
                    chart_numbers.append(v)
                else:
                    chart_numbers.append('0')

            chart_numbers[0:14]

            if len(chart_numbers) > 0:
                chart_max = int(1.2*float(max(chart_numbers)))
                show_chart = True
            else:
                chart_max = 0
                show_chart = False
                
            chart_length = len(chart_numbers)

            chart_numbers = ",".join([str(x) for x in chart_numbers])

            s = plural(len(chart_numbers))

            template_values = {
	            'show_login_link': False,
	            'show_chart': show_chart,
    	        'logged_in': True,
    	        'body_id': 'app',
    	        'user_email': email,
    	        'number_of_links': len(links),
    	        'links': links,
    	        'purchases': all_purchases,
    	        'number_of_days': chart_length,
    	        's': s,
    	        'chart_numbers': chart_numbers,
    	        'chart_max': chart_max,
    	        'last_seven_days_purchase_total': formatted_price(last_seven_days_purchase_total),
    	        'last_month_purchase_total': formatted_price(last_month_purchase_total),
    	        'purchase_total': formatted_price(purchase_total),
    	        'title': 'Gumroad',
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

class EditLinkHandler(webapp.RequestHandler): #edit link
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

                upload_url = blobstore.create_upload_url('/upload')

                template_values = {
                    'name': link.name,
                    'url_encoded_name': urllib.quote(link.name),
                    'link_to_share': link_to_share(permalink),
                    'price': '$' + formatted_price(link.price),
                    'views': link.number_of_views,
                    'number_of_downloads': link.number_of_downloads,
                    'download_limit': link.download_limit,
                    'total_profit': '$' + formatted_price(link.balance),
                    'conversion': conversion,
                    'hundred_minus_conversion': hundred_minus_conversion,
                    'url': link.url,
                    'preview_url': link.preview_url,
                    'upload_url': upload_url,
                    'description': link.description,
        	        'show_login_link': False,
        	        'editing': True,
        	        'permalink': permalink,
        	        'logged_in': True,
        	        'body_id': 'app',
        	        'user_email': email,
        	        'number_of_links': len(links),
        	        'links': links,
        	        'title': 'Gumroad - ' + link.name,
        	        'user_balance': formatted_price(user.balance)
        		}

                path = os.path.join(os.path.dirname(__file__), 'templates/link.html')
                self.response.out.write(template.render(path, template_values))

    def post(self, permalink):
        email = get_user()

        if not email:
            return self.redirect("/")
        else:
            user = db.GqlQuery("SELECT * FROM User WHERE email = :email", email = email).get()
            links = db.GqlQuery("SELECT * FROM Link WHERE owner = :email", email = email).fetch(999)

        request = self.request
        name = cgi.escape(request.get('name'))
        price = cgi.escape(request.get('price'))
        non_decimal = re.compile(r'[^\d.]+')
        price = non_decimal.sub('', price)

        url = cgi.escape(request.get('url'))
        preview_url = cgi.escape(request.get('preview_url'))
        description = cgi.escape(request.get('description'))
        download_limit = cgi.escape(request.get('download_limit'))

        success = False

        if not name or not price or not url:
            error_message = 'Fill in the whole form please!'
            success = False
        else:
            
            if float(price) < 0.99 and not float(price) == 0:
                price = str(0.99)
                        
            if eval(price) > 999:
                error_message = 'We don\'t support prices that high yet!'
    	        success = False
    	    else:
                price = '%.3g' % (eval(price))

                link = db.GqlQuery("SELECT * FROM Link WHERE unique_permalink = :permalink", permalink = permalink).get()

                if not link.owner == email:
                    return self.redirect("/home")
                else:
                    link.owner = email
                    link.name = name
                    
                    if download_limit == '' or download_limit == None:
                        download_limit = 0
                    
                    link.download_limit = int(download_limit)
                    link.description = description
                    link.url = url
                    link.preview_url = preview_url
                    link.price = float(price)
                    link.put()
                    success = True

        if success:
            return self.redirect("/edit/" + permalink)
    	else:
            template_values = {
    	        'name': name,
                'url_encoded_name': urllib.quote(name),
    	        'price': '$' + price,
    	        'url': url,
    	        'preview_url': preview_url,
    	        'description': description,
                'download_limit': link.download_limit,
                'link_to_share': link_to_share(permalink),
    	        'show_login_link': False,
    	        'editing': True,
    	        'permalink': permalink,
    	        'logged_in': True,
    	        'body_id': 'app',
    	        'user_email': email,
    	        'number_of_links': len(links),
    	        'links': links,
    	        'title': 'Gumroad - Edit Link',
    	        'user_balance': formatted_price(user.balance),
    	        'show_error': True,
    	        'error_message': error_message
    	        }

            path = os.path.join(os.path.dirname(__file__), 'templates/link.html')
            self.response.out.write(template.render(path, template_values))

class FileHandler(blobstore_handlers.BlobstoreDownloadHandler): #file download        
    def get(self, permalink, file_name):
        f = db.GqlQuery("SELECT * FROM File WHERE unique_permalink = :permalink", permalink = permalink).get()

        if not f:
            return show_404(self)

        blob_key = f.blob_key
        blob_info = blobstore.BlobInfo.get(blob_key)
        self.send_blob(blob_info)

class FileUploadHandler(blobstore_handlers.BlobstoreUploadHandler): #file upload
    def post(self):
        upload = self.get_uploads('file')[0]
        key = str(upload.key())
        
        #add file to db
        x = 1
        while x == 1:
            permalink = "".join([random.choice(string.letters[:26]) for i in xrange(6)])
            new_permalink = Permalink(permalink=permalink)
            permalinks_from_db = db.GqlQuery("SELECT * FROM Permalink WHERE permalink = :permalink", permalink = permalink)
            if permalinks_from_db.count() == 0:
                new_permalink.put()
                x = 0

        new_file = File(blob_key=key, file_name=upload.filename, unique_permalink=permalink)
        new_file.put()

        return self.redirect('/f/%s/%s/success' % (permalink, upload.filename))

class AjaxSuccessHandler(webapp.RequestHandler): #ajax success
  def get(self, file_id):
    self.response.headers['Content-Type'] = 'text/plain'
    self.response.out.write('%s/f/%s' % (self.request.host_url, file_id))

class AddLinkHandler(webapp.RequestHandler): #add link
    def get(self):
        email = get_user()

        links = []

        if not email:
            self.redirect("/home")
        else:
            user = db.GqlQuery("SELECT * FROM User WHERE email = :email", email = email).get()
            links = db.GqlQuery("SELECT * FROM Link WHERE owner = :email", email = email).fetch(999)

            upload_url = blobstore.create_upload_url('/upload')

            template_values = {
    	        'show_login_link': False,
    	        'logged_in': True,
    	        'body_id': 'app',
                'upload_url': upload_url,
    	        'user_email': email,
    	        'number_of_links': len(links),
    	        'links': links,
    	        'title': 'Gumroad - Add Link',
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
            preview_url = cgi.escape(self.request.get('preview_url'))
            description = cgi.escape(self.request.get('description'))

            if not name or not price or not url:
    	        error_message = 'Fill in the whole form please!'
    	        success = False
            else:
                                
                if float(price) < 0.99 and not float(price) == 0:
                    price = str(0.99)
                
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
                    new_link.preview_url = preview_url
                    new_link.description = description
                    new_link.put()

                    s = sessions.Session()
                    s["user"] = email

                    success = True

            if success:
                self.redirect("/edit/" + permalink)
            else:
                upload_url = blobstore.create_upload_url('/upload')
                
                template_values = {
    		        'name': name,
    		        'price': '$' + price,
    		        'url': url,
    		        'description': description,
        	        'show_login_link': False,
        	        'logged_in': True,
        	        'body_id': 'app',
        	        'user_email': email,
                    'upload_url': upload_url,
        	        'number_of_links': len(links),
        	        'links': links,
        	        'title': 'Gumroad - Add Link',
        	        'user_balance': formatted_price(user.balance),
    		        'show_error': True,
    		        'error_message': error_message
    		        }

                path = os.path.join(os.path.dirname(__file__), 'templates/link.html')
                self.response.out.write(template.render(path, template_values))

class ApiCreateLinkHandler(webapp.RequestHandler):
    def get(self):
        self.response.headers['Content-Type'] = 'application/json'
        self.response.out.write(json.dumps({
            'status': 'failure',
            'error_message': 'Must use POST for this method.'
        }))
    def post(self):
        email = self.request.get('email')
        password = self.request.get('password')
                
        user = db.GqlQuery("SELECT * FROM User WHERE email = :email AND password = :password", email = email, password = sha256(password).hexdigest()).get()

        if user == None:
            self.response.headers['Content-Type'] = 'application/json'
            self.response.out.write(json.dumps({
                'status': 'failure',
                'error_message': 'User does not exist. Double-check credentials.'
            }))
        else:
            request = self.request
            name = cgi.escape(self.request.get('name'))
            price = cgi.escape(self.request.get('price'))
            non_decimal = re.compile(r'[^\d.]+')
            price = non_decimal.sub('', price)
            url = cgi.escape(self.request.get('url'))
            description = cgi.escape(self.request.get('description'))

            link = db.GqlQuery("SELECT * FROM Link WHERE url = :url AND owner = :owner", url = url, owner = email).get()
            
            if link == None:
                if not name or not price or not url:
                    self.response.headers['Content-Type'] = 'application/json'
                    self.response.out.write(json.dumps({
                        'status': 'failure',
                        'error_message': 'Parameters missing. Need name, URL, and price.'
                    }))
                else:
                            
                    if float(price) < 0.99 and not float(price) == 0:
                        price = str(0.99)
            
                    if eval(price) > 999:
                        self.response.headers['Content-Type'] = 'application/json'
                        self.response.out.write(json.dumps({
                            'status': 'failure',
                            'error_message': 'We don\'t support prices that high yet.'
                        }))
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

                        self.response.headers['Content-Type'] = 'application/json'
                        self.response.out.write(json.dumps({
                            'status': 'success',
                            'url': link_to_share(permalink)
                        }))
            else:
                self.response.headers['Content-Type'] = 'application/json'
                self.response.out.write(json.dumps({
                    'status': 'success',
                    'url': link_to_share(link.unique_permalink)
                }))

class ApiPurchaseLinkHandler(webapp.RequestHandler):
    def get(self):
        self.response.headers['Content-Type'] = 'application/json'
        self.response.out.write(json.dumps({
            'status': 'failure',
            'error_message': 'Must use POST for this method.'
        }))
    def post(self):
        permalink = self.request.get('id')

        links_from_db = db.GqlQuery("SELECT * FROM Link WHERE unique_permalink = :permalink", permalink = permalink)

        if links_from_db.count() == 0:
            self.response.headers['Content-Type'] = 'application/json'
            self.response.out.write(json.dumps({
                'status': 'failure',
                'error_message': 'That link does not exist.',
                'show_error': True
            }))
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
            logging.debug('Start guestbook signing request')
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
                    'status': 'failure',
                    'error_message': 'Specify your card details, please!',
                    'show_error': True
                }))
            else:       
                if link.number_of_downloads >= link.download_limit and link.download_limit > 0:
                    self.response.headers['Content-Type'] = 'application/json'
                    self.response.out.write(json.dumps({
                        'status': 'failure',
                        'error_message': 'This link has hit its download limit. Sorry!',
                        'show_error': True
                    }))   
                else:               
                    #Stripe payments!
                    identifier = link.unique_permalink + ' ' + str(link.number_of_views)
                    if cgi.escape(self.request.get('testing')):
                        client = stripe.Client('pe43CRDgovrviePbNzHvisgDYtMF62Ev')
                    else:
                        client = stripe.Client('bXOUJVSN09rarpaBgyWeQowXzzdIZMJ9')
                        
                    cents = int(link.price*100)    
                    
                    try:
                        resp = client.execute(amount=cents, currency='usd', card={'number': card_number, 'exp_month': expiry_month, 'exp_year': expiry_year}, identifier=identifier)

                        if resp.dict['paid']:
                            link.number_of_paid_downloads += 1
                            link.number_of_downloads += 1
                            link.balance += link.price
                            link.put()

                            user.balance += link.price
                            user.put()

                            new_purchase = Purchase(owner=link.owner, price=float(link.price), unique_permalink=link.unique_permalink)
                            new_purchase.put()

                            message = mail.EmailMessage(sender="Gumroad <hi@gumroad.com>",
                                                        subject="You just sold a link!")
                            message.to = user.email

                            message.body="""
                            Hi!

                            You just sold %s. Please visit
                            http://gumroad.com/home to check it out.

                            Congratulations on the sale!

                            Please let us know if you have any questions,
                            The Gumroad Team
                            """ % link.name

                            try:
                                message.send()
                            except:
                                pass

                            redirect_url = link.url

                            if cgi.escape(self.request.get('testing')):
                                redirect_url = 'http://google.com'

                            self.response.headers['Content-Type'] = 'application/json'
                            self.response.out.write(json.dumps({
                                'success': True,
                                'redirect_url': redirect_url
                            }))
                        else:
                            self.response.headers['Content-Type'] = 'application/json'
                            self.response.out.write(json.dumps({
                                'status': 'failure',
                                'error_message': 'Your payment didn\'t go through! Please double-check your card details:',
                                'show_error': True
                            }))
                    except:
                        self.response.headers['Content-Type'] = 'application/json'
                        self.response.out.write(json.dumps({
                            'status': 'failure',
                            'error_message': 'Please double-check your card details.',
                            'show_error': True
                        }))

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
                'email_address': user.email,
    	        'show_login_link': False,
    	        'logged_in': True,
    	        'body_id': 'app',
    	        'email': email,
    	        'number_of_links': len(links),
    	        'links': links,
    	        'title': 'Gumroad - Account Settings',
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
            
            if not user:
                email = cgi.escape(self.request.get('email'))
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
                                                                
                for link in links:                    
                    link.owner = user.email
                    link.put()
                
                user.name = name
                user.payment_address = payment_address
                
                try:
                    s = sessions.Session()
                    s["user"] = email
                except:
                    pass
                
                user.put()
                success = True

            if success:
                self.redirect("/settings")
            else:
                template_values = {
                    'name': user.name,
                    'payment_address': user.payment_address,
        	        'show_login_link': False,
        	        'logged_in': True,
        	        'body_id': 'app',
                    'email_address': user.email,
        	        'email': email,
        	        'number_of_links': len(links),
        	        'links': links,
        	        'title': 'Gumroad - Account Settings',
        	        'user_balance': formatted_price(user.balance),
        	        'show_error': True,
        	        'error_message': error_message
        	    }

                path = os.path.join(os.path.dirname(__file__), 'templates/account.html')
                self.response.out.write(template.render(path, template_values))
                                                            
class LinkHandler(webapp.RequestHandler): #viewing link
    def get(self, permalink):

        if self.request.url.startswith('http://www.gumroad.com/'):
            self.redirect("https://gumroad.appspot.com/l/" + permalink)

        links_from_db = db.GqlQuery("SELECT * FROM Link WHERE unique_permalink = :permalink", permalink = permalink)

        if links_from_db.count() == 0:
            return show_404(self)
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
                'hide_header': True,
                'hide_footer': True,
                'permalink': permalink,
                'preview_url': link.preview_url,
                'description': description,
                'show_description': show_description,
                'user_name': user.name,
                'user_email': user.email,
    	        'body_id': 'link',
    	        'title': 'Gumroad - ' + link.name,
    	        'user_balance': formatted_price(user.balance),
    	        'price': formatted_price(link.price)
    		}

            path = os.path.join(os.path.dirname(__file__), 'templates/visiting-link.html')
            self.response.out.write(template.render(path, template_values))

    def post(self, permalink):
        links_from_db = db.GqlQuery("SELECT * FROM Link WHERE unique_permalink = :permalink", permalink = permalink)

        if links_from_db.count() == 0:
            self.response.headers['Content-Type'] = 'application/json'
            self.response.out.write(json.dumps({
                'error_message': 'That link does not exist.',
                'show_error': True
            }))
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
                return self.response.out.write(json.dumps({
                    'error_message': 'Fill in the whole form please!',
                    'show_error': True
                }))
            else:       
                if link.number_of_downloads >= link.download_limit and link.download_limit > 0:
                    self.response.headers['Content-Type'] = 'application/json'
                    return self.response.out.write(json.dumps({
                        'error_message': 'This link has hit its download limit. Sorry!',
                        'show_error': True
                    }))   
                else:               
                    #Stripe payments!
                    identifier = link.unique_permalink + ' ' + str(link.number_of_views)
                    if cgi.escape(self.request.get('testing')):
                        client = stripe.Client('pe43CRDgovrviePbNzHvisgDYtMF62Ev')
                    else:
                        client = stripe.Client('bXOUJVSN09rarpaBgyWeQowXzzdIZMJ9')
                        
                    cents = int(link.price*100)    
                    
                    try:
                        resp = client.execute(amount=cents, currency='usd', card={'number': card_number, 'exp_month': expiry_month, 'exp_year': expiry_year}, identifier=identifier)

                        if resp.dict['paid']:
                            link.number_of_paid_downloads += 1
                            link.number_of_downloads += 1
                            link.balance += link.price
                            link.put()

                            user.balance += link.price
                            user.put()

                            new_purchase = Purchase(owner=link.owner, price=float(link.price), unique_permalink=link.unique_permalink)
                            new_purchase.put()

                            message = mail.EmailMessage(sender="Sahil @ Gumroad <sahil@slavingia.com>",
                                                        subject="You just sold a link!")
                            message.to = user.email

                            message.body="""
                            Hi!

                            You just sold %s. Please visit
                            http://gumroad.com/home to check it out.

                            Congratulations on the sale!

                            Please let us know if you have any questions,
                            The Gumroad Team
                            """ % link.name

                            try:
                                message.send()
                            except:
                                pass

                            redirect_url = link.url

                            if cgi.escape(self.request.get('testing')):
                                redirect_url = 'http://google.com'

                            self.response.headers['Content-Type'] = 'application/json'
                            self.response.out.write(json.dumps({
                                'success': True,
                                'redirect_url': redirect_url
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

SIMPLE_TYPES = (int, long, float, bool, dict, basestring, list)

def to_dict(model):
    output = {}

    for key, prop in model.properties().iteritems():
        value = getattr(model, key)

        if value is None or isinstance(value, SIMPLE_TYPES):
            output[key] = value
        elif isinstance(value, datetime.date):
            # Convert date/datetime to ms-since-epoch ("new Date()").
            ms = time.mktime(value.utctimetuple()) * 1000
            ms += getattr(value, 'microseconds', 0) / 1000
            output[key] = int(ms)
        elif isinstance(value, db.GeoPt):
            output[key] = {'lat': value.lat, 'lon': value.lon}
        elif isinstance(value, db.Model):
            output[key] = to_dict(value)
        else:
            raise ValueError('cannot encode ' + repr(prop))

    return output

class ApiLinkStatsHandler(webapp.RequestHandler):
    def get(self, permalink, email, password):
        email = urllib.unquote(email).decode('utf8')
        password = password.rstrip("/")

        user = db.GqlQuery("SELECT * FROM User WHERE email = :email", email = email).get()
        link = db.GqlQuery("SELECT * FROM Link WHERE unique_permalink = :permalink AND owner = :email", permalink = permalink, email = email).get()

        if not link:
            self.response.headers['Content-Type'] = 'application/json'
            return self.response.out.write(json.dumps({
                'status': 'failure',
                'error_message': 'Link with that id does not exist.'
            }))
        else:
            if sha256(password).hexdigest() != user.password:
                self.response.headers['Content-Type'] = 'application/json'
                return self.response.out.write(json.dumps({
                    'status': 'failure',
                    'error_message': 'Credentials did not match.'
                }))

        user_dict = to_dict(user)
        link_dict = to_dict(link)

        del user_dict['reset_hash']
        del user_dict['password']

        self.response.headers['Content-Type'] = 'application/json'
        self.response.out.write(json.dumps({
            'status': 'success',
            'user': user_dict,
            'link': link_dict
        }))

class ApiStatsHandler(webapp.RequestHandler):    
    def get(self, email, password):
        email = urllib.unquote(email).decode('utf8')
        password = password.rstrip("/")
        
        user = db.GqlQuery("SELECT * FROM User WHERE email = :email", email = email).get()
        links = db.GqlQuery("SELECT * FROM Link WHERE owner = :email", email = email).fetch(999)

        if not user:
            self.response.headers['Content-Type'] = 'application/json'
            return self.response.out.write(json.dumps({
                'status': 'failure',
                'error_message': 'User with that email does not exist.'
            }))
        else:
            if sha256(password).hexdigest() != user.password:
                self.response.headers['Content-Type'] = 'application/json'
                return self.response.out.write(json.dumps({
                    'status': 'failure',
                    'error_message': 'Credentials did not match.'
                }))
                
        user_dict = to_dict(user)
        link_dicts = [to_dict(link) for link in links]

        del user_dict['reset_hash']
        del user_dict['password']
                
        self.response.headers['Content-Type'] = 'application/json'
        self.response.out.write(json.dumps({
            'status': 'success',
            'user': user_dict,
            'links': link_dicts
        }))
        
    def post(self, email, password):
        self.response.headers['Content-Type'] = 'application/json'
        self.response.out.write(json.dumps({
            'status': 'failure',
            'error_message': 'Must use GET for this method.'
        }))
        
class StatsHandler(webapp.RequestHandler):
    def get(self):
        
        if not cgi.escape(self.request.get('omg')) == 'yes':
            return show_404(self)
        
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
            'title': 'Gumroad - FAQ',
            'body_id': 'static-content'
        }

        path = os.path.join(os.path.dirname(__file__), 'templates/faq.html')
        self.response.out.write(template.render(path, template_values))

class AboutHandler(webapp.RequestHandler):
    def get(self):

        template_values = {
            'title': 'About Gumroad',
            'body_id': 'static-content'
        }

        path = os.path.join(os.path.dirname(__file__), 'templates/about.html')
        self.response.out.write(template.render(path, template_values))

class ElsewhereHandler(webapp.RequestHandler):
    def get(self):

        template_values = {
            'title': 'Gumroad - Elsewhere',
            'body_id': 'static-content'
        }

        path = os.path.join(os.path.dirname(__file__), 'templates/elsewhere.html')
        self.response.out.write(template.render(path, template_values))
        
class FlickrHandler(webapp.RequestHandler):
    def get(self):

        template_values = {
            'title': 'Gumroad - Flickr',
            'body_id': 'app'
        }

        path = os.path.join(os.path.dirname(__file__), 'templates/flickr.html')
        self.response.out.write(template.render(path, template_values))
        
def show_404(self):
    self.error(404)

    template_values = {
        'title': 'Gumroad - 404',
        'body_id': 'fourohfour',
        'hide_header': True,
        'hide_footer': True
    }
    
    path = os.path.join(os.path.dirname(__file__), 'templates/404.html')
    self.response.out.write(template.render(path, template_values))

class NotFoundPageHandler(webapp.RequestHandler):
    def get(self):
        show_404(self)

def main():
    logging.getLogger().setLevel(logging.DEBUG)
    application = webapp.WSGIApplication([('/', MainHandler),
 	                                      ('/stats', StatsHandler),
                                    	  ('/faq', FAQHandler),
                                    	  ('/about', AboutHandler),
                                    	  ('/elsewhere', ElsewhereHandler),
                                    	  ('/flickr', FlickrHandler),
                                    	  ('/login', LoginHandler),
                                    	  ('/settings', AccountHandler),
                                    	  ('/links', LinksHandler),
                                    	  ('/logout', LogoutHandler),
                                    	  ('/upload', FileUploadHandler),
                                          ('/f/(\S+)/success', AjaxSuccessHandler),
                                    	  ('/f/(\S+)/(\S+)$', FileHandler),
                                    	  ('/home', HomeHandler),
                                    	  ('/reset-password/(\S+)$', ResetPasswordHandler),
                                    	  ('/password-reset/(\S+)$', ResetPasswordHandler),
                                    	  ('/forgot-password', ForgotPasswordHandler),
                                    	  ('/add', AddLinkHandler),
                                    	  ('/edit/(\S+)$', EditLinkHandler),
                                    	  ('/delete/(\S+)$', DeleteHandler),
                                    	  ('/l/(\S+)$', LinkHandler),
                                    	  ('/api/create$', ApiCreateLinkHandler),
                                    	  ('/api/add$', ApiCreateLinkHandler),
                                    	  ('/api/link/stats/(\S+)/(\S+)/(\S+)$', ApiLinkStatsHandler),
                                    	  ('/api/user/stats/(\S+)/(\S+)$', ApiStatsHandler),
                                    	  ('/api/purchase$', ApiPurchaseLinkHandler),
                                    	  ('/.*', NotFoundPageHandler)],
                                         debug=True)
    util.run_wsgi_app(application)


if __name__ == '__main__':
    main()
