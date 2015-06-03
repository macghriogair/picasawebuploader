#! /usr/bin/python2
#
# Uploads photos to Google Photos / Google+ / Picasa Web Albums
#
# Requires:
#   Python 2.7
#   gdata 2.0 python library
#
# Copyright (C) 2015 Michael Oestergaard
#
# A slightly modified version of https://github.com/jackpal/picasawebuploader
# Contains code from http://nathanvangheem.com/news/moving-to-picasa-update

import sys
if sys.version_info < (2,7):
    sys.stderr.write("This script requires Python 2.7 or newer.\n")
    sys.stderr.write("Current version: " + sys.version + "\n")
    sys.stderr.flush()
    sys.exit(1)

import argparse
import atom
import atom.service
import filecmp
import gdata
import gdata.photos.service
import gdata.media
import gdata.geo
import gdata.gauth
import getpass
import httplib2
import os
import subprocess
import tempfile
import time
import webbrowser

from datetime import datetime, timedelta
from oauth2client.client import flow_from_clientsecrets
from oauth2client.file import Storage
from gdata.photos.service import GPHOTOS_INVALID_ARGUMENT, GPHOTOS_INVALID_CONTENT_TYPE, GooglePhotosException

PICASA_MAX_VIDEO_SIZE_BYTES = 104857600

class VideoEntry(gdata.photos.PhotoEntry):
    pass

gdata.photos.VideoEntry = VideoEntry

def InsertVideo(self, album_or_uri, video, filename_or_handle, content_type='image/jpeg'):
    """Copy of InsertPhoto which removes protections since it *should* work"""
    try:
        assert(isinstance(video, VideoEntry))
    except AssertionError:
        raise GooglePhotosException({'status':GPHOTOS_INVALID_ARGUMENT,
            'body':'`video` must be a gdata.photos.VideoEntry instance',
            'reason':'Found %s, not PhotoEntry' % type(video)
        })
    try:
        majtype, mintype = content_type.split('/')
        #assert(mintype in SUPPORTED_UPLOAD_TYPES)
    except (ValueError, AssertionError):
        raise GooglePhotosException({'status':GPHOTOS_INVALID_CONTENT_TYPE,
            'body':'This is not a valid content type: %s' % content_type,
            'reason':'Accepted content types:'
        })
    if isinstance(filename_or_handle, (str, unicode)) and \
        os.path.exists(filename_or_handle): # it's a file name
        mediasource = gdata.MediaSource()
        mediasource.setFile(filename_or_handle, content_type)
    elif hasattr(filename_or_handle, 'read'):# it's a file-like resource
        if hasattr(filename_or_handle, 'seek'):
            filename_or_handle.seek(0) # rewind pointer to the start of the file
        # gdata.MediaSource needs the content length, so read the whole image
        file_handle = StringIO.StringIO(filename_or_handle.read())
        name = 'image'
        if hasattr(filename_or_handle, 'name'):
            name = filename_or_handle.name
        mediasource = gdata.MediaSource(file_handle, content_type,
            content_length=file_handle.len, file_name=name)
    else: #filename_or_handle is not valid
        raise GooglePhotosException({'status':GPHOTOS_INVALID_ARGUMENT,
            'body':'`filename_or_handle` must be a path name or a file-like object',
            'reason':'Found %s, not path name or object with a .read() method' % \
            type(filename_or_handle)
        })

    if isinstance(album_or_uri, (str, unicode)): # it's a uri
        feed_uri = album_or_uri
    elif hasattr(album_or_uri, 'GetFeedLink'): # it's a AlbumFeed object
        feed_uri = album_or_uri.GetFeedLink().href

    try:
        return self.Post(video, uri=feed_uri, media_source=mediasource,
            converter=None)
    except gdata.service.RequestError as e:
        raise GooglePhotosException(e.args[0])

gdata.photos.service.PhotosService.InsertVideo = InsertVideo

def OAuth2Login(client_secrets, credential_store, email):
    scope='https://picasaweb.google.com/data/'
    user_agent='picasawebuploader'

    storage = Storage(credential_store)
    credentials = storage.get()
    if credentials is None or credentials.invalid:
        flow = flow_from_clientsecrets(client_secrets, scope=scope, redirect_uri='urn:ietf:wg:oauth:2.0:oob')
        uri = flow.step1_get_authorize_url()
        webbrowser.open(uri)
        code = raw_input('Enter the authentication code: ').strip()
        credentials = flow.step2_exchange(code)
        storage.put(credentials)

    if (credentials.token_expiry - datetime.utcnow()) < timedelta(minutes=5):
        http = httplib2.Http()
        http = credentials.authorize(http)
        credentials.refresh(http)

    gd_client = gdata.photos.service.PhotosService(source=user_agent,
                                                   email=email,
                                                   additional_headers={'Authorization' : 'Bearer %s' % credentials.access_token})

    return gd_client

