# -*- codiing: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for get_change_infos_from_gerrit function."""
from recipe_engine import post_process
from recipe_engine.post_process import DropExpectation, MustRun
from PB.recipe_modules.chromeos.auto_runner_util.auto_runner_util import HostProjects

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'auto_runner_util',
]
QUERY_PARAMS = (
    ('status', 'open'),
    ('label', 'Commit-Queue<=0'),
)

O_PARAMS = [
    'COMMIT_FOOTERS',
]

TEST_HOST_PROJECTS_PREFIXES = [
    HostProjects(host='chromium', project_prefix=['chromiumos']),
]


def RunSteps(api):
  api.auto_runner_util.get_change_infos_from_gerrit(TEST_HOST_PROJECTS_PREFIXES,
                                                    query_params=QUERY_PARAMS,
                                                    o_params=O_PARAMS)


def GenTests(api):
  yield api.test(
      'basic',
      api.post_process(
          MustRun,
          'Looking for CLs in host %s' % TEST_HOST_PROJECTS_PREFIXES[0].host),
      api.post_process(
          post_process.StepCommandContains,
          '''Looking for CLs in host chromium.Looking for CLs in project chromiumos.query https://chromium-review.googlesource.com.gerrit changes''',
          [
              '-p', 'status=open', '-p', 'label=Commit-Queue<=0', '-p',
              'projects=chromiumos', '-o', 'COMMIT_FOOTERS'
          ]), api.post_process(DropExpectation))
