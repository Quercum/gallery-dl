# -*- coding: utf-8 -*-

# Copyright 2014-2017 Mike Fährmann
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation.

"""Extract images and ugoira from https://www.pixiv.net/"""

from .common import Extractor, Message
from .. import text, exception
from ..cache import cache
import re


class PixivExtractor(Extractor):
    """Base class for pixiv extractors"""
    category = "pixiv"
    directory_fmt = ["{category}", "{user[id]} {user[account]}"]
    filename_fmt = "{category}_{user[id]}_{id}{num}.{extension}"
    illust_url = "https://www.pixiv.net/member_illust.php?mode=medium"

    def __init__(self):
        Extractor.__init__(self)
        self.api = PixivAPI(self)
        self.user_id = -1
        self.load_ugoira = self.config("ugoira", True)

    def items(self):
        metadata = self.get_metadata()

        yield Message.Version, 1
        yield Message.Headers, self.session.headers
        yield Message.Cookies, self.session.cookies
        yield Message.Directory, metadata

        for work in self.works():
            work = self.prepare_work(work)

            pos = work["extension"].rfind("?", -18)
            if pos != -1:
                timestamp = work["extension"][pos:]
                work["extension"] = work["extension"][:pos]
            else:
                timestamp = ""

            if work["type"] == "ugoira":
                if not self.load_ugoira:
                    continue
                url, framelist = self.parse_ugoira(work)
                work["extension"] = "zip"
                yield Message.Url, url, work
                work["extension"] = "txt"
                yield Message.Url, "text:"+framelist, work

            elif work["page_count"] == 1:
                yield Message.Url, work["url"], work

            else:
                url = work["url"]
                ext = work["extension"]
                off = url.rfind(".")
                if url[off-2] == "p":
                    off -= 3
                if work["id"] > 11319935 and "/img-original/" not in url:
                    big = "_big"
                else:
                    big = ""
                for i in range(work["page_count"]):
                    work["num"] = "_p{:02}".format(i)
                    url = "{}{}_p{}.{}{}".format(
                        url[:off], big, i, ext, timestamp
                    )
                    yield Message.Url, url, work

    def works(self):
        """Return all work-items for a pixiv-member"""
        return []

    def prepare_work(self, work):
        """Prepare a work-dictionary with additional keywords"""
        url = work["image_urls"]["large"]
        work["num"] = ""
        work["url"] = url
        work["extension"] = url[url.rfind(".")+1:]
        return work

    def parse_ugoira(self, data):
        """Parse ugoira data"""
        # get illust page
        page = self.request(
            self.illust_url, params={"illust_id": data["id"]},
        ).text

        # parse page
        frames = text.extract(page, ',"frames":[', ']')[0]

        # build url
        url = re.sub(
            r"/img-original/(.+/\d+)[^/]+",
            r"/img-zip-ugoira/\g<1>_ugoira1920x1080.zip",
            data["url"]
        )

        # build framelist
        framelist = re.sub(
            r'\{"file":"([^"]+)","delay":(\d+)\},?',
            r'\1 \2\n', frames
        )

        return url, framelist

    def get_metadata(self, user=None):
        """Collect metadata for extractor-job"""
        if not user:
            user = self.api.user(self.user_id)[0]
        return {"user": user}


class PixivUserExtractor(PixivExtractor):
    """Extractor for works of a pixiv-user"""
    subcategory = "user"
    pattern = [r"(?:https?://)?(?:www\.)?pixiv\.net/"
               r"member(?:_illust)?\.php\?id=(\d+)(?:.*&tag=([^&#]+))?"]
    test = [
        ("http://www.pixiv.net/member_illust.php?id=173530", {
            "url": "852c31ad83b6840bacbce824d85f2a997889efb7",
        }),
        ("https://www.pixiv.net/member_illust.php?id=173530&tag=HITMAN", {
            "url": "3ecb4970dd91ce1de0a9449671b42db5e3fe2b08",
        }),
        ("http://www.pixiv.net/member_illust.php?id=173531", {
            "exception": exception.NotFoundError,
        }),
    ]

    def __init__(self, match):
        PixivExtractor.__init__(self)
        self.user_id, tag = match.groups()
        self.tag = tag.lower() if tag else None

    def works(self):
        for work in self.api.user_works(self.user_id):
            if (not self.tag or
                    self.tag in [tag.lower() for tag in work["tags"]]):
                yield work


class PixivWorkExtractor(PixivExtractor):
    """Extractor for a single pixiv work/illustration"""
    subcategory = "work"
    pattern = [(r"(?:https?://)?(?:www\.)?pixiv\.net/member(?:_illust)?\.php"
                r"\?(?:[^&]+&)*illust_id=(\d+)"),
               (r"(?:https?://)?i(?:\d+\.pixiv|\.pximg)\.net(?:/.*)?/img-[^/]+"
                r"/img/\d{4}(?:/\d\d){5}/(\d+)"),
               (r"(?:https?://)?img\d+\.pixiv\.net/img/[^/]+/(\d+)")]
    test = [
        (("http://www.pixiv.net/member_illust.php"
          "?mode=medium&illust_id=966412"), {
            "url": "90c1715b07b0d1aad300bce256a0bc71f42540ba",
            "content": "69a8edfb717400d1c2e146ab2b30d2c235440c5a",
        }),
        (("http://www.pixiv.net/member_illust.php"
          "?mode=medium&illust_id=966411"), {
            "exception": exception.NotFoundError,
        }),
        (("http://i1.pixiv.net/c/600x600/img-master/"
          "img/2008/06/13/00/29/13/966412_p0_master1200.jpg"), {
            "url": "90c1715b07b0d1aad300bce256a0bc71f42540ba",
        }),
        (("https://i.pximg.net/img-original/"
          "img/2017/04/25/07/33/29/62568267_p0.png"), {
            "url": "71b8bbd070d6b03a75ca4afb89f64d1445b2278d",
        }),
    ]

    def __init__(self, match):
        PixivExtractor.__init__(self)
        self.illust_id = match.group(1)
        self.load_ugoira = True
        self.work = None

    def works(self):
        return (self.work,)

    def get_metadata(self, user=None):
        self.work = self.api.work(self.illust_id)[0]
        return PixivExtractor.get_metadata(self, self.work["user"])


