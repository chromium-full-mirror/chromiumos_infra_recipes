# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto.build import Build
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

from recipe_engine import post_process

DEPS = [
    'recipe_engine/properties',
    'auto_retry_util',
    'test_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  build = Build(
      id=123,
      input=Build.Input(
          gerrit_changes=[
              GerritChange(
                  host='chromium.googlesource.com',
                  project='projectA',
                  change=456,
                  patchset=1,
              ),
              GerritChange(
                  host='chromium.googlesource.com',
                  project='projectB',
                  change=789,
                  patchset=4,
              ),
          ],
      ),
  )
  build.input.properties['$recipe_engine/cq'] = {
      'runMode': api.properties['runMode']
  }

  api.auto_retry_util.retry_build(build)


def GenTests(api):

  yield api.test(
      'retry-build',
      api.properties(
          runMode='FULL_RUN',
      ),
      api.post_process(
          post_process.StepCommandContains,
          'retry build 123.set labels on CL 456.curl https://chromium.googlesource.com/changes/456/revisions/current/review',
          [
              r'{"labels": {"Commit-Queue": 2}}',
              'https://chromium.googlesource.com/changes/456/revisions/current/review'
          ],
      ),
      api.post_process(
          post_process.StepCommandContains,
          'retry build 123.set labels on CL 789.curl https://chromium.googlesource.com/changes/789/revisions/current/review',
          [
              r'{"labels": {"Commit-Queue": 2}}',
              'https://chromium.googlesource.com/changes/789/revisions/current/review'
          ],
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'dry-run',
      api.properties(
          runMode='DRY_RUN',
      ),
      api.post_process(
          post_process.StepCommandContains,
          'retry build 123.set labels on CL 456.curl https://chromium.googlesource.com/changes/456/revisions/current/review',
          [
              r'{"labels": {"Commit-Queue": 1}}',
              'https://chromium.googlesource.com/changes/456/revisions/current/review'
          ],
      ),
      api.post_process(post_process.DropExpectation),
  )
