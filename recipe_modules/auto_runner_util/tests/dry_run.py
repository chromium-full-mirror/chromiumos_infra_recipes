# -*- codiing: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for executing dry runs."""

from recipe_engine.post_process import DropExpectation, DoesNotRun, MustRun

from RECIPE_MODULES.chromeos.auto_runner_util.api import EnhancedChangeInfo
from PB.recipe_modules.chromeos.auto_runner_util.auto_runner_util import AutoRunnerUtilProperties

DEPS = [
    'auto_runner_util',
    'gerrit',
    'recipe_engine/properties',
]


def RunSteps(api):
  changes = {
      EnhancedChangeInfo({
          '_number': 1234,
          'project': 'mychromiumos'
      }, 'mychromium-review.googlesource.com', api),
      EnhancedChangeInfo({
          '_number': 1235,
          'project': 'mychromiumos'
      }, 'mychromium-review.googlesource.com', api)
  }
  api.auto_runner_util.auto_dry_run_cls(changes)


def GenTests(api):
  yield api.test(
      'basic_with_dry_run_enabled',
      api.properties(
          **{
              '$chromeos/auto_runner_util':
                  AutoRunnerUtilProperties(enable_auto_dry_run=True)
          }),
      api.post_process(MustRun, 'Setting CQ+1 to 2 CLs.add comment on CL 1234'),
      api.post_process(MustRun, 'Setting CQ+1 to 2 CLs.set labels on CL 1234'),
      api.post_process(MustRun, 'Setting CQ+1 to 2 CLs.add comment on CL 1235'),
      api.post_process(MustRun, 'Setting CQ+1 to 2 CLs.set labels on CL 1235'),
      api.post_process(DropExpectation),
  )
  yield api.test(
      'basic_with_dry_run_disabled',
      api.post_process(MustRun, 'Auto dry run disabled. Skipping'),
      api.post_process(DoesNotRun,
                       'Setting CQ+1 to 2 CLs.add comment on CL 1234'),
      api.post_process(DoesNotRun,
                       'Setting CQ+1 to 2 CLs.set labels on CL 1234'),
      api.post_process(DoesNotRun,
                       'Setting CQ+1 to 2 CLs.add comment on CL 1235'),
      api.post_process(DoesNotRun,
                       'Setting CQ+1 to 2 CLs.set labels on CL 1235'),
      api.post_process(DropExpectation),
  )
