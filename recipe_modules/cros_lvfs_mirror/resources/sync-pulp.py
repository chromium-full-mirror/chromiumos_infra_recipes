#!/usr/bin/env vpython3
#
# Copyright (C) 2020 Richard Hughes <richard@hughsie.com>
#
# SPDX-License-Identifier: GPL-2.0+
#
# pylint: disable=too-few-public-methods
#
# [VPYTHON:BEGIN]
# python_version: "3.11"
# wheel: <
#   name: "infra/python/wheels/requests-py2_py3"
#   version: "version:2.21.0"
# >
# wheel: <
#   name: "infra/python/wheels/urllib3-py2_py3"
#   version: "version:1.24.3"
# >
# wheel: <
#   name: "infra/python/wheels/certifi-py2_py3"
#   version: "version:2019.3.9"
# >
# wheel: <
#   name: "infra/python/wheels/chardet-py2_py3"
#   version: "version:3.0.4"
# >
# wheel: <
#   name: "infra/python/wheels/idna-py2_py3"
#   version: "version:2.8"
# >
# wheel: <
#   name: "infra/python/wheels/pyopenssl-py2_py3"
#   version: "version:19.0.0"
# >
# wheel: <
#   name: "infra/python/wheels/cryptography/${vpython_platform}"
#   version: "version:3.3.2"
# >
# wheel: <
#   name: "infra/python/wheels/enum34-py3"
#   version: "version:1.1.6"
# >
# wheel: <
#   name: "infra/python/wheels/cffi/${vpython_platform}"
#   version: "version:1.15.1"
# >
# wheel: <
#   name: "infra/python/wheels/pycparser-py2_py3"
#   version: "version:2.19"
# >
# wheel: <
#   name: "infra/python/wheels/six-py2_py3"
#   version: "version:1.10.0"
# >
# [VPYTHON:END]

"""Mirror lvfs servers.

Download all the cab and xml files from LVFS (fwupd.org) servers.
Skip the files that already exist on GCS.
"""

import os
import posixpath
import re
import sys

import requests

# pylint: disable=superfluous-parens


class Pulp:

  def __init__(self, url, existent):
    self.url = url
    self.existent = open(existent, 'r', encoding='utf-8')  # pylint: disable=consider-using-with
    self.manifest = 'PULP_MANIFEST'
    self.useragent = os.path.basename(sys.argv[0])
    self.session = requests.Session()

  def _download_file(self, fn, path):

    url_fn = posixpath.join(self.url, fn)
    print('Downloading {}…'.format(url_fn))
    try:
      headers = {
          'User-Agent': self.useragent,
      }
      rv = self.session.get(url_fn, headers=headers, timeout=5)

      # This will raise an exception for HTTP error status codes.
      rv.raise_for_status()
    except (
        requests.exceptions.ConnectionError,
        requests.exceptions.ReadTimeout,
        requests.exceptions.HTTPError,
    ) as e:
      print(str(e))
    else:
      with open(os.path.join(path, fn), 'wb') as f:
        f.write(rv.content)

  def _sync_file(self, fn, path):

    self.existent.seek(0)
    for line in self.existent:
      if re.search(fn, line):
        return
    self._download_file(fn, path)

  def sync(self, path):

    # check dir exists
    if not os.path.exists(path):
      print('{} does not exist'.format(path))
      return 1

    # download the PULP_MANIFEST
    try:
      print('Downloading {}…'.format(self.manifest))
      url_manifest = posixpath.join(self.url, self.manifest)
      headers = {
          'User-Agent': self.useragent,
      }
      rv = self.session.get(url_manifest, headers=headers, timeout=5)
    except (
        requests.exceptions.ConnectionError,
        requests.exceptions.ReadTimeout,
    ) as e:
      print(str(e))
      return 1

    # parse into lines
    for line in rv.content.decode().split('\n'):
      try:
        fn, _, _ = line.rsplit(',', 2)
      except ValueError:
        continue
      self._sync_file(fn, path)

    # success
    return 0


if __name__ == '__main__':

  if len(sys.argv) != 4:
    print('USAGE: URL DIR EXISTENT')
    sys.exit(2)

  pulp = Pulp(url=sys.argv[1], existent=sys.argv[3])
  sys.exit(pulp.sync(sys.argv[2]))
