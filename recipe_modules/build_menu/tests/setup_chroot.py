# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test coverage for BuildMenuApi.setup_chroot()."""

from typing import Callable, Generator, Optional

from PB.chromiumos.builder_config import BuilderConfig
from PB.recipe_modules.chromeos.build_menu.tests.test import \
  SetupChrootProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'build_menu',
    'cros_build_api',
    'cros_infra_config',
]

PROPERTIES = SetupChrootProperties

PYTHON_VERSION_COMPATIBILITY = 'PY3'

UPDATE_DICT = {
    SetupChrootProperties.Update.NONE: None,
    SetupChrootProperties.Update.FALSE: False,
    SetupChrootProperties.Update.TRUE: True,
}


def RunSteps(api: RecipeApi, properties: SetupChrootProperties) -> None:
  """Setup the chroot, like a builder might do."""
  with api.build_menu.configure_builder():
    update_bool = UPDATE_DICT[properties.update_chroot]
    api.build_menu.setup_chroot(update=update_bool)


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
  """Define test cases to exercise the logic of setup_chroot()."""

  def _update_chroot_test_case(
      name: str,
      expect_update_sdk: bool,
      *args: TestData,
      expect_setup_toolchains: bool = None,
      update_kwarg: SetupChrootProperties.Update = SetupChrootProperties.Update
      .NONE,
      run_spec: BuilderConfig.RunSpec = (
          BuilderConfig.RunSpec.RUN_SPEC_UNSPECIFIED),
      build_target: Optional[str] = None,
      status: str = 'SUCCESS',
  ) -> TestData:
    """Test whether setup_chroot updates the chroot.

    Internally, this:
      * Defines a custom builder config specifying run_spec;
      * Tells build_menu to specify the build target (if given);
      * Passes `update_kwarg` into the recipe as the `update_chroot` property;
      * Checks whether the 'update sdk' step ran;
      * Checks whether the `setup toolchains` step ran;
      * Whatever else *args specifies;
      * Drops expectations.

    Usage:
      yield _update_chroot_test_case(
        'basic', None, BuilderConfig.RUN_SPEC_UNSPECIFIED, True)

    Args:
      name: The name of the test case.
      expect_update_sdk: Whether the test case should run the `update sdk` step.
      *args: Other stuff to add into the test case.
      expect_setup_toolchains: If given, whether the test case should run the
        `setup toolchains` step.
      update_kwarg: The `update` kwarg that will be passed into setup_chroot().
      run_spec: The RunSpec that will be specified in the BuilderConfig.
      build_target: If given, the build target for this build.
      status: The expected result of the test recipe.

    Returns:
      TestData that fully defines a test case to check whether the SDK gets
      updated.
    """

    def _bool_to_step_checker(expect_run: bool) -> Callable:
      """Return MustRun or DoesNotRun based on the input."""
      return post_process.MustRun if expect_run else post_process.DoesNotRun

    test_case = api.test(
        name,
        api.cros_infra_config.use_custom_builder_config(
            BuilderConfig(
                update_chroot=BuilderConfig.UpdateChroot(
                    run_spec=run_spec,
                )),
            step_name='configure builder.cros_infra_config',
        ), api.properties(update_chroot=update_kwarg), status=status)
    if build_target is not None:
      test_case += api.properties(
          **{
              '$chromeos/build_menu': {
                  'build_target': {
                      'name': 'amd64-generic',
                  },
              },
          },
      )
    test_case += api.post_check(
        _bool_to_step_checker(expect_update_sdk), 'update sdk')
    if expect_setup_toolchains is not None:
      test_case += api.post_check(
          _bool_to_step_checker(expect_setup_toolchains), 'setup toolchains')
    for arg in args:
      test_case += arg
    test_case += api.post_process(post_process.DropExpectation)
    return test_case

  yield _update_chroot_test_case('default', True, expect_setup_toolchains=False)
  yield _update_chroot_test_case('builder-config-specifies-update-chroot', True,
                                 run_spec=BuilderConfig.RunSpec.RUN)
  yield _update_chroot_test_case(
      'builder-config-specifies-do-not-update-chroot', False,
      expect_setup_toolchains=True, run_spec=BuilderConfig.RunSpec.NO_RUN,
      build_target='amd64-generic')

  yield _update_chroot_test_case('kwarg-specifies-update-chroot', True,
                                 update_kwarg=SetupChrootProperties.Update.TRUE)
  yield _update_chroot_test_case(
      'kwarg-specifies-do-not-update-chroot', False,
      update_kwarg=SetupChrootProperties.Update.FALSE)
  yield _update_chroot_test_case('kwarg-update-chroot-overrides-builder-config',
                                 True,
                                 update_kwarg=SetupChrootProperties.Update.TRUE,
                                 run_spec=BuilderConfig.RunSpec.NO_RUN)
  yield _update_chroot_test_case(
      'kwarg-do-not-update-chroot-overrides-builder-config', False,
      update_kwarg=SetupChrootProperties.Update.FALSE,
      run_spec=BuilderConfig.RunSpec.RUN)

  yield _update_chroot_test_case(
      'skip-update-chroot-but-no-toolchain-build-targets',
      False,
      expect_setup_toolchains=False,
      run_spec=BuilderConfig.RunSpec.NO_RUN,
  )

  yield _update_chroot_test_case(
      'skip-update-chroot-but-no-setup-toolchains-endpoint',
      False,
      api.cros_build_api.remove_endpoints(['ToolchainService/SetupToolchains']),
      api.post_check(post_process.StepException, 'setup toolchains'),
      run_spec=BuilderConfig.RunSpec.NO_RUN,
      build_target='amd64-generic',
      status='INFRA_FAILURE',
  )
