#!/usr/bin/env python

"""A utility to export tumblr posts into markdown files."""

import re
import os.path
import argparse

import jinja2
import requests
import dateutil.parser
import dateutil.tz


API_KEY = "fuiKNFp9vQFvjLNvx4sUwti4Yb5yGutBN4Xh10LXZhhRKjWlV4"
API_URL = "http://api.tumblr.com/v2/blog"
API_URL_POSTS = API_URL + "/{domain}/posts/{post_type}" \
    "?api_key={api_key}&filter=raw"


TEMPLATE = jinja2.Template('''
---
layout: post
title: "{{ post.title }}"
date: {{ post.date.strftime("%H-%m-%d %H:%M") }}
comments: true
categories:
    {%- for tag in post.tags %}
    - {{ tag }}
    {%- endfor %}
---

{{ post.body }}
'''.strip())


def get_posts(domain, post_type="text"):
    url = API_URL_POSTS.format(url_base=API_URL, domain=domain,
                               post_type=post_type, api_key=API_KEY)
    data = requests.get(url).json()
    assert data["meta"]["status"] == 200, repr(data["meta"])
    for post in data["response"]["posts"]:
        post["utcdate"] = dateutil.parser.parse(post["date"])
        post["date"] = post["utcdate"].astimezone(dateutil.tz.tzlocal())
        if not post["slug"].strip():
            post["slug"] = str(post["id"])
        yield post


class PostConverter(object):

    def __init__(self, target_directory, template):
        if not os.path.exists(target_directory):
            os.mkdir(target_directory)
        if not os.path.isdir(target_directory):
            raise IOError("%s is not direcotry" % target_directory)

        self.target_directory = target_directory
        self.template = template
        self.middlewares = []

    def open_postfile(self, slug, date):
        filename = "%s-%s" % (date.strftime("%Y-%m-%d"), slug.strip("-"))
        return open(os.path.join(self.target_directory, filename), "w")

    def record_redirect(self, post_id, slug):
        old_url = "/post/%d/%s" % (post_id, slug)
        new_url = "/post/%s" % slug
        with open(os.path.join(self.target_directory, "_redirect"), "a") as db:
            db.write("%s:%s\n" % (old_url, new_url))

    def convert(self, post):
        with self.open_postfile(post["slug"], post["date"]) as postfile:
            for middleware in self.middlewares:
                post["body"] = middleware(post["body"])
            postfile.write(self.template.render(post=post))
        self.record_redirect(post["id"], post["slug"])


class CodeBlockMiddleware(object):

    def __init__(self):
        self.re_begin = re.compile(r'<pre' r'\s' r'class="brush:(\w+)">')
        self.re_end = re.compile(r'</pre>')
        self.is_in_block = False

    def _handle_line(self, line):
        matched_begin = self.re_begin.match(line)
        matched_end = self.re_end.match(line)
        if matched_begin:
            self.is_in_block = True
            return "```%s" % matched_begin.group(1)
        elif matched_end:
            self.is_in_block = False
            return "```"
        else:
            if self.is_in_block:
                line = line.replace("&gt;", ">").replace("&lt;", "<")
            return line

    def __call__(self, body):
        return "\n".join(self._handle_line(l) for l in body.split("\n"))


def main():
    #: parse arguments
    option = argparse.ArgumentParser(description=__doc__)
    option.add_argument("-d", "--domain", required=True, type=str,
                        help="The domain of tumblr blog")
    option.add_argument("-t", "--target-directory", type=str,
                        default="./posts",
                        help="The target directory to locate output files")
    args = option.parse_args()

    #: convert posts
    converter = PostConverter(args.target_directory, TEMPLATE)
    converter.middlewares.append(CodeBlockMiddleware())
    for post in get_posts(args.domain):
        converter.convert(post)
        print("* %d:%s" % (post["id"], post["slug"]))


if __name__ == "__main__":
    main()
