# -*- codiing: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for get_eligible_cls function."""
from recipe_engine import post_process
from recipe_engine.post_process import DropExpectation, MustRun, MustRunRE, DoesNotRun

from PB.recipe_modules.chromeos.auto_runner_util.auto_runner_util import AutoRunnerUtilProperties, HostProjects, CLSignalEnum

DEPS = [
    'auto_runner_util',
    'recipe_engine/properties',
]

def RunSteps(api):
  api.auto_runner_util.get_eligible_cls()


def GenTests(api):
  yield api.test('basic',
                 api.post_process(MustRunRE, r'Looking for CLs in host .*'),
                 api.post_process(MustRun, 'Filtering CLs with Cq-Depend'),
                 api.post_process(MustRun, 'Filtering Related Chain CLs'),
                 api.post_process(MustRun, 'Filtering CLs with No Reviewers'),
                 api.post_process(DropExpectation))
  yield api.test(
      'basic_with_props',
      api.properties(
          **{
              '$chromeos/auto_runner_util':
                  AutoRunnerUtilProperties(
                      max_limit_per_query=2, host_projects=[
                          HostProjects(host='mychromium',
                                       project_prefix=['mychromiumos']),
                      ], cls_signal=CLSignalEnum.PATCHSET_UPLOAD)
          }), api.post_process(MustRun, 'Looking for CLs in host mychromium'),
      api.post_process(
          post_process.StepCommandContains,
          '''Looking for CLs in host mychromium.Looking for CLs in project mychromiumos.query https://mychromium-review.googlesource.com.gerrit changes''',
          [
              '--limit', '2', '-p', 'status=open', '-p',
              'label=Commit-Queue<=0', '-p', 'label=Code-Review>=0', '-p',
              'label=verified>=0', '-p', '-is=wip', '-p',
              'projects=mychromiumos', '-o', 'CURRENT_REVISION', '-o',
              'COMMIT_FOOTERS', '-o', 'REVIEWER_UPDATES'
          ]), api.post_process(DoesNotRun, 'Filtering CLs with No Reviewers'),
      api.post_process(DropExpectation))
