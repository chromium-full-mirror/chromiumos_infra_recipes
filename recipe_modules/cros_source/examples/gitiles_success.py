# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'cros_source',
]


def RunSteps(api):
  with api.cros_source.checkout_overlays_context():
    with api.context(cwd=api.cros_source.workspace_path):
      api.cros_source.sync_gitiles_snapshot(api.buildbucket.gitiles_commit)


def attempt_download_file(api, attempt):
  step_text = (u'sync to snapshot.fetch '
               '2d72510e447ab60a9728aeea2362d8be2cbd7789:snapshot.xml')
  if attempt > 1:
    step_text += ' (' + str(attempt) + ')'
  return api.step_data(
      step_text, times_out_after=(api.cros_source.gitiles_timeout_seconds + 1))


def GenTests(api):
  yield (api.test('failed_gitiles') +  #
         attempt_download_file(api, 1) +  #
         attempt_download_file(api, 2) +  #
         api.buildbucket.ci_build())