def protectWebAlbums(gd_client):
    albums = gd_client.GetUserFeed()
    for album in albums.entry:
        #print('title: %s, number of photos: %s, id: %s summary: %s access: %s\n' % (album.title.text,
        # album.numphotos.text, album.gphoto_id.text, album.summary.text, album.access.text))
        needUpdate = False
        if album.access.text != 'protected' and album.title.text not in ['Auto Backup', 'Profile Photos', 'Scrapbook Photos']:
            album.access.text = 'protected'
            needUpdate = True
        # print album
        if needUpdate:
            print("updating " + album.title.text)
            try:
                updated_album = gd_client.Put(album, album.GetEditLink().href,
                        converter=gdata.photos.AlbumEntryFromString)
            except gdata.service.RequestError as e:
                print("Could not update album: " + str(e))

def getWebAlbums(gd_client):
    albums = gd_client.GetUserFeed()
    d = {}
    for album in albums.entry:
        title = album.title.text
        if title in d:
          print("Duplicate web album:" + title)
        else:
          d[title] = album
        # print('title: %s, number of photos: %s, id: %s' % (album.title.text,
        #    album.numphotos.text, album.gphoto_id.text))
        #print(vars(album))
    return d

def findAlbum(gd_client, title):
    albums = gd_client.GetUserFeed()
    for album in albums.entry:
        if album.title.text == title:
            return album
    return None

def createAlbum(gd_client, title):
    print("Creating album " + title)
    # public, private, protected. private == "anyone with link"
    album = gd_client.InsertAlbum(title=title, summary='', access='protected')
    return album

def findOrCreateAlbum(gd_client, title):
    delay = 1
    while True:
        try:
            album = findAlbum(gd_client, title)
            if not album:
                album = createAlbum(gd_client, title)
            return album
        except gdata.photos.service.GooglePhotosException as e:
            print("caught exception " + str(e))
            print("sleeping for " + str(delay) + " seconds")
            time.sleep(delay)
            delay = delay * 2

def postPhoto(gd_client, album, filename):
    album_url = '/data/feed/api/user/%s/albumid/%s' % (gd_client.email, album.gphoto_id.text)
    photo = gd_client.InsertPhotoSimple(album_url, 'New Photo',
            'Uploaded using the API', filename, content_type='image/jpeg')
    return photo

def postPhotoToAlbum(gd_client, photo, album):
    album = findOrCreateAlbum(gd_client, args.album)
    photo = postPhoto(gd_client, album, args.source)
    return photo

def getWebPhotosForAlbum(gd_client, album):
    photos = gd_client.GetFeed(
            '/data/feed/api/user/%s/albumid/%s?kind=photo' % (
            gd_client.email, album.gphoto_id.text))
    return photos.entry

allExtensions = {}

# key: extension, value: type
knownExtensions = {
    '.png': 'image/png',
    '.jpeg': 'image/jpeg',
    '.jpg': 'image/jpeg',
    '.avi': 'video/avi',
    '.wmv': 'video/wmv',
    '.3gp': 'video/3gp',
    '.m4v': 'video/m4v',
    '.mp4': 'video/mp4',
    '.mov': 'video/mov'
    }

def getContentType(filename):
    ext = os.path.splitext(filename)[1].lower()
    if ext in knownExtensions:
        return knownExtensions[ext]
    else:
        return None

def accumulateSeenExtensions(filename):
    ext = os.path.splitext(filename)[1].lower()
    if ext in allExtensions:
        allExtensions[ext] = allExtensions[ext] + 1
    else:
        allExtensions[ext] = 1

def isMediaFilename(filename):
    accumulateSeenExtensions(filename)
    return getContentType(filename) != None

def visit(arg, dirname, names):
    basedirname = os.path.basename(dirname)
    if basedirname.startswith('.'):
        return
    mediaFiles = [name for name in names if not name.startswith('.') and isMediaFilename(name) and
        os.path.isfile(os.path.join(dirname, name))]
    count = len(mediaFiles)
    if count > 0:
        arg[dirname] = {'files': sorted(mediaFiles)}

def findMedia(source):
    hash = {}
    os.path.walk(source, visit, hash)
    return hash

def findDupDirs(photos):
    d = {}
    for i in photos:
        base = os.path.basename(i)
        if base in d:
            print("duplicate " + base + ":\n" + i + ":\n" + d[base])
            dc = filecmp.dircmp(i, d[base])
            print(dc.diff_files)
        d[base] = i
    # print([len(photos[i]['files']) for i in photos])

