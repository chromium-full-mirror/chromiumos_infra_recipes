# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.recipe_modules.chromeos.gerrit.examples.parse_gerrit_change import (
    ParseGerritChangeProperties)

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'gerrit',
]


PROPERTIES = ParseGerritChangeProperties


def RunSteps(api, properties):
  gerrit_change = api.gerrit.parse_gerrit_change(properties.gerrit_change_url)
  api.assertions.assertEqual(gerrit_change.host, properties.expected.host)
  api.assertions.assertEqual(gerrit_change.project, properties.expected.project)
  api.assertions.assertEqual(gerrit_change.change, properties.expected.change)
  api.assertions.assertEqual(gerrit_change.patchset,
                             properties.expected.patchset)


def GenTests(api):
  # TODO(evanhernandez): Yuck. Remove this.
  api.gerrit.test_gerrit_change_url()

  yield api.test(
      'parse-full-url',
      api.properties(
          gerrit_change_url=('https://chromium-review.googlesource.com/c/'
                             'chromiumos/chromite/+/12345/6'),
          expected=GerritChange(
              host='chromium-review.googlesource.com',
              project='chromiumos/chromite',
              change=12345,
              patchset=6,
          )))

  yield api.test(
      'parse-no-patchset-url',
      api.properties(
          gerrit_change_url=('https://chromium-review.googlesource.com/c/'
                             'chromiumos/chromite/+/12345'),
          expected=GerritChange(
              host='chromium-review.googlesource.com',
              project='chromiumos/chromite',
              change=12345,
          )))

  yield api.test(
      'parse-no-https-url',
      api.properties(
          gerrit_change_url=(
              'chromium-review.googlesource.com/c/chromiumos/chromite/+/12345'),
          expected=GerritChange(
              host='chromium-review.googlesource.com',
              project='chromiumos/chromite',
              change=12345,
          )))

  yield api.test(
      'parse-no-project-url',
      api.properties(
          gerrit_change_url=(
              'https://chrome-internal-review.googlesource.com/12345'),
          expected=GerritChange(
              host='chrome-internal-review.googlesource.com',
              change=12345,
          )))

  yield api.test(
      'parse-no-project-no-https-url',
      api.properties(
          gerrit_change_url='chrome-internal-review.googlesource.com/12345',
          expected=GerritChange(
              host='chrome-internal-review.googlesource.com',
              change=12345,
          )))

  yield api.test(
      'parse-coreboot-style-url',
      api.properties(
          gerrit_change_url='https://review.coreboot.org/c/em100/+/30938/3',
          expected=GerritChange(
              host='review.coreboot.org',
              project='em100',
              change=30938,
              patchset=3,
          )))

  yield api.test(
      'parse-coreboot-style-no-patchset-url',
      api.properties(
          gerrit_change_url='https://review.coreboot.org/c/em100/+/30938',
          expected=GerritChange(
              host='review.coreboot.org',
              project='em100',
              change=30938,
          )))
