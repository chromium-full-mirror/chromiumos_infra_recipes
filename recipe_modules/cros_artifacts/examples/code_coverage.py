# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

import json

from recipe_engine import post_process

DEPS = [
    'recipe_engine/raw_io',
    'recipe_engine/swarming',
    'build_menu',
    'cros_build_api',
]



def RunSteps(api):
  with api.build_menu.configure_builder() as config, \
      api.build_menu.setup_workspace_and_chroot():
    api.build_menu.packages_installed = True
    api.build_menu.upload_artifacts(config=config)


def GenTests(api):
  yield api.build_menu.test(
      'basic',
      api.cros_build_api.set_api_return(
          'upload artifacts.call artifacts service', 'ArtifactsService/Get',
          json.dumps(
              {
                  'artifacts': {
                      'test': {
                          'artifacts': [{
                              'artifactType':
                                  39,
                              'paths': [{
                                  'path': '[START_DIR]/coverage.tbz2',
                                  'location': 2
                              }]
                          },]
                      }
                  }
              }, sort_keys=True)),
      api.post_check(
        post_process.MustRun,
        'upload artifacts.upload code coverage data'),
      cq=True
    )

  yield api.build_menu.test(
      'e2e_coverage',
      api.cros_build_api.set_api_return(
          'upload artifacts.call artifacts service', 'ArtifactsService/Get',
          json.dumps(
              {
                  'artifacts': {
                      'test': {
                          'artifacts': [{
                              'artifactType':
                                  54,
                              'paths': [{
                                  'path': '[START_DIR]/coverage.tbz2',
                                  'location': 2
                              }]
                          },]
                      }
                  }
              }, sort_keys=True)),
      api.step_data(
          'upload artifacts.gsutil ls snapshot version',
          stdout=api.raw_io.output_text('''
            gs://chromeos-image-archive/brya-snapshot/8766842719767962417/
          '''), retcode=0),
      api.post_check(
          post_process.MustRun,
          'upload artifacts.upload e2e coverage metadata.add e2e coverage metadata'
      ))
