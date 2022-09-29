# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json

from recipe_engine import post_process

DEPS = [
    'recipe_engine/swarming',
    'build_menu',
    'cros_build_api',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  with api.build_menu.configure_builder() as config, \
      api.build_menu.setup_workspace_and_chroot():
    api.build_menu.packages_installed = True
    api.build_menu.upload_artifacts(config=config)


def GenTests(api):
  yield api.build_menu.test(
      'basic',
      api.cros_build_api.set_api_return(
          'upload artifacts', 'ArtifactsService/Get',
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
          'upload artifacts.upload code coverage data (code coverage llvm json)'
      ), cq=True)
