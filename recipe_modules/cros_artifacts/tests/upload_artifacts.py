# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'cros_artifacts',
    'cros_build_api',
]

from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import BuildTarget
from recipe_engine import post_process


def RunSteps(api):
  config = BuilderConfig()

  api.cros_artifacts.upload_artifacts(
      'builder', BuildTarget(name='target'), config.id.type,
      config.artifacts.artifacts_gs_bucket,
      artifacts_info=config.artifacts.artifacts_info)


def GenTests(api):

  yield api.test(
      'basic',
      api.post_check(post_process.DoesNotRun, 'upload artifacts.gsutil rsync'),
      api.cros_build_api.set_api_return('upload artifacts',
                                        'ArtifactsService/Get', '{}'))
