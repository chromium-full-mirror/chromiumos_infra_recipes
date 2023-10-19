# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for uprev'ing various pins in infra/recipes/infra/config."""

from typing import Callable

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_engine import result as result_pb2
from PB.recipes.chromeos.uprev_recipes_pin import (UprevRecipesPinProperties)
from RECIPE_MODULES.chromeos.gerrit.api import Label
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'recipe_engine/time',
    'gerrit',
    'git',
    'gobin',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = UprevRecipesPinProperties


class PinInfo():
  """Info for a particular pin."""

  def __init__(self, pin: UprevRecipesPinProperties.Pin, pin_file: str,
               pin_fn: Callable[[RecipeApi, UprevRecipesPinProperties, str],
                                str]):
    self.pin = pin
    self.pin_file = pin_file
    self.pin_fn = pin_fn


def _get_chromite_pin(api: RecipeApi, _properties: UprevRecipesPinProperties,
                      _current_pin_value: str) -> str:
  """Get the new value for the chromite HEAD pin, i.e. the ToT commit."""
  api.step('git init', ['git', 'init'])
  with api.step.nest('get latest commit') as step:
    commit = api.git.fetch_ref(
        'https://chromium.googlesource.com/chromiumos/chromite/',
        'refs/heads/main')
    step.step_text = f'commit: {commit}'
    return commit


