#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Author: Patrick Mac Gregor
# @Date:   2018-05-12
# @Last Modified by:   Patrick Mac Gregor
# @Last Modified time: 2018-05-12

import os
import argparse
from classes.TokenRefreshingClient import TokenRefreshingClient
import gdata
import gdata.photos.service
import atom
import atom.service
import time
from gdata.photos.service import GPHOTOS_INVALID_ARGUMENT, GPHOTOS_INVALID_CONTENT_TYPE, GooglePhotosException


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


PICASA_MAX_VIDEO_SIZE_BYTES = 104857600


class VideoEntry(gdata.photos.PhotoEntry):
    pass


gdata.photos.VideoEntry = VideoEntry


def InsertVideo(self, album_or_uri, video, filename_or_handle, content_type='image/jpeg'):
    """Copy of InsertPhoto which removes protections since it *should* work"""
    try:
        assert(isinstance(video, VideoEntry))
    except AssertionError:
        raise GooglePhotosException({
            'status': GPHOTOS_INVALID_ARGUMENT,
            'body': '`video` must be a gdata.photos.VideoEntry instance',
            'reason': 'Found %s, not PhotoEntry' % type(video)
        })
    try:
        majtype, mintype = content_type.split('/')
        # assert(mintype in SUPPORTED_UPLOAD_TYPES)
    except (ValueError, AssertionError):
        raise GooglePhotosException({
            'status': GPHOTOS_INVALID_CONTENT_TYPE,
            'body': 'This is not a valid content type: %s' % content_type,
            'reason': 'Accepted content types:'
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


def findMedia(source):
    hash = {}
    os.path.walk(source, visit, hash)
    return hash


def visit(arg, dirname, names):
    basedirname = os.path.basename(dirname)
    if basedirname.startswith('.'):
        return
    mediaFiles = [name for name in names if not name.startswith('.') and isMediaFilename(name) and
        os.path.isfile(os.path.join(dirname, name))]
    count = len(mediaFiles)
    if count > 0:
        arg[dirname] = {'files': sorted(mediaFiles)}


def isMediaFilename(filename):
    accumulateSeenExtensions(filename)
    return getContentType(filename) != None


def accumulateSeenExtensions(filename):
    ext = os.path.splitext(filename)[1].lower()
    if ext in allExtensions:
        allExtensions[ext] = allExtensions[ext] + 1
    else:
        allExtensions[ext] = 1


def getContentType(filename):
    ext = os.path.splitext(filename)[1].lower()
    if ext in knownExtensions:
        return knownExtensions[ext]
    else:
        return None


def toBaseName(photos):
    d = {}
    for i in photos:
        base = os.path.basename(i)
        print(base, i)
        if base in d:
            print("duplicate " + base + ":\n" + i + ":\n" + d[base]['path'])
            raise Exception("duplicate base")
        p = photos[i]
        p['path'] = i
        d[base] = p
    return d


def uploadDirs(gd_client, dir):
    webAlbum = findDefaultAlbum(gd_client)

    for path, localAlbum in dir.iteritems():
        for filename in localAlbum['files']:
            localPath = os.path.join(path, filename)
            upload(gd_client, localPath, webAlbum, filename)


defaultAlbum = None


def findDefaultAlbum(gd_client):
    global defaultAlbum
    if not defaultAlbum:
        defaultAlbum = findAlbum(gd_client, 'Auto Backup')
    if not defaultAlbum:
        raise Exception("Default Album not found!")

    return defaultAlbum


def findAlbum(gd_client, title):
    albums = gd_client.GetUserFeed()
    for album in albums.entry:
        if album.title.text == title:
            return album
    return None


def upload(gd_client, localPath, album, fileName):
    print("Uploading " + localPath)
    contentType = getContentType(fileName)

    if contentType.startswith('image/'):
        isImage = True
        mediaItem = gdata.photos.PhotoEntry()
    else:
        size = os.path.getsize(localPath)

        # tested by cpbotha on 2013-05-24
        # this limit still exists
        if size > PICASA_MAX_VIDEO_SIZE_BYTES:
            print("Video file too big to upload: " + str(size) + " > " + str(PICASA_MAX_VIDEO_SIZE_BYTES))
            return
        isImage = False
        mediaItem = VideoEntry()

    mediaItem.title = atom.Title(text=fileName)
    mediaItem.summary = atom.Summary(text='', summary_type='text')
    delay = 1
    while True:
        try:
            if isImage:
                gd_client.InsertPhoto(album, mediaItem, localPath, content_type=contentType)
            else:
                gd_client.InsertVideo(album, mediaItem, localPath, content_type=contentType)
            break
        except gdata.photos.service.GooglePhotosException as e:
            print("Got exception " + str(e))
            print("retrying in " + str(delay) + " seconds")
            time.sleep(delay)
            delay = delay * 2


def main():
    parser = argparse.ArgumentParser(
        description='Uploads photos to Google Photos / Google+ \
        Picasa Web Albums.'
    )
    parser.add_argument('--email', help='the google account email to use (example@gmail.com)', required=True)
    parser.add_argument('--source', help='the directory to upload', required=True)
    args = parser.parse_args()
    email = args.email

    configdir = os.path.expanduser('~/.config/picasawebuploader')
    client_secrets = os.path.join(configdir, 'client_secrets.json')
    credential_store = os.path.join(configdir, 'credentials.dat')

    gd_client = TokenRefreshingClient(client_secrets, credential_store, email)

    localAlbums = findMedia(args.source)
    uploadDirs(gd_client, localAlbums)


if __name__ == '__main__':
    main()
