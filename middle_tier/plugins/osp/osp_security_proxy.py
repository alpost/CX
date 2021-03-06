import json
import logging

import requests

from exceptions import MiddleTierException
from proxy.response import Response
from resources.base import Resource
from security import IncorrectSecurityConfigurationException, UnauthorizedSecurityException, \
    AuthenticationResponse
from security.custom import CustomKeyHandler

logger = logging.getLogger()
TARGET_URL_PROP = "target_url"
USERNAME_PROP = "username"
PASSWORD_PROP = "password"
APP_PROP = "app"
TIMEOUT = "timeout"


class OSPAuthenticationResponse(AuthenticationResponse):
    """This is the authentication response that handles returning the token when it is valid"""
    def __init__(self, response):
        self.response = response

    def get_username(self):
        """Get the username of the user represented by the token"""
        return self.response.get("username")


class OSPTokenCheckClient:
    """
    This class handles calling the OSP server to validate tokens.  It manages the introspect URL 
    and makes the REST request to check if a token is valid.
    """
    def __init__(self, url, username, password, app, timeout=10):
        self.app = app
        self.token_url = self.get_osp_introspect_url(url, app)
        self.attr_url = self.get_osp_attributes_url(url, app)
        self.username = username
        self.timeout = timeout
        self.password = password
        
        if url is None:
            raise MiddleTierException("The target_url parameter is not configured in the services.json file.")
        if username is None:
            raise MiddleTierException("The username parameter is not configured in the services.json file.")
        if password is None:
            raise MiddleTierException("The password parameter is not configured in the services.json file.")
        if app is None:
            raise MiddleTierException("The app parameter is not configured in the services.json file.")
            
    def get_osp_introspect_url(self, url, app):
        """Get the OSP introspect REST endpoint URL"""
        url = '{base}/osp/a/{app}/auth/oauth2/introspect'.format(base=url,
                                                                 app=app)
        logger.debug("OSP introspect url = {}".format(url))
        return url
        
    def get_osp_attributes_url(self, url, app):
        """Get the OSP attributes REST endpoint URL"""
        url = '{base}/osp/a/{app}/auth/oauth2/getattributes?attributes=client+name+last_name+first_name+initials+email+roles+language+cacheable+expiration&access_token='.format(base=url,
                                                                 app=app)
        logger.debug("OSP introspect url = {}".format(url))
        return url

    def check_token(self, token):
        """
        This function makes the REST call to validate the token.  It will return the JSON
        response from OSP which may be token information or may indicate that the token is
        not active.
        """
        logger.debug("OSP token url: {}".format(self.token_url))
        try:
            r = requests.post(self.token_url, auth=(self.username, self.password), data={
                "token": token}, timeout=self.timeout)
            logger.debug("OSP returns: {}".format(r.text))
            logger.debug("r.status_code: {}".format(r.status_code))
            if r.status_code == 200:
                return r.json()
            elif r.status_code == 401:
                '''
                When the server returns a 401 it means that the client ID or 
                client secret are incorrect.  In this case we can give a better
                error message to help sort out the configuration issue.
                '''
                raise IncorrectSecurityConfigurationException("Unable to authenticate request")
            else:
                return None
        except Exception as e:
            logger.exception("Failed to run OSP token checker")
            raise e
            
    def check_attributes(self, token):
        """
        This function makes the REST call to get attributes based on the user represented
        by the token.  It will return the JSON response from OSP which may be a JSON 
        document with user information or may indicate that the token is not active.
        """
        logger.debug("OSP attributes url: {}".format(self.attr_url + token))
        try:
            r = requests.get(self.attr_url + token, auth=(self.username, self.password), timeout=self.timeout)
            logger.debug("OSP returns: {}".format(r.text))
            logger.debug("r.status_code: {}".format(r.status_code))
            if r.status_code == 200:
                return r.json()
            elif r.status_code == 401:
                '''
                When the server returns a 401 it means that the client ID or 
                client secret are incorrect.  In this case we can give a better
                error message to help sort out the configuration issue.
                '''
                raise IncorrectSecurityConfigurationException("Unable to authenticate request")
            else:
                return None
        except Exception as e:
            logger.exception("Failed to run OSP token checker")
            raise e


class OSPProxy(CustomKeyHandler):
    """
    The OSP proxy does the actual checking of tokens and interprets the responses.  It also handles
    reading the token from the HTTP header and making sure that it's there before passing code control
    on to other REST endpoints.
    """
    def __init__(self, config):
        super().__init__(config)
        if self.config is None:
            raise IncorrectSecurityConfigurationException("Security custom data is not configured")
        data = self.config.get("data")

        url = data.get(TARGET_URL_PROP)
        username = data.get(USERNAME_PROP)
        password = data.get(PASSWORD_PROP)
        app = data.get(APP_PROP)
        timeout = data.get(TIMEOUT, 10)
        self.osp_client = OSPTokenCheckClient(url, username, password, app, timeout)

    def check(self, token):
        logger.debug("OSP security proxy data = {}".format(self.config))
        bearer_prefix = "Bearer "
        if not token.startswith(bearer_prefix):
            raise UnauthorizedSecurityException("Not authorized")
        token = token[len(bearer_prefix):]
        try:
            check_token = self.osp_client.check_token(token)
            is_active = check_token.get('active', False)
            logger.debug("OSP user status: {}".format(is_active))
            if is_active:
                return OSPAuthenticationResponse(check_token)
            else:
                raise UnauthorizedSecurityException("Not authorized")
        except Exception:
            raise UnauthorizedSecurityException("Not authorized")


