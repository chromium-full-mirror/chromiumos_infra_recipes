# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that runs the Subtools Builder.

The Subtools builder starts with an SDK, builds some additional _host_ packages,
then exports build artifacts to external locations, such as CIPD.
"""

import contextlib
from typing import Generator

from PB.chromite.api.sdk_subtools import BuildSdkSubtoolsRequest
from recipe_engine import recipe_api
from recipe_engine import recipe_test_api
from recipe_engine import post_process

DEPS = [
    'recipe_engine/step',
    'build_menu',
    'cros_build_api',
    'cros_sdk',
    'cros_source',
    'failures',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api: recipe_api.RecipeApi) -> None:
  return BuildSdkSubtoolsRun(api).run()


class BuildSdkSubtoolsRun:
  """Class to encapsulate a single run of the SDK subtools builder."""

  def __init__(self, api: recipe_api.RecipeApi) -> None:
    """Initialize the builder run."""
    self.m = api

  def run(self) -> None:
    """Run the main logic for this builder."""
    with self._setup(), self.m.step.nest('Build SDK Subtools') as step:
      request = BuildSdkSubtoolsRequest(chroot=self.m.cros_sdk.chroot)
      response = self.m.cros_build_api.SdkSubtoolsService.BuildSdkSubtools(
          request, response_lambda=self.m.cros_build_api.failed_pkg_data_names,
          pkg_logs_lambda=self.m.cros_build_api.failed_pkg_logs)
      pkgs = self.m.cros_build_api.failed_pkg_logs(request, response)
      self.m.failures.set_test_failed_packages(step, pkgs)

  @contextlib.contextmanager
  def _setup(self) -> Generator:
    """Configure the builder and setup the workspace and chroot."""
    with self.m.build_menu.configure_builder(missing_ok=True), \
        self.m.build_menu.setup_workspace_and_chroot(
            force_no_chroot_upgrade=True) as context:
      # TBD how far we can get re-using the cros_sdk recipe. It will create and
      # use chroots in `m.path / cache / cros_chroot / chroot`, but the subtools
      # builder might be more efficient using its own `subtools_chroot` scope so
      # that there is more control over when to mark it "dirty".
      # For now, always mark the SDK "dirty" as a precaution.
      self.m.cros_sdk.mark_sdk_as_dirty()
      yield context


def GenTests(api: recipe_test_api.RecipeTestApi) -> Generator:
  BUILD_SDK_SUBTOOLS_CALL_STEP = (
      'Build SDK Subtools.call'
      ' chromite.api.SdkSubtoolsService/BuildSdkSubtools.call build API script')
  INIT_SDK_CALL_STEP = ('init sdk.call chromite.api.SdkService/Create.call'
                        ' build API script')

  yield api.test(
      'basic',
      api.post_check(post_process.StepSuccess, BUILD_SDK_SUBTOOLS_CALL_STEP),
      api.post_check(post_process.MustRun, BUILD_SDK_SUBTOOLS_CALL_STEP),
      status='SUCCESS',
  )

  yield api.test(
      'build-sdk-subtools-step-failure',
      api.step_data(BUILD_SDK_SUBTOOLS_CALL_STEP, retcode=1),
      api.post_check(post_process.MustRun, BUILD_SDK_SUBTOOLS_CALL_STEP),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'init-sdk-step-failure',
      api.step_data(INIT_SDK_CALL_STEP, retcode=1),
      api.post_check(post_process.DoesNotRun, BUILD_SDK_SUBTOOLS_CALL_STEP),
      api.post_process(post_process.DropExpectation),
      status='INFRA_FAILURE',
  )
