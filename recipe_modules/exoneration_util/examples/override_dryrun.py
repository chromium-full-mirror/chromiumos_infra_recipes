# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.exoneration_util.exoneration_util import ExonerationUtilProperties
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'exoneration_util',
    'test_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  api.exoneration_util.override_dryrun()


def GenTests(api):
  chromite_repo = 'chromiumos/chromite'
  chromite_change = GerritChange(project=chromite_repo)
  non_chromite_change = GerritChange(project='infra/recipes')

  yield api.test('noop')

  yield api.test(
      'override',
      api.test_util.test_build(extra_changes=[chromite_change]).build,
      api.properties(
          **{
              '$chromeos/exoneration_util':
                  ExonerationUtilProperties(enablement_repos=[chromite_repo])
          }))

  yield api.test(
      'dont-override',
      api.test_util.test_build(extra_changes=[non_chromite_change]).build,
      api.properties(
          **{
              '$chromeos/exoneration_util':
                  ExonerationUtilProperties(enablement_repos=[chromite_repo])
          }))