class OSPVirtualEndpoint(Resource):
    """
    This endpoint handles getting information about the token.  It can act like a whoAmI style
    call and is a good candidate for a first REST call in an application.  
    """
    def __init__(self, service):
        super().__init__(service)
        self.config = service.service_definition
        if self.config is None:
            raise IncorrectSecurityConfigurationException("Security custom data is not configured")
        data = self.config.get("data")

        url = data.get(TARGET_URL_PROP)
        username = data.get(USERNAME_PROP)
        password = data.get(PASSWORD_PROP)
        app = data.get(APP_PROP)
        timeout = data.get(TIMEOUT, 10)
        self.osp_client = OSPTokenCheckClient(url, username, password, app, timeout)
        
    def get_attributes(self, request):
        bearer_prefix = "Bearer "
        token = request.headers.get("Authorization")
        if not token or not token.startswith(bearer_prefix):
            raise UnauthorizedSecurityException("Not authorized")
        token = token[len(bearer_prefix):]
        
        try:
            response = self.osp_client.check_attributes(token)
            is_error = response.get('error')
            logger.debug("OSP user attributes status: {}".format(is_error))
            if is_error:
                raise UnauthorizedSecurityException("Not authorized")
        except UnauthorizedSecurityException:
            logger.exception("Failed to check token")
            raise UnauthorizedSecurityException("Not authorized")
        except IncorrectSecurityConfigurationException:
            '''
            This exception happens because there was a configuration error validating the token.
            We don't want to returna 401 in this case because the client will just request a new
            token, get the same token (because it is valid), and then try to validate it again.
            That causes a refresh loop in the browser.  Instead we want to return a 400 so we 
            can stop the loop and have a better error message.
            '''
            raise IncorrectSecurityConfigurationException("The OSP server said that the token validation request was " +
            "unauthorized.  That means the client ID or client secret are incorrect in the services.json file.")
        except Exception:
            '''
            This exception happens because we couldn't contact the OSP server.  This most likely
            happens because of the configuration error in the services.json file.  We don't want 
            to returna 401 in this case because the client will just request a new token, get the 
            same token (because it is valid), and then try to validate it again.  That causes a 
            refresh loop in the browser.  Instead we want to return a 400 so we can stop the loop 
            and have a better error message.
            '''
            logger.exception("""
-----------------------------------------

The middle tier was unable to contact the OSP server to validate the token.  This 
means your OSP server was either offline or unreachable.

-----------------------------------------
            """)
            raise IncorrectSecurityConfigurationException("The middle tier was unable to contact the OSP server to " + 
            "validate the token.  This means your OSP server was either offline or unreachable.  Check the " + 
            "configuration in the services.json file.")
        return Response(json.dumps(response), headers={'Content-type': "application/json"})

    def get_token(self, request):
        bearer_prefix = "Bearer "
        token = request.headers.get("Authorization")
        if not token or not token.startswith(bearer_prefix):
            raise UnauthorizedSecurityException("Not authorized")
        token = token[len(bearer_prefix):]
        try:
            response = self.osp_client.check_token(token)
            is_active = response.get('active', False)
            logger.debug("OSP user status: {}".format(is_active))
            if not is_active:
                raise UnauthorizedSecurityException("Not authorized")
        except UnauthorizedSecurityException:
            logger.exception("Failed to check token")
            raise UnauthorizedSecurityException("Not authorized")
        except IncorrectSecurityConfigurationException:
            '''
            This exception happens because there was a configuration error validating the token.
            We don't want to returna 401 in this case because the client will just request a new
            token, get the same token (because it is valid), and then try to validate it again.
            That causes a refresh loop in the browser.  Instead we want to return a 400 so we 
            can stop the loop and have a better error message.
            '''
            raise IncorrectSecurityConfigurationException("The OSP server said that the token validation request was " +
            "unauthorized.  That means the client ID or client secret are incorrect in the services.json file.")
        except Exception:
            '''
            This exception happens because we couldn't contact the OSP server.  This most likely
            happens because of the configuration error in the services.json file.  We don't want 
            to returna 401 in this case because the client will just request a new token, get the 
            same token (because it is valid), and then try to validate it again.  That causes a 
            refresh loop in the browser.  Instead we want to return a 400 so we can stop the loop 
            and have a better error message.
            '''
            logger.exception("""
-----------------------------------------

The middle tier was unable to contact the OSP server to validate the token.  This 
means your OSP server was either offline or unreachable.

-----------------------------------------
            """)
            raise IncorrectSecurityConfigurationException("The middle tier was unable to contact the OSP server to " + 
            "validate the token.  This means your OSP server was either offline or unreachable.  Check the " + 
            "configuration in the services.json file.")
        return Response(json.dumps(response), headers={'Content-type': "application/json"})
