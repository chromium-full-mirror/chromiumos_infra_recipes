# -*- codiing: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for get_change_infos_from_gerrit function."""
from recipe_engine import post_process
from recipe_engine.post_process import DropExpectation, MustRun
from RECIPE_MODULES.chromeos.auto_runner_util.api import HOSTS

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

HOSTS = ('chromium',)
PROJECTS = ('chromiumos',)


def RunSteps(api):
  hosts = api.properties['hosts']
  query_params = api.properties['query_params']
  projects = list(api.properties['projects'])
  o_params = list(api.properties['o_params'])
  api.auto_runner_util.get_change_infos_from_gerrit(hosts, projects=projects,
                                                    query_params=query_params,
                                                    o_params=o_params)


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(hosts=HOSTS, query_params=QUERY_PARAMS, projects=PROJECTS,
                     o_params=O_PARAMS),
      api.post_process(MustRun, 'Looking for CLs in host %s' % HOSTS[0]),
      api.post_process(
          post_process.StepCommandContains,
          '''Looking for CLs in host chromium.Looking for CLs in project chromiumos.query https://chromium-review.googlesource.com.gerrit changes''',
          [
              '-p', 'status=open', '-p', 'label=Commit-Queue<=0', '-p',
              'projects=chromiumos', '-o', 'COMMIT_FOOTERS'
          ]), api.post_process(DropExpectation))