def toBaseName(photos):
    d = {}
    for i in photos:
        base = os.path.basename(i)
        if base in d:
            print("duplicate " + base + ":\n" + i + ":\n" + d[base]['path'])
            raise Exception("duplicate base")
        p = photos[i]
        p['path'] = i
        d[base] = p
    return d

def compareLocalToWeb(local, web):
    localOnly = []
    both = []
    webOnly = []
    for i in local:
        if i in web:
            both.append(i)
        else:
            localOnly.append(i)
    for i in web:
        if i not in local:
            webOnly.append(i)
    return {'localOnly' : localOnly, 'both' : both, 'webOnly' : webOnly}

def compareLocalToWebDir(localAlbum, webPhotoDict):
    localOnly = []
    both = []
    webOnly = []
    for i in localAlbum:
        if i in webPhotoDict:
            both.append(i)
        else:
            localOnly.append(i)
    for i in webPhotoDict:
        if i not in localAlbum:
            webOnly.append(i)
    return {'localOnly' : localOnly, 'both' : both, 'webOnly' : webOnly}

def syncDirs(gd_client, dirs, local, web):
    for dir in dirs:
        syncDir(gd_client, dir, local[dir], web[dir])

def syncDir(gd_client, dir, localAlbum, webAlbum):
    webPhotos = getWebPhotosForAlbum(gd_client, webAlbum)
    webPhotoDict = {}
    for photo in webPhotos:
        title = photo.title.text
        if title in webPhotoDict:
            print("duplicate web photo: " + webAlbum.title.text + " " + title)
        else:
            webPhotoDict[title] = photo
    report = compareLocalToWebDir(localAlbum['files'], webPhotoDict)
    localOnly = report['localOnly']
    for f in localOnly:
        localPath = os.path.join(localAlbum['path'], f)
        upload(gd_client, localPath, webAlbum, f)

def uploadDirs(gd_client, dirs, local):
    for dir in dirs:
        uploadDir(gd_client, dir, local[dir])

def uploadDir(gd_client, dir, localAlbum):
    webAlbum = findOrCreateAlbum(gd_client, dir)
    for f in localAlbum['files']:
        localPath = os.path.join(localAlbum['path'], f)
        upload(gd_client, localPath, webAlbum, f)

# Global used for a temp directory
gTempDir = ''

def getTempPath(localPath):
    baseName = os.path.basename(localPath)
    global gTempDir
    if gTempDir == '':
        gTempDir = tempfile.mkdtemp('imageshrinker')
    tempPath = os.path.join(gTempDir, baseName)
    return tempPath

def upload(gd_client, localPath, album, fileName):
    print("Uploading " + localPath)
    contentType = getContentType(fileName)

    if contentType.startswith('image/'):
        isImage = True
        picasa_photo = gdata.photos.PhotoEntry()
    else:
        size = os.path.getsize(localPath)

        # tested by cpbotha on 2013-05-24
        # this limit still exists
        if size > PICASA_MAX_VIDEO_SIZE_BYTES:
            print("Video file too big to upload: " + str(size) + " > " + str(PICASA_MAX_VIDEO_SIZE_BYTES))
            return
        isImage = False
        picasa_photo = VideoEntry()
    picasa_photo.title = atom.Title(text=fileName)
    picasa_photo.summary = atom.Summary(text='', summary_type='text')
    delay = 1
    while True:
        try:
            if isImage:
                gd_client.InsertPhoto(album, picasa_photo, localPath, content_type=contentType)
            else:
                gd_client.InsertVideo(album, picasa_photo, localPath, content_type=contentType)
            break
        except gdata.photos.service.GooglePhotosException as e:
          print("Got exception " + str(e))
          print("retrying in " + str(delay) + " seconds")
          time.sleep(delay)
          delay = delay * 2

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Uploads photos to Google Photos / Google+ / Picasa Web Albums.')
    parser.add_argument('--email', help='the google account email to use (example@gmail.com)', required=True)
    parser.add_argument('--source', help='the directory to upload', required=True)
    args = parser.parse_args()
    email = args.email

    # options for oauth2 login
    configdir = os.path.expanduser('~/.config/picasawebuploader')
    client_secrets = os.path.join(configdir, 'client_secrets.json')
    credential_store = os.path.join(configdir, 'credentials.dat')

    gd_client = OAuth2Login(client_secrets, credential_store, email)
    #protectWebAlbums(gd_client)
    webAlbums = getWebAlbums(gd_client)
    localAlbums = toBaseName(findMedia(args.source))
    albumDiff = compareLocalToWeb(localAlbums, webAlbums)
    syncDirs(gd_client, albumDiff['both'], localAlbums, webAlbums)
    uploadDirs(gd_client, albumDiff['localOnly'], localAlbums)
