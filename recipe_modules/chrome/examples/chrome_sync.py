# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromiumos import common as common_pb2
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.builder_config import BuilderConfig
from recipe_engine import post_process

DEPS = [
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/step',
    'chrome',
    'cros_infra_config',
]



def RunSteps(api):
  with api.step.nest('chrome sync check'):
    cache_path = api.path.cleanup_dir.join('snapshot_chrome')

    # Manufacture the minimal builder config.
    config = BuilderConfig(
        id=BuilderConfig.Id(name='amd64-generic-release',
                            type=BuilderConfig.Id.RELEASE),
        artifacts=BuilderConfig.Artifacts(
            artifacts_info=common_pb2.ArtifactsByService(
                legacy=common_pb2.ArtifactsByService.Legacy(output_artifacts=[
                    common_pb2.ArtifactsByService.Legacy.ArtifactInfo(
                        gs_locations=[
                            'chromeos-image-archive/{target}-release/{version}'
                        ])
                ]),
            )))
    with api.context(cwd=cache_path.join('src')):
      api.chrome.sync_chrome_async(config,
                                   build_target=BuildTarget(name='target'))
      api.chrome.wait_for_sync_chrome_source_async()
      api.chrome.delete_chrome_checkout()


def GenTests(api):

  yield api.test(
      'basic',
      api.post_check(
          post_process.MustRun,
          'chrome sync check.sync chrome source async.sync chrome.gclient sync'
      ),
      api.post_check(post_process.MustRun,
                     'chrome sync check.deleting chrome checkout'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'basic-override-version',
      api.step_data(
          'chrome sync check.sync chrome source async.find chrome cache head.read HEAD ref',
          api.file.read_text('ref: refs/heads/main')),
      api.step_data(
          'chrome sync check.sync chrome source async.find chrome cache head.read HEAD hash',
          api.file.read_text('deadbeef\n')),
      api.post_check(
          post_process.StepCommandContains,
          'chrome sync check.sync chrome source async.sync chrome.gclient sync',
          ['--revision', 'src@deadbeef']),
      api.post_check(post_process.DoesNotRun,
                     'chromite.api.PackageService/GetChromeVersion'),
  )
