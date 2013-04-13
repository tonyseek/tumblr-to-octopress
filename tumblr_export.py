#!/usr/bin/env python

"""A utility to export tumblr posts into markdown files."""

import re
import os.path
import argparse
import urllib.parse

import jinja2
import requests
import dateutil.parser
import dateutil.tz


API_KEY = "fuiKNFp9vQFvjLNvx4sUwti4Yb5yGutBN4Xh10LXZhhRKjWlV4"
API_URL = "http://api.tumblr.com/v2/blog"
API_URL_POSTS = API_URL + "/{domain}/posts/{post_type}" \
    "?api_key={api_key}&filter=raw&offset={offset}&limit={limit}"


TEMPLATE = jinja2.Template('''
---
layout: post
title: "{{ post.title }}"
date: {{ post.date.strftime("%Y-%m-%d %H:%M") }}
comments: true
tumblr_id: {{ post.id }}
categories:
    {%- for tag in post.tags %}
    - {{ tag }}
    {%- endfor %}
---

{{ post.body }}
'''.strip())


def get_posts(domain, post_type="text", offset=0, limit=20):
    url = API_URL_POSTS.format(url_base=API_URL, domain=domain,
                               post_type=post_type, api_key=API_KEY,
                               offset=offset, limit=limit)
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
        daterepr = date.strftime("%Y-%m-%d")
        filename = "%s-%s.markdown" % (daterepr, slug.strip("-"))
        return open(os.path.join(self.target_directory, filename), "w")

    def convert(self, post):
        with self.open_postfile(post["slug"], post["date"]) as postfile:
            for middleware in self.middlewares:
                post = middleware(post)
            postfile.write(self.template.render(post=post))


class DisqusMigrationMiddleware(object):

    def __init__(self, from_domain, to_domain, output_file, has_slug=False):
        self.from_domain = from_domain
        self.to_domain = to_domain
        self.output_file = output_file
        self.has_slug = has_slug

    def __call__(self, post):
        new_url = "http://%s/post/%s" % (self.to_domain, post["slug"])
        old_url = "http://%s/post/%s" % (self.to_domain, post["id"])
        if self.has_slug:
            old_url += "/%s" % post["slug"]
        with open(self.output_file, "a") as csv_file:
            csv_file.write("%s, %s\n" % (old_url, new_url))
        return post


class CodeBlockMiddleware(object):

    def __init__(self):
        self.re_begin = re.compile(r'<pre(?:\s+class="brush:\s*(\w+)")?>')
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

    def __call__(self, post):
        post["body"] = "\n".join(self._handle_line(line)
                                 for line in post["body"].split("\n"))
        return post


def main():
    #: parse arguments
    option = argparse.ArgumentParser(description=__doc__)
    option.add_argument("-f", "--from-domain", required=True, type=str,
                        help="The domain of tumblr blog")
    option.add_argument("-t", "--to-domain", required=True, type=str,
                        help="The new domain")
    option.add_argument("-o", "--output-directory", type=str,
                        default="./posts",
                        help="The target directory to locate output files")
    option.add_argument("--offset", type=int, default=0,
                        help="The post number to start at")
    option.add_argument("--limit", type=int, default=20,
                        help="The number of posts to return")
    option.add_argument("--disqus-url-map", type=str,
                        default="./disqus-url-map.csv",
                        help="The url map file for disqus migration")
    option.add_argument("--disqus-url-map-has-slug", type=bool, default=False,
                        help="The tumblr urls included slug or not.")
    args = option.parse_args()

    #: convert posts
    converter = PostConverter(args.output_directory, TEMPLATE)
    converter.middlewares.extend([
        CodeBlockMiddleware(),
        DisqusMigrationMiddleware(args.from_domain, args.to_domain,
                                  output_file=args.disqus_url_map,
                                  has_slug=args.disqus_url_map_has_slug),
    ])
    posts = get_posts(args.from_domain, offset=args.offset, limit=args.limit)
    for post in posts:
        converter.convert(post)
        print("* %d:%s" % (post["id"], post["slug"]))


if __name__ == "__main__":
    main()
