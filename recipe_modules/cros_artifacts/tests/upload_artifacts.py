# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'cros_artifacts',
    'cros_build_api',
]

import json

from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import ArtifactsByService
from PB.chromiumos.common import BuildTarget


def RunSteps(api):
  config = BuilderConfig()

  api.cros_artifacts.upload_artifacts(
      'builder', BuildTarget(name='target'), config.id.type,
      config.artifacts.artifacts_gs_bucket,
      artifacts_info=config.artifacts.artifacts_info)


def GenTests(api):

  yield api.test(
      'basic',
      api.post_check(lambda check, steps: check('upload artifacts.gsutil rsync'
                                                not in steps)),
      api.cros_build_api.set_api_return('upload artifacts',
                                        'ArtifactsService/Get', '{}'))
