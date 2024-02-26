# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for performing various manipulations on ChromeOS signing keys."""

from PB.recipes.chromeos.key_manager import KeyManagerProperties
from PB.chromite.api.signing import CreatePreMPKeysRequest
from PB.chromiumos.common import BuildTarget

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_build_api',
    'git',
    'signing',
    'src_state',
]

PROPERTIES = KeyManagerProperties


def RunSteps(api: RecipeApi, properties: KeyManagerProperties):
  with api.step.nest('set up dependencies'):
    api.git.clone(
        'https://chromium.googlesource.com/chromiumos/chromite/',
        target_path=api.src_state.workspace_path.join('infra/chromite-HEAD'),
        branch='main', single_branch=True)

    api.git.clone(
        'https://chromium.googlesource.com/chromiumos/chromite/',
        target_path=api.src_state.workspace_path.join('infra/chromite'),
        branch='main', single_branch=True)

  if properties.create_premp_keys_requests:
    with api.step.nest('create PreMP keys'):
      api.step('docker auth', [
          'gcloud',
          'auth',
          'configure-docker',
          'us-docker.pkg.dev',
      ])
      api.step('docker pull', [
          'docker',
          'pull',
          api.signing.signing_docker_image,
      ])

      for create_premp_keys_request in properties.create_premp_keys_requests:
        api.cros_build_api.SigningService.CreatePreMPKeys(
            create_premp_keys_request)


def GenTests(api: RecipeTestApi):
  yield api.test(
      'basic',
      api.properties(
          KeyManagerProperties(create_premp_keys_requests=[
              CreatePreMPKeysRequest(build_target=BuildTarget(name='atlas'))
          ])),
      api.post_check(
          post_process.StepCommandContains, 'create PreMP keys.docker pull', [
              'docker', 'pull',
              'us-docker.pkg.dev/chromeos-bot/signing/signing:latest:'
          ]),
      api.post_check(
          post_process.MustRun,
          'create PreMP keys.call chromite.api.SigningService/CreatePreMPKeys'),
      api.post_process(post_process.DropExpectation),
  )