class PixivFavoriteExtractor(PixivExtractor):
    """Extractor for all favorites/bookmarks of a pixiv-user"""
    subcategory = "favorite"
    directory_fmt = ["{category}", "bookmarks", "{user[id]} {user[account]}"]
    pattern = [r"(?:https?://)?(?:www\.)?pixiv\.net/bookmark\.php\?id=(\d+)"]
    test = [("http://www.pixiv.net/bookmark.php?id=173530", {
        "url": "e717eb511500f2fa3497aaee796a468ecf685cc4",
    })]

    def __init__(self, match):
        PixivExtractor.__init__(self)
        self.user_id = match.group(1)

    def works(self):
        return self.api.user_favorite_works(self.user_id)

    def prepare_work(self, work):
        return PixivExtractor.prepare_work(self, work["work"])


class PixivBookmarkExtractor(PixivFavoriteExtractor):
    """Extractor for all favorites/bookmarks of your own account"""
    subcategory = "bookmark"
    pattern = [r"(?:https?://)?(?:www\.)?pixiv\.net/bookmark\.php()$"]
    test = []

    def get_metadata(self, user=None):
        self.api.login()
        user = self.api.user_info
        self.user_id = user["id"]
        return PixivExtractor.get_metadata(self, user)


class PixivAPI():
    """Minimal interface for the Pixiv Public-API for mobile devices

    For a better and more complete implementation, see
    - https://github.com/upbit/pixivpy
    For in-depth information regarding the Pixiv Public-API, see
    - http://blog.imaou.com/opensource/2014/10/09/pixiv_api_for_ios_update.html
    """
    def __init__(self, extractor):
        self.session = extractor.session
        self.log = extractor.log
        self.username = extractor.config("username")
        self.password = extractor.config("password")
        self.user_info = None
        self.session.headers.update({
            "Referer": "https://www.pixiv.net/",
            'App-OS': 'ios',
            'App-OS-Version': '10.3.1',
            'App-Version': '6.7.1',
            'User-Agent': 'PixivIOSApp/6.7.1 (iOS 10.3.1; iPhone8,1)',
        })

    def user(self, user_id):
        """Query information about a pixiv user"""
        endpoint = "users/" + user_id
        return self._call(endpoint, {})["response"]

    def work(self, illust_id):
        """Query information about a single pixiv work/illustration"""
        endpoint = "works/" + illust_id
        params = {"image_sizes": "large"}
        return self._call(endpoint, params)["response"]

    def user_works(self, user_id):
        """Query information about the works of a pixiv user"""
        endpoint = "users/{user}/works".format(user=user_id)
        params = {"image_sizes": "large"}
        return self._pagination(endpoint, params)

    def user_favorite_works(self, user_id):
        """Query information about the favorite works of a pixiv user"""
        endpoint = "users/{user}/favorite_works".format(user=user_id)
        params = {"image_sizes": "large", "include_stats": False}
        return self._pagination(endpoint, params)

    def login(self):
        """Login and gain a Pixiv Public-API access token"""
        self.user_info, access_token = self._login_impl(
            self.username, self.password)
        self.session.headers["Authorization"] = access_token

    @cache(maxage=50*60, keyarg=1)
    def _login_impl(self, username, password):
        """Actual login implementation"""
        self.log.info("Logging in as %s", username)
        data = {
            "username": username,
            "password": password,
            "grant_type": "password",
            "client_id": "bYGKuGVw91e0NMfPGp44euvGt59s",
            "client_secret": "HP3RmkgAmEGro0gn1x9ioawQE8WMfvLXDz3ZqxpK",
            "get_secure_url": 1,
        }
        response = self.session.post(
            "https://oauth.secure.pixiv.net/auth/token", data=data
        )
        if response.status_code != 200:
            raise exception.AuthenticationError()
        try:
            response = response.json()["response"]
            token = response["access_token"]
            user = response["user"]
        except KeyError:
            raise Exception("Get token error! Response: %s" % (response))
        return user, "Bearer " + token

    def _call(self, endpoint, params, _empty=[None]):
        url = "https://public-api.secure.pixiv.net/v1/" + endpoint + ".json"

        self.login()
        data = self.session.get(url, params=params).json()

        status = data.get("status")
        response = data.get("response", _empty)
        if status == "failure" or response == _empty:
            raise exception.NotFoundError()
        return data

    def _pagination(self, endpoint, params):
        while True:
            data = self._call(endpoint, params)
            yield from data["response"]

            pinfo = data["pagination"]
            if pinfo["current"] == pinfo["pages"]:
                return
            params["page"] = pinfo["next"]