def _get_signing_docker_pin(api: RecipeApi,
                            properties: UprevRecipesPinProperties,
                            _current_pin_value: str) -> str:
  """Get the new value for the signing docker image pin."""
  with api.step.nest('setup build'):
    api.step('git init', ['git', 'init'])
    api.step('gcloud auth configure-docker',
             ['gcloud', 'auth', 'configure-docker', 'us-docker.pkg.dev'])
  # Check out the crostools repo.
  with api.step.nest('create docker image'):
    docker_checkout = api.path.mkdtemp()
    with api.context(cwd=docker_checkout):
      api.git.clone(
          'https://chrome-internal.googlesource.com/chromeos/crostools',
          depth=1)
      # Build the docker image.
      with api.context(cwd=docker_checkout.join('signing_docker')):
        tag = str(api.time.ms_since_epoch())[0:8]
        image_with_tag = f'signing:{tag}'
        api.step('docker build',
                 ['./setup.py', '-d', f'-t {image_with_tag} -t signing:latest'])
        # Upload the docker image to the container registry.
        api.step('docker tag', [
            'docker', 'tag', f'{image_with_tag}',
            f'us-docker.pkg.dev/chromeos-bot/signing/{image_with_tag}'
        ])
        api.step('docker tag', [
            'docker', 'tag', 'signing:latest',
            'us-docker.pkg.dev/chromeos-bot/signing/signing:latest'
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
        return image_with_tag


def _get_infrainfra_golang_pin(api: RecipeApi, _: UprevRecipesPinProperties,
                               current_pin_value: str) -> str:
  """Get the new value for the infra/infra golang pin."""
  return api.gobin.get_latest_pin_value(current_pin_value)


# Maps supported pins to fns to get the new pin value.
SUPPORTED_PINS = {
    UprevRecipesPinProperties.CHROMITE_HEAD:
        PinInfo(UprevRecipesPinProperties.CHROMITE_HEAD,
                'chromite-HEAD.version', _get_chromite_pin),
    UprevRecipesPinProperties.SIGNING_DOCKER_IMAGE:
        PinInfo(UprevRecipesPinProperties.SIGNING_DOCKER_IMAGE,
                'signing-docker-image.version', _get_signing_docker_pin),
    UprevRecipesPinProperties.INFRAINFRA_GOLANG:
        PinInfo(UprevRecipesPinProperties.INFRAINFRA_GOLANG,
                'infrainfra-golang.version', _get_infrainfra_golang_pin),
}


def RunSteps(api: RecipeApi, properties: UprevRecipesPinProperties) -> None:
  if properties.pin not in SUPPORTED_PINS:
    raise StepFailure('unsupported pin')
  pin_info = SUPPORTED_PINS[properties.pin]

  # Clone the recipes repo in a temp dir.
  checkout = api.path.mkdtemp()
  with api.context(cwd=checkout):
    api.git.clone('https://chromium.googlesource.com/chromiumos/infra/recipes/',
                  depth=1)

    # Get the existing pin value.
    version_file_name = f'{checkout}/infra/config/{pin_info.pin_file}'
    current_pin_value = api.file.read_text(
        f'read {pin_info.pin_file} file',
        version_file_name,
        include_log=True,
    ).strip()

    # Get the new pin value.
    pin_name = UprevRecipesPinProperties.Pin.Name(properties.pin)
    new_pin_value = None
    with api.step.nest(f'get new pin value for {pin_name}'):
      new_pin_value = SUPPORTED_PINS[properties.pin].pin_fn(
          api, properties, current_pin_value)

    # Modify the version file.
    api.file.write_text(
        f'update {pin_info.pin_file} file',
        version_file_name,
        new_pin_value,
        include_log=True,
    )
    # Check to make sure there was actually a change.
    if not api.git.diff_check(version_file_name):
      return result_pb2.RawResult(
          summary_markdown='No new commits since last uprev',
          status=common_pb2.SUCCESS,
      )
    # Create a cl updating the file.
    api.git.add([version_file_name])
    commit_lines = [
        f'Update {pin_info.pin_file}',
        '',
        f'Generated by {api.buildbucket.build_url()}.',
    ]
    api.git.commit('\n'.join(commit_lines))
    change = api.gerrit.create_change('chromiumos/infra/recipes',
                                      ref=api.git.get_branch_ref('main'),
                                      project_path=checkout)
    labels = {
        Label.BOT_COMMIT: 1,
    }
    api.gerrit.set_change_labels_remote(change, labels)
    if properties.push:
      # In production mode, we submit the cl.
      api.gerrit.submit_change(change, project_path=checkout, retries=3)
    else:
      # In dry_run mode, we abandon the cl.
      api.gerrit.abandon_change(change)
    return result_pb2.RawResult(
        summary_markdown=f'Updated {pin_info.pin_file} pin to {new_pin_value}',
        status=common_pb2.SUCCESS,
    )


def GenTests(api: RecipeTestApi) -> None:
  yield api.test(
      'unsupported-pin',
      api.properties(pin=UprevRecipesPinProperties.UNSPECIFIED),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'chromite-head-dry-run',
      api.properties(pin=UprevRecipesPinProperties.CHROMITE_HEAD),
      api.git.diff_check(True),
      api.post_check(post_process.StepTextEquals,
                     'get new pin value for CHROMITE_HEAD.get latest commit',
                     'commit: deadbeefdeadbeefdeadbeefdeadbeefdeadbeef'),
      api.post_check(post_process.MustRun,
                     'get new pin value for CHROMITE_HEAD.git init'),
      api.post_check(post_process.MustRun, 'git clone'),
      api.post_check(post_process.MustRun, 'update chromite-HEAD.version file'),
      api.post_check(post_process.MustRun, 'git add'),
      api.post_check(post_process.MustRun, 'write commit message'),
      api.post_check(post_process.MustRun, 'git commit'),
      api.post_check(post_process.MustRun,
                     'create gerrit change for chromiumos/infra/recipes'),
      api.post_check(post_process.MustRun, 'set labels on CL 1'),
      api.post_check(post_process.MustRun, 'abandon CL 1'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'chromite-head-no-diff',
      api.properties(push=True, pin=UprevRecipesPinProperties.CHROMITE_HEAD),
      api.git.diff_check(False),
      api.post_check(post_process.StepTextEquals,
                     'get new pin value for CHROMITE_HEAD.get latest commit',
                     'commit: deadbeefdeadbeefdeadbeefdeadbeefdeadbeef'),
      api.post_check(post_process.MustRun,
                     'get new pin value for CHROMITE_HEAD.git init'),
      api.post_check(post_process.MustRun, 'git clone'),
      api.post_check(post_process.MustRun, 'update chromite-HEAD.version file'),
      api.post_check(post_process.DoesNotRun, 'git add'),
      api.post_check(post_process.DoesNotRun, 'write commit message'),
      api.post_check(post_process.DoesNotRun, 'git commit'),
      api.post_check(post_process.DoesNotRun,
                     'create gerrit change for chromiumos/infra/recipes'),
      api.post_check(post_process.DoesNotRun, 'set labels on CL 1'),
      api.post_check(post_process.DoesNotRun, 'submit CL 1'),
      api.post_process(post_process.DropExpectation),
  )
  yield api.test(
      'chromite-head-full-run',
      api.properties(push=True, pin=UprevRecipesPinProperties.CHROMITE_HEAD),
      api.git.diff_check(True),
      api.post_check(post_process.StepTextEquals,
                     'get new pin value for CHROMITE_HEAD.get latest commit',
                     'commit: deadbeefdeadbeefdeadbeefdeadbeefdeadbeef'),
      api.post_check(post_process.MustRun,
                     'get new pin value for CHROMITE_HEAD.git init'),
      api.post_check(post_process.MustRun, 'git clone'),
      api.post_check(post_process.MustRun, 'update chromite-HEAD.version file'),
      api.post_check(post_process.MustRun, 'git add'),
      api.post_check(post_process.MustRun, 'write commit message'),
      api.post_check(post_process.MustRun, 'git commit'),
      api.post_check(post_process.MustRun,
                     'create gerrit change for chromiumos/infra/recipes'),
      api.post_check(post_process.MustRun, 'set labels on CL 1'),
      api.post_check(post_process.MustRun, 'submit CL 1'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'docker-dry-run',
      api.properties(pin=UprevRecipesPinProperties.SIGNING_DOCKER_IMAGE),
      api.post_check(
          post_process.MustRun,
          'get new pin value for SIGNING_DOCKER_IMAGE.setup build.git init'),
      api.post_check(
          post_process.MustRun,
          'get new pin value for SIGNING_DOCKER_IMAGE.create docker image.git clone'
      ),
      api.post_check(
          post_process.MustRun,
          'get new pin value for SIGNING_DOCKER_IMAGE.create docker image.docker build'
      ),
      api.post_check(
          post_process.MustRun,
          'get new pin value for SIGNING_DOCKER_IMAGE.create docker image.docker tag'
      ),
      api.post_check(
          post_process.DoesNotRun,
          'get new pin value for SIGNING_DOCKER_IMAGE.create docker image.docker push'
      ),
      # File / gerrit logic tested in chromite unit tests.
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'docker-full-run',
      api.properties(push=True,
                     pin=UprevRecipesPinProperties.SIGNING_DOCKER_IMAGE),
      api.post_check(
          post_process.MustRun,
          'get new pin value for SIGNING_DOCKER_IMAGE.setup build.git init'),
      api.post_check(
          post_process.MustRun,
          'get new pin value for SIGNING_DOCKER_IMAGE.create docker image.git clone'
      ),
      api.post_check(
          post_process.MustRun,
          'get new pin value for SIGNING_DOCKER_IMAGE.create docker image.docker build'
      ),
      api.post_check(
          post_process.MustRun,
          'get new pin value for SIGNING_DOCKER_IMAGE.create docker image.docker tag'
      ),
      api.post_check(
          post_process.MustRun,
          'get new pin value for SIGNING_DOCKER_IMAGE.create docker image.docker push'
      ),
      # File / gerrit logic tested in chromite unit tests.
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'infrainfra-golang-full-run-no-change',
      api.properties(push=True,
                     pin=UprevRecipesPinProperties.INFRAINFRA_GOLANG),
      api.step_data(
          'read infrainfra-golang.version file',
          api.file.read_text('deadbeef'),
      ),
      api.step_data(
          'get new pin value for INFRAINFRA_GOLANG.get commits since deadbeef',
          stdout=api.raw_io.output_text('\n'.join(['CAFECAFE']))),
      # Easiest not to mock anything and fall back to the existing pin.
      # get_latest_pin_value is well tested in the gobin module, and
      # file / gerrit logic is tested in the chromite unit tests above.
      api.post_check(post_process.StepCommandContains,
                     'update infrainfra-golang.version file', 'deadbeef'),
      api.post_process(post_process.DropExpectation),
  )
