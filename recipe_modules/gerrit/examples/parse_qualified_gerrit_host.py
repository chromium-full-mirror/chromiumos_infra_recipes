# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.recipe_modules.chromeos.gerrit.examples \
    .parse_qualified_gerrit_host import ParseQualifiedGerritHostProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'gerrit',
]


PROPERTIES = ParseQualifiedGerritHostProperties


def RunSteps(api, properties):
  qualified_gerrit_host = api.gerrit.parse_qualified_gerrit_host(
      properties.gerrit_change)
  api.assertions.assertEqual(qualified_gerrit_host, properties.expected)


def GenTests(api):
  yield api.test(
      'parse-stripped-host',
      api.properties(
          gerrit_change=GerritChange(
              host='chrome-internal.googlesource.com',
              project='infra/config',
              change=12345,
              patchset=6,
          ), expected='https://chrome-internal.googlesource.com'))

  yield api.test(
      'parse-http-host',
      api.properties(
          gerrit_change=GerritChange(
              host='http://chrome-internal.googlesource.com',
              change=12345,
          ), expected='https://chrome-internal.googlesource.com'))

  yield api.test(
      'parse-https-host',
      api.properties(
          gerrit_change=GerritChange(
              host='https://chrome-internal.googlesource.com',
              change=12345,
          ), expected='https://chrome-internal.googlesource.com'))
