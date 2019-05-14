# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/buildbucket',
    'cros_infra_config',
]


def RunSteps(api):
  api.cros_infra_config.get_builder_config(
      api.buildbucket.build.builder.builder)


def attempt_download_file(api, attempt):
  step_text = 'read build config.fetch master:generated/builder_configs.cfg'
  if attempt > 1:
    step_text += ' (' + str(attempt) + ')'
  return api.step_data(
      step_text,
      times_out_after=(api.cros_infra_config.gitiles_timeout_seconds + 1))


def GenTests(api):
  yield (api.test('retry_success_gitiles') + attempt_download_file(api, 1) +
         attempt_download_file(api, 2) + api.buildbucket.ci_build(
             project='chromeos', bucket='postsubmit',
             builder='postsubmit-orchestrator'))
