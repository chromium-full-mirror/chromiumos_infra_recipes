# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test coverage for BuildMenuApi.setup_chroot()."""

from typing import Generator, Optional

from PB.chromiumos.builder_config import BuilderConfig
from recipe_engine import post_process
from recipe_engine.recipe_api import Property
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'build_menu',
    'cros_infra_config',
]

PROPERTIES = {'update_chroot': Property(kind=bool, default=None)}

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api: RecipeApi, update_chroot: Optional[bool]) -> None:
  """Setup the chroot, like a builder might do."""
  with api.build_menu.configure_builder():
    api.build_menu.setup_chroot(update=update_chroot)


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
  """Define test cases to exercise the logic of setup_chroot()."""

  def _update_chroot_test_case(
      name: str,
      expect_update_sdk: bool,
      update_kwarg: Optional[bool] = None,
      run_spec: BuilderConfig.RunSpec = (
          BuilderConfig.RunSpec.RUN_SPEC_UNSPECIFIED),
  ) -> TestData:
    """Test whether setup_chroot updates the chroot.

    Internally, this:
      * Defines a custom builder config specifying run_spec;
      * Passes `update_kwarg` into the recipe as the `update_chroot` property;
      * Checks whether the 'update sdk' step ran;
      * Drops expectations.

    Usage:
      yield _update_chroot_test_case(
        'basic', None, BuilderConfig.RUN_SPEC_UNSPECIFIED, True)

    Args:
      name: The name of the test case.
      expect_update_sdk: Whether the test case should run the `update sdk` step.
      update_kwarg: The `update` kwarg that will be passed into setup_chroot().
      run_spec: The RunSpec that will be specified in the BuilderConfig.

    Returns:
      TestData that fully defines a test case to check whether the SDK gets
      updated.
    """
    step_checker = (
        post_process.MustRun if expect_update_sdk else post_process.DoesNotRun)
    return api.test(
        name,
        api.cros_infra_config.use_custom_builder_config(
            BuilderConfig(
                update_chroot=BuilderConfig.UpdateChroot(
                    run_spec=run_spec,
                )),
            step_name='configure builder.cros_infra_config',
        ),
        api.properties(update_chroot=update_kwarg),
        api.post_check(step_checker, 'update sdk'),
        api.post_process(post_process.DropExpectation),
    )

  yield _update_chroot_test_case('default', True)
  yield _update_chroot_test_case('builder-config-specifies-update-chroot', True,
                                 run_spec=BuilderConfig.RunSpec.RUN)
  yield _update_chroot_test_case(
      'builder-config-specifies-do-not-update-chroot', False,
      run_spec=BuilderConfig.RunSpec.NO_RUN)
  yield _update_chroot_test_case('kwarg-specifies-update-chroot', True,
                                 update_kwarg=True)
  yield _update_chroot_test_case('kwarg-specifies-do-not-update-chroot', False,
                                 update_kwarg=False)
  yield _update_chroot_test_case('kwarg-update-chroot-overrides-builder-config',
                                 True, update_kwarg=True,
                                 run_spec=BuilderConfig.RunSpec.NO_RUN)
  yield _update_chroot_test_case(
      'kwarg-do-not-update-chroot-overrides-builder-config', False,
      update_kwarg=False, run_spec=BuilderConfig.RunSpec.RUN)
