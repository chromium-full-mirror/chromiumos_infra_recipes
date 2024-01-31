# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromite.api.sysroot import Sysroot
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import BuildTarget
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'cros_artifacts',
    'cros_build_api',
]



def RunSteps(api):
  config = BuilderConfig()

  api.cros_artifacts.upload_artifacts(
      'builder', config.id.type, config.artifacts.artifacts_gs_bucket,
      artifacts_info=config.artifacts.artifacts_info,
      sysroot=Sysroot(path='/build/target',
                      build_target=BuildTarget(name='target')))


def GenTests(api):

  yield api.test(
      'basic',
      api.post_check(post_process.DoesNotRun, 'upload artifacts.gsutil rsync'),
      api.cros_build_api.set_api_return(
          'upload artifacts.call artifacts service', 'ArtifactsService/Get',
          '{}'))
