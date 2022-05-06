# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.recipe_modules.chromeos.gerrit.examples.parse_gerrit_change_url import (
    ParseGerritChangeUrlProperties)

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'gerrit',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

PROPERTIES = ParseGerritChangeUrlProperties


def RunSteps(api, properties):
  gerrit_change_url = api.gerrit.parse_gerrit_change_url(
      properties.gerrit_change)
  api.assertions.assertEqual(gerrit_change_url, properties.expected)


def GenTests(api):
  host = 'chrome-internal.googlesource.com'
  yield api.test(
      'parse-full-url',
      api.properties(
          gerrit_change=GerritChange(
              host=host,
              project='infra/config',
              change=12345,
              patchset=6,
          ), expected=('https://{}/c/infra/config/+/12345/6'.format(host))))

  yield api.test(
      'parse-partial-url',
      api.properties(
          gerrit_change=GerritChange(
              host='chrome-internal.googlesource.com',
              change=12345,
          ), expected='https://chrome-internal.googlesource.com/12345'))
