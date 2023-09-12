# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for building the signing docker image."""

from PB.recipes.chromeos.build_signing_docker_image import (
    BuildSigningDockerImageProperties)

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_engine import result as result_pb2
from RECIPE_MODULES.chromeos.gerrit.api import Label
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/scheduler',
    'recipe_engine/step',
    'recipe_engine/time',
    'gerrit',
    'git',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = BuildSigningDockerImageProperties


def RunSteps(api: RecipeApi,
             properties: BuildSigningDockerImageProperties) -> None:
  with api.step.nest('setup build'):
    api.step('git init', ['git', 'init'])
    api.step('gcloud auth configure-docker',
             ['gcloud', 'auth', 'configure-docker', 'us-docker.pkg.dev'])
  # 1. check out the crostools repo.
  with api.step.nest('create docker image'):
    docker_checkout = api.path.mkdtemp()
    with api.context(cwd=docker_checkout):
      api.git.clone(
          'https://chrome-internal.googlesource.com/chromeos/crostools',
          depth=1)
      # 2. build the docker image.
      with api.context(cwd=docker_checkout.join('signing_docker')):
        tag = str(api.time.ms_since_epoch())[0:8]
        image_with_tag = f'signing:{tag}'
        api.step('docker build',
                 ['./setup.py', '-d', f'-t {image_with_tag} -t signing:latest'])
        # 3. upload the docker image to the container registry.
        api.step('docker tag', [
            'docker', 'tag', f'{image_with_tag}',
            f'us-docker.pkg.dev/chromeos-bot/signing/{image_with_tag}'
        ])
        api.step('docker tag', [
            'docker', 'tag', 'signing:latest',
            f'us-docker.pkg.dev/chromeos-bot/signing/signing:latest'
        ])
        if properties.push:
          api.step('docker push', [
              'docker', 'push',
              'us-docker.pkg.dev/chromeos-bot/signing/signing', '--all-tags'
          ])
        else:
          with api.step.nest(
              'skipping pushing image (not in push mode)') as pres:
            pres.step_text = 'would have ran `docker push us-docker.pkg.dev/chromeos-bot/signing/signing --all-tags`'
  # 4. update the docker pin.
  with api.step.nest('update recipes pin'):
    checkout = api.path.mkdtemp()
    with api.context(cwd=checkout):
      api.git.clone(
          'https://chromium.googlesource.com/chromiumos/infra/recipes/',
          depth=1)
      # 3. modify the version file.
      version_file_name = f'{checkout}/infra/config/signing-docker-image.version'
      api.file.write_text(
          'update signing-docker-image version file',
          version_file_name,
          image_with_tag,
          include_log=True,
      )
      # 4. create a cl updating the file.
      api.git.add([version_file_name])
      api.git.commit('update signing-docker-image version')
      change = api.gerrit.create_change('chromiumos/infra/recipes',
                                        ref=api.git.get_branch_ref('main'),
                                        project_path=checkout)
      labels = {
          Label.BOT_COMMIT: 1,
      }
      api.gerrit.set_change_labels_remote(change, labels)
      if properties.push:
        # 5. in push mode, we submit the cl.
        api.gerrit.submit_change(change, project_path=checkout, retries=3)
      else:
        # 5. if not push mode, we abandon the cl.
        api.gerrit.abandon_change(change)
      return result_pb2.RawResult(
          summary_markdown=f'Updated signing-docker-image pin to {image_with_tag}',
          status=common_pb2.SUCCESS,
      )


def GenTests(api: RecipeTestApi) -> None:
  yield api.test(
      'no-push-run',
      api.post_check(post_process.MustRun, 'setup build.git init'),
      api.post_check(post_process.MustRun, 'create docker image.git clone'),
      api.post_check(post_process.MustRun, 'create docker image.docker build'),
      api.post_check(post_process.MustRun, 'create docker image.docker tag'),
      api.post_check(post_process.DoesNotRun,
                     'create docker image.docker push'),
      api.post_check(post_process.MustRun, 'update recipes pin.git clone'),
      api.post_check(
          post_process.MustRun,
          'update recipes pin.update signing-docker-image version file'),
      api.post_check(post_process.MustRun, 'update recipes pin.git add'),
      api.post_check(post_process.MustRun,
                     'update recipes pin.write commit message'),
      api.post_check(post_process.MustRun, 'update recipes pin.git commit'),
      api.post_check(
          post_process.MustRun,
          'update recipes pin.create gerrit change for chromiumos/infra/recipes'
      ),
      api.post_check(post_process.MustRun,
                     'update recipes pin.set labels on CL 1'),
      api.post_check(post_process.MustRun, 'update recipes pin.abandon CL 1'),
      api.post_process(post_process.DropExpectation),
  )
  yield api.test(
      'full-run',
      api.properties(push=True),
      api.post_check(post_process.MustRun, 'setup build.git init'),
      api.post_check(post_process.MustRun, 'create docker image.git clone'),
      api.post_check(post_process.MustRun, 'create docker image.docker build'),
      api.post_check(post_process.MustRun, 'create docker image.docker tag'),
      api.post_check(post_process.MustRun, 'create docker image.docker push'),
      api.post_check(post_process.MustRun, 'update recipes pin.git clone'),
      api.post_check(
          post_process.MustRun,
          'update recipes pin.update signing-docker-image version file'),
      api.post_check(post_process.MustRun, 'update recipes pin.git add'),
      api.post_check(post_process.MustRun,
                     'update recipes pin.write commit message'),
      api.post_check(post_process.MustRun, 'update recipes pin.git commit'),
      api.post_check(
          post_process.MustRun,
          'update recipes pin.create gerrit change for chromiumos/infra/recipes'
      ),
      api.post_check(post_process.MustRun,
                     'update recipes pin.set labels on CL 1'),
      api.post_check(post_process.MustRun, 'update recipes pin.submit CL 1'),
      api.post_process(post_process.DropExpectation),
  )
