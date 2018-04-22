#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Author: Patrick Mac Gregor
# @Date:   2018-04-22
# @Last Modified by:   Patrick Mac Gregor
# @Last Modified time: 2018-04-22

import gdata.photos.service
import httplib2
import time
from datetime import datetime, timedelta
from oauth2client.client import flow_from_clientsecrets
from oauth2client.file import Storage
from gdata.photos.service import GPHOTOS_INVALID_ARGUMENT, GPHOTOS_INVALID_CONTENT_TYPE, GooglePhotosException


class TokenRefreshingClient:
    def __init__(self, client_secrets, credential_store, email):
        self.credential_store = credential_store
        storage = Storage(credential_store)
        self.credentials = storage.get()
        self.client_secrets = client_secrets
        self.email = email
        self.originalClient = self.initClient()

    def initClient(self):
        scope='https://picasaweb.google.com/data/'
        user_agent='picasawebuploader'

        if self.credentials is None or self.credentials.invalid:
            self.credentials = self.oAuth2Login(self.client_secrets, scope)
            storage.put(self.credentials)

        if self.isTokenExpired():
            self.refreshToken()

        return gdata.photos.service.PhotosService(
            source=user_agent,
            email=self.email,
            additional_headers={'Authorization' : 'Bearer %s' % self.credentials.access_token}
        )

    def oAuth2Login(self, client_secrets, scope):
        flow = flow_from_clientsecrets(client_secrets, scope=scope, redirect_uri='urn:ietf:wg:oauth:2.0:oob')
        uri = flow.step1_get_authorize_url()
        webbrowser.open(uri)
        code = raw_input('Enter the authentication code: ').strip()
        return flow.step2_exchange(code)

    def isTokenExpired(self):
        #print(self.credentials.token_expiry)
        return (self.credentials.token_expiry - datetime.utcnow()) < timedelta(minutes=5)

    def refreshToken(self):
        print("Refreshing token ..")
        http = httplib2.Http()
        http = self.credentials.authorize(http)
        self.credentials.refresh(http)
        storage = Storage(self.credential_store)
        storage.put(self.credentials)
        print("Refreshing client with new token valid until " + str(self.credentials.token_expiry))
        self.originalClient = self.initClient()

    def InsertPhoto(self, *args, **kwargs):
        if (self.isTokenExpired()):
            self.refreshToken()

        return self.originalClient.InsertPhoto(*args, **kwargs)

    def GetUserFeed(self, *args):
        return self.originalClient.GetUserFeed(*args)

