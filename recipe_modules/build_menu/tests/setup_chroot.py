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
    SetupChrootProperties.OptionalBool.NONE: None,
    SetupChrootProperties.OptionalBool.FALSE: False,
    SetupChrootProperties.OptionalBool.TRUE: True,
}


def RunSteps(api: RecipeApi, properties: SetupChrootProperties) -> None:
  """Setup the chroot, like a builder might do."""
  with api.build_menu.configure_builder():
    force_no_chroot_upgrade = UPDATE_DICT[properties.force_no_chroot_upgrade]
    api.build_menu.setup_chroot(force_no_chroot_upgrade=force_no_chroot_upgrade)


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
  """Define test cases to exercise the logic of setup_chroot()."""

  def _sdk_update_test_case(
      name: str,
      expect_update_sdk: bool,
      *args: TestData,
      expect_setup_toolchains: bool = False,
      force_no_chroot_upgrade: SetupChrootProperties.OptionalBool = (
          SetupChrootProperties.OptionalBool.NONE),
      sdk_update_run_spec: BuilderConfig.RunSpec = (
          BuilderConfig.RunSpec.RUN_SPEC_UNSPECIFIED),
      build_target: Optional[str] = None,
      status: str = 'SUCCESS',
  ) -> TestData:
    """Test whether setup_chroot updates the SDK.

    Internally, this:
      * Defines a custom builder config specifying sdk_update_run_spec;
      * Tells build_menu to specify the build target (if given);
      * Passes `update_kwarg` into the recipe as the `sdk_update` property;
      * Checks whether the 'update sdk' step ran;
      * Checks whether the `setup toolchains` step ran;
      * Drops expectations.

    Usage:
      yield _sdk_update_test_case(
        'basic', None, BuilderConfig.RUN_SPEC_UNSPECIFIED, True)

    Args:
      name: The name of the test case.
      expect_update_sdk: Whether the test case should run the `update sdk` step.
      *args: Other stuff to add into the test case.
      expect_setup_toolchains: Whether the test case should run the `setup
        toolchains` step.
      force_no_chroot_upgrade: What should be passed to force_no_chroot_upgrade
        argument of setup_chroot.
      sdk_update_run_spec: The RunSpec that will be specified in the
        BuilderConfig.
      build_target: If given, the build target for this build.
      status: The expected result of the test recipe.

    Returns:
      TestData that fully defines a test case to check whether the SDK gets
      updated.
    """
    use_custom_builder_config = api.cros_infra_config.use_custom_builder_config(
        BuilderConfig(
            build=BuilderConfig.Build(
                sdk_update=BuilderConfig.Build.SdkUpdate(
                    sdk_update_run_spec=sdk_update_run_spec))),
        step_name='configure builder.cros_infra_config')
    properties = {'force_no_chroot_upgrade': force_no_chroot_upgrade}
    if build_target is not None:
      properties['$chromeos/build_menu'] = {
          'build_target': {
              'name': 'amd64-generic'
          }
      }
    check_update_sdk = api.post_check(
        _get_run_checker(expect_update_sdk), 'update sdk')
    check_setup_toolchains = api.post_check(
        _get_run_checker(expect_setup_toolchains), 'setup toolchains')

    return api.test(name, use_custom_builder_config,
                    api.properties(**properties), check_update_sdk,
                    check_setup_toolchains, *args,
                    api.post_process(post_process.DropExpectation),
                    status=status)

  yield _sdk_update_test_case('default', True)
  yield _sdk_update_test_case('default-with-build-target', True,
                              build_target='amd64-generic')

  yield _sdk_update_test_case(
      'skip-update-sdk-via-run-spec',
      False,
      expect_setup_toolchains=True,
      sdk_update_run_spec=BuilderConfig.RunSpec.NO_RUN,
      build_target='amd64-generic',
  )

  # force_no_chroot_upgrade should override the run_spec.
  yield _sdk_update_test_case(
      'force-no-chroot-upgrade',
      False,
      force_no_chroot_upgrade=SetupChrootProperties.OptionalBool.TRUE,
      sdk_update_run_spec=BuilderConfig.RUN,
      expect_setup_toolchains=True,
      build_target='amd64-generic',
  )

  yield _sdk_update_test_case(
      'skip-update-sdk-but-no-toolchain-build-targets',
      False,
      expect_setup_toolchains=False,
      sdk_update_run_spec=BuilderConfig.RunSpec.NO_RUN,
  )
  yield _sdk_update_test_case(
      'skip-update-sdk-but-no-setup-toolchains-endpoint',
      False,
      api.cros_build_api.remove_endpoints(['ToolchainService/SetupToolchains']),
      api.post_check(post_process.StepException, 'setup toolchains'),
      sdk_update_run_spec=BuilderConfig.RunSpec.NO_RUN,
      expect_setup_toolchains=True,
      build_target='amd64-generic',
      status='INFRA_FAILURE',
  )


def _get_run_checker(expect_run: bool) -> Callable:
  """Return MustRun or DoesNotRun based on the input."""
  return post_process.MustRun if expect_run else post_process.DoesNotRun
