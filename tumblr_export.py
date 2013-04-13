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
        post["new_slug"] = post["slug"]
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

    def open_postfile(self, new_slug, date):
        daterepr = date.strftime("%Y-%m-%d")
        cleaned_slug = "-".join(p for p in new_slug.split("-") if p)
        filename = "%s-%s.markdown" % (daterepr, cleaned_slug)
        return open(os.path.join(self.target_directory, filename), "w")

    def convert(self, post):
        for middleware in self.middlewares:
            try:
                post = middleware(post)
            except SkipPostException:
                return
        with self.open_postfile(post["new_slug"], post["date"]) as postfile:
            postfile.write(self.template.render(post=post))


class SkipPostException(Exception):
    pass


class DisqusMigrationMiddleware(object):

    def __init__(self, to_domain, output_file, has_slug=False):
        self.to_domain = to_domain
        self.output_file = output_file
        self.has_slug = has_slug

    def __call__(self, post):
        new_url = "http://%s/post/%s" % (self.to_domain, post["new_slug"])
        old_url = "http://%s/post/%s" % (self.to_domain, post["id"])
        if self.has_slug and post["slug"] != post["id"]:
            old_url += "/%s" % post["slug"]
        with open(self.output_file, "a") as csv_file:
            csv_file.write("%s, %s\n" % (old_url, new_url))
        return post


class NginxMapMiddleware(object):

    def __init__(self, output_file):
        self.output_file = output_file

    def __call__(self, post):
        args = (post["id"], post["new_slug"])
        with open(self.output_file, "a") as conf_file:
            conf_file.write("~^/post/%s(/.*)?  /post/%s;\n" % args)
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


def screen_log_middleware(post):
    print("* %d:%s:%s" % (post["id"], post["slug"], post["new_slug"]))
    return post


def rename_slug_middleware(post):
    new_slug = input("[{id}] {slug} {title}: ".format(**post)).strip()
    if new_slug:
        if new_slug == "!":
            raise SkipPostException
        post["new_slug"] = new_slug
    return post


def main():
    #: parse arguments
    option = argparse.ArgumentParser(description=__doc__)
    option.add_argument("-f", "--from-domain", required=True, type=str,
                        help="domain of tumblr blog")
    option.add_argument("-t", "--to-domain", required=True, type=str,
                        help="domain of new site")
    option.add_argument("-o", "--output-directory", type=str,
                        default="./posts",
                        help="target directory to locate output files")
    option.add_argument("--offset", type=int, default=0,
                        help="post number to start at")
    option.add_argument("--limit", type=int, default=20,
                        help="number of posts to return")
    option.add_argument("--disqus-url-map", type=str,
                        default="./disqus-url-map.csv",
                        help="url map file for disqus migration")
    option.add_argument("--disqus-url-map-has-slug", type=bool, default=False,
                        help="tumblr urls included slug or not.")
    option.add_argument("--nginx-url-map", type=str,
                        default="./nginx-url-map.conf",
                        help="url map file for nginx")
    option.add_argument("--rename-slug", type=bool, default=True,
                        help="rename slug of urls or not")
    args = option.parse_args()

    #: convert posts
    converter = PostConverter(args.output_directory, TEMPLATE)
    if args.rename_slug:
        print("-- type new slug after the prompt")
        print("-- if you type empty string, the origin value will be keep")
        print("-- if you type '!', the post will be skiped")
        converter.middlewares.append(rename_slug_middleware)
    else:
        converter.middlewares.append(screen_log_middleware)
    converter.middlewares.extend([
        CodeBlockMiddleware(),
        DisqusMigrationMiddleware(args.to_domain,
                                  output_file=args.disqus_url_map,
                                  has_slug=args.disqus_url_map_has_slug),
        NginxMapMiddleware(output_file=args.nginx_url_map),
    ])
    posts = get_posts(args.from_domain, offset=args.offset, limit=args.limit)
    for post in posts:
        converter.convert(post)


if __name__ == "__main__":
    main()
